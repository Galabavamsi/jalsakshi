"""Vobiz webhooks: ``POST /ivr/vobiz/{token}/{answer|digits|recording|status}`` (public route).

Checks, in order: the secret path token (SSM ``ivr_path_token``), the optional source-IP
allowlist, and the optional Vobiz signature. Then the IVR engine runs one turn and the reply is
VobizXML. Our own ``call_id`` travels in each URL's query, and ``turn`` in the digits URL, so a
duplicate or stale webhook replays the current prompt instead of applying an input twice.

A call ends on the flow's last turn or on the hangup callback, whichever comes first; both
paths write the CheckIn once and resume the waiting workflow task.
"""

from __future__ import annotations

import hmac
import ipaddress
from typing import Any, Final
from urllib.parse import urlencode

from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response

from jalsakshi.core.models import CapturedVia
from jalsakshi.handlers import config
from jalsakshi.handlers.calls import CallRecord, LoadedCall, finish_call, load_call, save_call
from jalsakshi.handlers.common import entrypoint, logger
from jalsakshi.store import Repository
from jalsakshi.voice import flow as ivr
from jalsakshi.voice.actions import Action
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

MIN_NOTE_S: Final = 1
HANGUP_XML: Final = f"{XML_DECLARATION}<Response><Hangup /></Response>"

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
    flow, actions = ivr.start(record.flow)
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
        finish_call(repo, LoadedCall(record, loaded.task_token), CapturedVia.DTMF)
    return _render(actions, record)


def _recording(repo: Repository, call_id: str, event: VobizEvent) -> None:
    """Keep the note's recording URL (very short recordings are a skipped note)."""
    if not event.recording_url or (event.recording_duration_s or 0) < MIN_NOTE_S:
        return
    loaded = load_call(repo, call_id) if call_id else None
    if loaded is None:
        return
    flow = ivr.with_recording(loaded.record.flow, event.recording_url)
    save_call(repo, loaded.record.model_copy(update={"flow": flow}))


def _status(repo: Repository, call_id: str, event: VobizEvent) -> None:
    """Hangup callback: finish the call with whatever was answered (none: unreachable)."""
    if not event.is_hangup:
        return
    loaded = load_call(repo, call_id) if call_id else None
    if loaded is not None and not loaded.record.finished:
        logger.info("call ended", extra={"call_id": call_id, "status": event.call_status})
        finish_call(repo, loaded, CapturedVia.DTMF)


def _render(actions: list[Action], record: CallRecord) -> str:
    base = _base_url()
    digits = urlencode({"call_id": record.call_id, "turn": record.flow.turn})
    recording = urlencode({"call_id": record.call_id})
    return render_xml(
        actions,
        f"{base}/digits?{digits}",
        config.settings().audio_base_url,
        recording_url=f"{base}/recording?{recording}",
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
