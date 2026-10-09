"""Vobiz webhooks: ``POST /ivr/vobiz/{token}/{answer|digits|recording|status|inbound}``.

Checks, in order: the secret path token (SSM ``ivr_path_token``), the optional source-IP
allowlist, and the optional Vobiz signature. Then the IVR engine runs one turn and the reply is
VobizXML. Our own ``call_id`` travels in each URL's query, and ``turn`` in the digits URL, so a
duplicate or stale webhook replays the current prompt instead of applying an input twice.

A call ends on the flow's last turn or on the hangup callback, whichever comes first; both
paths write the CheckIn once and resume the waiting workflow task.

``inbound`` is the answer URL of the number's Vobiz Application: a resident's missed call. It is
rejected at once (the caller pays nothing) and a call-back is queued (§15.4). A finished voice
note is handed to the notes Lambda asynchronously, so the caller never waits for transcription.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import re
from datetime import timedelta
from typing import Any, Final
from urllib.parse import urlencode

from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response

from jalsakshi.core.models import CapturedVia, Purpose
from jalsakshi.handlers import config, residents, speech
from jalsakshi.handlers.calls import (
    CallRecord,
    LoadedCall,
    callback_queued,
    finish_call,
    load_call,
    save_call,
)
from jalsakshi.handlers.common import activity, count, entrypoint, logger, mask_phone
from jalsakshi.store import Repository
from jalsakshi.voice import flow as ivr
from jalsakshi.voice.actions import Action, Hangup, Play
from jalsakshi.voice.adapters.vobiz import (
    CONTENT_TYPE,
    EMPTY_RESPONSE,
    XML_DECLARATION,
    VobizEvent,
    parse_form,
    parse_webhook,
    render_xml,
    validate_signature,
)
from jalsakshi.voice.catalog import audio_base_for, catalog_for

MIN_NOTE_S: Final = 1
HANGUP_XML: Final = f"{XML_DECLARATION}<Response><Hangup /></Response>"
REJECT_XML: Final = f'{XML_DECLARATION}<Response><Hangup reason="rejected" /></Response>'
CALLBACK_COOLDOWN: Final = timedelta(minutes=10)
_DIGITS_ONLY: Final = re.compile(r"\D")

app = APIGatewayHttpResolver()


@app.post("/ivr/vobiz/<token>/<action>")
def webhook(token: str, action: str) -> Response:
    """One Vobiz callback; replies with VobizXML (or 404 for an untrusted request)."""
    if not _trusted(token):
        return Response(404, "text/plain", "not found")
    current = app.current_event
    try:
        event = parse_webhook(parse_form(current.body, base64_encoded=current.is_base64_encoded))
    except ValueError:
        return Response(400, "text/plain", "bad request")
    call_id = current.get_query_string_value("call_id") or ""
    repo = config.repository()
    match action:
        case "inbound":
            try:
                return _xml(_inbound(repo, event))
            except Exception:  # a missed call is always rejected (never answered and charged)
                logger.exception("missed call not queued")
                return _xml(REJECT_XML)
        case "answer":
            return _xml(_answer(repo, call_id, event))
        case "digits":
            return _xml(_digits(repo, call_id, _turn(), event))
        case "recording":
            _recording(repo, call_id, event)
            return _xml(EMPTY_RESPONSE)
        case "status":
            _status(repo, call_id, event)
            return _xml(EMPTY_RESPONSE)
    return Response(404, "text/plain", "not found")


@app.exception_handler(Exception)
def _crash(exc: Exception) -> Response:
    """Never leave a caller in silence: log and hang up politely."""
    logger.exception("ivr webhook failed", extra={"error_type": type(exc).__name__})
    return _xml(HANGUP_XML)


@entrypoint
def handler(event: Any, context: Any) -> Any:
    """Lambda entrypoint for the Vobiz webhooks."""
    return app.resolve(event, context)


def _answer(repo: Repository, call_id: str, event: VobizEvent) -> str:
    loaded = load_call(repo, call_id) if call_id else None
    if loaded is None or loaded.record.finished:
        return HANGUP_XML
    record = loaded.record
    if record.provider_call_uuid is None:
        record = record.model_copy(update={"provider_call_uuid": event.call_uuid})
    flow, actions = ivr.start(residents.with_language(repo, record.flow))
    record = record.model_copy(update={"flow": flow})
    save_call(repo, record)
    return _render(actions, record)


def _digits(repo: Repository, call_id: str, turn: int, event: VobizEvent) -> str:
    loaded = load_call(repo, call_id) if call_id else None
    if loaded is None:
        return HANGUP_XML
    record = loaded.record
    if record.finished or record.flow.done:
        return _render(ivr.current_actions(record.flow), record)
    step = {"digits": event.digits, "timeout": event.is_timeout}
    if turn != record.flow.turn or not repo.record_call_step(call_id, f"turn-{turn:03d}", step):
        return _render(ivr.current_actions(record.flow), record)
    flow, actions, done = ivr.on_input(record.flow, event.digits, timeout=event.is_timeout)
    record = record.model_copy(update={"flow": flow})
    save_call(repo, record)
    if done:
        finished = finish_call(repo, LoadedCall(record, loaded.task_token), CapturedVia.DTMF)
        actions = _announce_number(actions, finished)
    return _render(actions, record)


def _announce_number(actions: list[Action], record: CallRecord) -> list[Action]:
    """Tell a resident the number of the complaint their missed call opened or joined."""
    if record.ticket_number is None or record.flow.purpose is not Purpose.REPORT:
        return actions
    cat = catalog_for(record.flow.language)
    key = cat.audio_key("report.number", number=record.ticket_number) or "report.number"
    number = Play(prompt_key=key, text_hi=cat.text("report.number", number=record.ticket_number))
    if actions and isinstance(actions[-1], Hangup):
        return [*actions[:-1], number, actions[-1]]
    return [*actions, number]


def _recording(repo: Repository, call_id: str, event: VobizEvent) -> None:
    """Keep the note's recording URL and hand it to the notes Lambda (skipped notes ignored)."""
    if not event.recording_url or (event.recording_duration_s or 0) < MIN_NOTE_S:
        return
    loaded = load_call(repo, call_id) if call_id else None
    if loaded is None:
        return
    if loaded.record.flow.answers.note_recording_url == event.recording_url:
        return  # a retried callback
    flow = ivr.with_recording(loaded.record.flow, event.recording_url)
    save_call(repo, loaded.record.model_copy(update={"flow": flow}))
    _invoke_async(
        config.settings().notes_fn,
        {
            "call_id": call_id,
            "recording_url": event.recording_url,
            "recording_id": event.recording_id,
        },
    )


def _inbound(repo: Repository, event: VobizEvent) -> str:
    """A missed call: reject it (free for the caller) and queue a call-back."""
    phone = normalise_phone(event.from_number)
    if phone is None:
        logger.info("missed call without caller id")
        return REJECT_XML
    now = config.now()
    # Only call-backs count (1 per 10 min, 5 a day): repeated rings in the cooldown are logged
    # but must not push the next call-back further away or use up the day's limit.
    since = now - CALLBACK_COOLDOWN
    recent = [m for m in repo.list_missed_calls(phone, since) if callback_queued(m)]
    repo.record_missed_call(phone, now, {"call_uuid": event.call_uuid, "callback": not recent})
    count("MissedCalls")
    if recent:
        logger.info("repeat missed call within cooldown", extra={"phone": mask_phone(phone)})
        return REJECT_XML
    job = {"kind": "callback", "phone": phone, "missed_at": now.isoformat()}
    _invoke_async(config.settings().outbound_fn, {**job, "delay_s": _delay_s()})
    when = "in a few seconds"
    activity(
        "missed_call",
        None,
        f"Missed call from {mask_phone(phone)}; calling back {when}",
        f"{mask_phone(phone)} से मिस्ड कॉल; वापस कॉल होगी",
    )
    return REJECT_XML


def normalise_phone(raw: str | None) -> str | None:
    """Indian caller id in E.164 (+91XXXXXXXXXX), or None when withheld or malformed."""
    digits = _DIGITS_ONLY.sub("", raw or "")
    if len(digits) == 10:
        digits = "91" + digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "91" + digits[1:]
    if len(digits) != 12 or not digits.startswith("91") or digits[2] == "0":
        return None  # an Indian national number never starts with 0 (e.g. "0000000000")
    return "+" + digits


def _delay_s() -> int:
    return config.settings().callback_delay_s


def _invoke_async(function_name: str | None, payload: dict[str, Any]) -> None:
    if not function_name:
        logger.warning("async target not configured", extra={"kind": payload.get("kind")})
        return
    config.client("lambda").invoke(
        FunctionName=function_name,
        InvocationType="Event",
        Payload=json.dumps(payload).encode(),
    )


def _status(repo: Repository, call_id: str, event: VobizEvent) -> None:
    """Hangup callback: finish the call with whatever was answered (none: unreachable)."""
    if not event.is_hangup:
        return
    loaded = load_call(repo, call_id) if call_id else None
    if loaded is not None and not loaded.record.finished:
        logger.info("call ended", extra={"call_id": call_id, "status": event.call_status})
        finish_call(repo, loaded, CapturedVia.DTMF)


def _render(actions: list[Action], record: CallRecord) -> str:
    language = record.flow.language
    actions = speech.with_dynamic_audio(actions, language)
    base = _base_url()
    digits = urlencode({"call_id": record.call_id, "turn": record.flow.turn})
    recording = urlencode({"call_id": record.call_id})
    return render_xml(
        actions,
        f"{base}/digits?{digits}",
        audio_base_for(config.settings().audio_base_url, language),
        recording_url=f"{base}/recording?{recording}",
        catalog=catalog_for(language),
    )


def _base_url() -> str:
    """``https://{host}{stage path}/ivr/vobiz/{token}``, taken from this request."""
    current = app.current_event
    path = current.raw_path.rsplit("/", 1)[0]
    return f"https://{current.request_context.domain_name}{path}"


def _turn() -> int:
    raw = app.current_event.get_query_string_value("turn") or ""
    return int(raw) if raw.isdigit() else -1


def _trusted(token: str) -> bool:
    expected = config.secrets.get(config.IVR_TOKEN_PARAM, required=False)
    if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
        logger.warning("ivr webhook with a wrong path token")
        return False
    cfg = config.settings()
    if cfg.ivr_allowed_cidrs and not _ip_allowed(cfg.ivr_allowed_cidrs):
        logger.warning("ivr webhook from an address outside the allowlist")
        return False
    if cfg.verify_vobiz_signature:
        return _signature_ok()
    return True


def _ip_allowed(cidrs: tuple[str, ...]) -> bool:
    try:
        source = ipaddress.ip_address(app.current_event.request_context.http.source_ip)
    except ValueError:
        return False
    return any(source in ipaddress.ip_network(cidr, strict=False) for cidr in cidrs)


def _signature_ok() -> bool:
    current = app.current_event
    url = f"https://{current.request_context.domain_name}{current.raw_path}"
    auth_token = config.secrets.get(config.VOBIZ_AUTH_TOKEN_PARAM)
    headers = {key: str(value) for key, value in (current.headers or {}).items()}
    valid = validate_signature(url, headers, str(auth_token))
    if not valid:
        logger.warning("ivr webhook with a bad Vobiz signature")
    return valid


def _xml(body: str) -> Response:
    return Response(200, CONTENT_TYPE, body)
