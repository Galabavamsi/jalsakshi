"""Vobiz adapter: engine actions to VobizXML, Vobiz webhooks to ``VobizEvent``, call requests.

VobizXML is a near drop-in for PlivoXML. The keypad verb is ``<Gather>`` (Plivo's ``<GetDigits>``)
with ``executionTimeout`` (5-60 s) instead of ``timeout``. Webhooks are form-encoded with
Plivo-style names (``CallUUID``, ``Digits``, ``CallStatus``, ``HangupCause``, ...).

How the XML is shaped:

- Prompts use ``<Play>`` with pre-rendered 8 kHz MP3 (Sarvam Bulbul). Only a prompt with no clip
  (for example a household count above 9) falls back to ``<Speak voice="WOMAN" language="hi-IN">``.
  Vobiz lists ``hi-IN`` (WOMAN) for its Speak API; the XML Speak page does not list it, so the
  fallback is best effort.
- Every ``<Gather>`` and ``<Record>`` is followed by ``<Redirect>`` to the action URL. Vobiz posts
  to the Gather action with empty ``Digits`` on a timeout; if it ever does not, the Redirect does,
  so the handler always gets the next turn. Elements after a Redirect never run, so an input
  action (or Hangup) must be the last action.
- ``<Record redirect="false">`` sends its events to ``recording_url`` (the ``RecordStop`` callback
  carries the file URL); when recording ends the Redirect continues the flow.

Signature check: Vobiz signs callbacks only when credentials are configured on the callback URL,
so the secret path token plus the IP allowlist stay the first line of defence.

Docs relied on (read 2026-10-08):
- https://www.vobiz.ai/docs/llms.txt
- https://vobiz.ai/docs/xml/overview/how-it-works
- https://vobiz.ai/docs/xml/gather , https://vobiz.ai/docs/xml/play , https://vobiz.ai/docs/xml/speak
- https://vobiz.ai/docs/xml/record , https://vobiz.ai/docs/xml/redirect , https://vobiz.ai/docs/xml/hangup
- https://vobiz.ai/docs/xml/request (with /call-status and /event)
- https://vobiz.ai/docs/call/make-call
- https://vobiz.ai/docs/call/speak-text/speak-text (TTS languages, including hi-IN)
- https://vobiz.ai/docs/concepts/callbacks , https://vobiz.ai/docs/concepts/validating-callbacks
- https://vobiz.ai/docs/compare/plivo/call-control-xml
- https://vobiz.ai/docs/api-reference/authentication
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict

from jalsakshi.voice.actions import Action, GetDigits, Hangup, Play, Record
from jalsakshi.voice.catalog import PromptCatalog, audio_url, default_catalog

API_BASE = "https://api.vobiz.ai/api/v1"
CONTENT_TYPE = "application/xml"
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>\n'
EMPTY_RESPONSE = f"{XML_DECLARATION}<Response />"
SPEAK_VOICE = "WOMAN"
SPEAK_LANGUAGE = "hi-IN"
GATHER_TIMEOUT_RANGE = (5, 60)
RECORD_SILENCE_TIMEOUT_S = 5
UNANSWERED_STATUSES = frozenset({"no-answer", "busy", "failed", "timeout", "cancel", "canceled"})

_E164 = re.compile(r"^\+\d{10,15}$")


@dataclass(frozen=True, slots=True)
class VobizAuth:
    """Account credentials; the token signs webhooks too. Never log it."""

    auth_id: str
    auth_token: str = field(repr=False)


class VobizEvent(BaseModel):
    """The fields JalSakshi uses from any Vobiz webhook (answer, gather, record, hangup)."""

    model_config = ConfigDict(frozen=True)

    call_uuid: str
    request_uuid: str | None = None
    event: str | None = None
    call_status: str | None = None
    digits: str | None = None
    input_type: str | None = None
    from_number: str | None = None
    to_number: str | None = None
    direction: str | None = None
    hangup_cause: str | None = None
    duration_s: int | None = None
    recording_id: str | None = None
    recording_url: str | None = None
    recording_duration_s: int | None = None
    recording_end_reason: str | None = None

    @property
    def is_timeout(self) -> bool:
        """No key arrived (Gather timeout, or the Redirect that follows an input verb)."""
        return self.digits is None

    @property
    def is_recording(self) -> bool:
        """A Record start/stop event rather than a call-flow turn."""
        return self.recording_id is not None or self.event in {"Record", "RecordStop"}

    @property
    def is_hangup(self) -> bool:
        """The call has ended."""
        return self.event == "Hangup" or self.call_status in UNANSWERED_STATUSES | {"completed"}

    @property
    def unanswered(self) -> bool:
        """The call ended without being picked up (busy, no answer, failed, ...)."""
        return self.call_status in UNANSWERED_STATUSES


def render_xml(
    actions: Sequence[Action],
    action_url: str,
    audio_base_url: str | None,
    *,
    recording_url: str | None = None,
    catalog: PromptCatalog | None = None,
) -> str:
    """VobizXML ``<Response>`` for the actions; input and recording events go to the given URLs."""
    _check_order(actions)
    cat = catalog or default_catalog()
    root = ET.Element("Response")
    for action in actions:
        match action:
            case Play():
                root.append(_prompt(action, audio_base_url, cat))
            case GetDigits():
                root.append(_gather(action, action_url, audio_base_url, cat))
                root.append(_redirect(action_url))
            case Record():
                root.append(_record(action, recording_url))
                root.append(_redirect(action_url))
            case Hangup():
                ET.SubElement(root, "Hangup")
    return XML_DECLARATION + ET.tostring(root, encoding="unicode")


def parse_form(body: str | bytes | None, *, base64_encoded: bool = False) -> dict[str, str]:
    """Decode an ``application/x-www-form-urlencoded`` body (API Gateway may base64 it)."""
    if not body:
        return {}
    raw = base64.b64decode(body) if base64_encoded else body
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    return {key: values[0] for key, values in parse_qs(text, keep_blank_values=True).items()}


def parse_webhook(form: Mapping[str, str | Sequence[str]]) -> VobizEvent:
    """Parse any Vobiz voice webhook. Raises ValueError without ``CallUUID``."""
    values = {key: _single(value) for key, value in form.items()}
    call_uuid = _pick(values, "CallUUID", "call_uuid")
    if not call_uuid:
        raise ValueError("Vobiz webhook has no CallUUID")
    return VobizEvent(
        call_uuid=call_uuid,
        request_uuid=_pick(values, "RequestUUID", "ALegRequestUUID"),
        event=_pick(values, "Event"),
        call_status=_pick(values, "CallStatus", "Status"),
        digits=_pick(values, "Digits"),
        input_type=_pick(values, "InputType"),
        from_number=_pick(values, "From"),
        to_number=_pick(values, "To"),
        direction=_pick(values, "Direction"),
        hangup_cause=_pick(values, "HangupCause", "HangupCauseName"),
        duration_s=_int(_pick(values, "Duration")),
        recording_id=_pick(values, "RecordingID"),
        recording_url=_pick(values, "RecordFile", "RecordUrl", "RecordingUrl"),
        recording_duration_s=_int(_pick(values, "RecordingDuration")),
        recording_end_reason=_pick(values, "RecordingEndReason"),
    )


def place_call_request(
    to: str,
    from_: str,
    answer_url: str,
    hangup_url: str,
    auth: VobizAuth,
    *,
    ring_url: str | None = None,
    time_limit_s: int = 300,
    ring_timeout_s: int = 45,
) -> tuple[str, str, dict[str, str], dict[str, Any]]:
    """Build (method, url, headers, json) for Vobiz "Make an Outbound Call"; never sends it.

    Exactly one E.164 destination: Vobiz fans out on ``<``, and consent is per household.
    """
    for label, number in (("to", to), ("from_", from_)):
        if not _E164.match(number):
            raise ValueError(f"{label} must be one E.164 number like +919876543210")
    url = f"{API_BASE}/Account/{auth.auth_id}/Call/"
    headers = {
        "X-Auth-ID": auth.auth_id,
        "X-Auth-Token": auth.auth_token,
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "from": from_,
        "to": to,
        "answer_url": answer_url,
        "answer_method": "POST",
        "hangup_url": hangup_url,
        "hangup_method": "POST",
        "time_limit": time_limit_s,
        "ring_timeout": ring_timeout_s,
    }
    if ring_url:
        body |= {"ring_url": ring_url, "ring_method": "POST"}
    return "POST", url, headers, body


def compute_signature(url: str, nonce: str, auth_token: str, version: str = "v3") -> str:
    """Vobiz callback signature: base64(HMAC-SHA256(token, base_url [+ "."] + nonce))."""
    if version not in {"v2", "v3"}:
        raise ValueError(f"unsupported signature version: {version}")
    separator = "." if version == "v3" else ""
    message = f"{_base_url(url)}{separator}{nonce}".encode()
    digest = hmac.new(auth_token.encode(), message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def validate_signature(url: str, headers: Mapping[str, str], auth_token: str) -> bool:
    """True if a V3 or V2 signature header matches; False (fail closed) if none is present."""
    lowered = {key.lower(): value for key, value in headers.items()}
    for version in ("v3", "v2"):
        signature = lowered.get(f"x-vobiz-signature-{version}")
        nonce = lowered.get(f"x-vobiz-signature-{version}-nonce")
        if not signature or not nonce:
            continue
        expected = compute_signature(url, nonce, auth_token, version)
        if hmac.compare_digest(signature.encode(), expected.encode()):
            return True
    return False


def _check_order(actions: Sequence[Action]) -> None:
    if not actions:
        raise ValueError("no actions to render")
    for action in actions[:-1]:
        if isinstance(action, GetDigits | Record | Hangup):
            raise ValueError(f"{action.type} must be the last action")


def _prompt(play: Play, audio_base_url: str | None, cat: PromptCatalog) -> ET.Element:
    url = play.audio_url
    if url is None and audio_base_url and cat.has_audio(play.prompt_key):
        url = audio_url(play.prompt_key, audio_base_url)
    if url:
        element = ET.Element("Play")
        element.text = url
        return element
    element = ET.Element("Speak", {"voice": SPEAK_VOICE, "language": SPEAK_LANGUAGE})
    element.text = play.text_hi
    return element


def _gather(
    action: GetDigits, action_url: str, audio_base_url: str | None, cat: PromptCatalog
) -> ET.Element:
    low, high = GATHER_TIMEOUT_RANGE
    gather = ET.Element(
        "Gather",
        {
            "action": action_url,
            "method": "POST",
            "inputType": "dtmf",
            "numDigits": str(action.num_digits),
            "executionTimeout": str(min(max(action.timeout_s, low), high)),
            "finishOnKey": "",
            "redirect": "true",
        },
    )
    gather.extend(_prompt(play, audio_base_url, cat) for play in action.prompts)
    return gather


def _record(action: Record, recording_url: str | None) -> ET.Element:
    if not recording_url:
        raise ValueError("render_xml needs recording_url to render a Record action")
    return ET.Element(
        "Record",
        {
            "action": recording_url,
            "method": "POST",
            "redirect": "false",
            "callbackUrl": recording_url,
            "callbackMethod": "POST",
            "fileFormat": "mp3",
            "maxLength": str(action.max_s),
            "timeout": str(RECORD_SILENCE_TIMEOUT_S),
            "finishOnKey": "#",
            "playBeep": "true",
        },
    )


def _redirect(url: str) -> ET.Element:
    element = ET.Element("Redirect", {"method": "POST"})
    element.text = url
    return element


def _base_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _single(value: str | Sequence[str]) -> str:
    if isinstance(value, str):
        return value
    return value[0] if value else ""


def _pick(values: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = values.get(name, "").strip()
        if value:
            return value
    return None


def _int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, OverflowError):
        return None
