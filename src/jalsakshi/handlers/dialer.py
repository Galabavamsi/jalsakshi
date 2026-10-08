"""Outbound PSTN calls through Vobiz: the request is built by ``voice.adapters.vobiz``, sent here.

Safety (CLAUDE.md): callers have already passed the Cedar ``PlaceCall`` check; on top of that,
only numbers on the stage's SSM allowlist of consenting test phones are dialled, and toll-free
or helpline numbers (PHED 1800-233-0008 and the like) never are.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import urlencode

from jalsakshi.handlers import config
from jalsakshi.handlers.calls import CallRecord
from jalsakshi.handlers.common import count, logger
from jalsakshi.voice.adapters.vobiz import VobizAuth, place_call_request

# Toll-free and shared-cost lines (where state helplines live) and emergency short codes.
BLOCKED_PREFIXES: Final = ("+911800", "+911860", "+91100", "+91101", "+91102", "+91108")


class DialError(RuntimeError):
    """The call could not be placed (refused by a safety check, or Vobiz failed)."""


def check_dialable(phone: str) -> None:
    """Raise DialError unless ``phone`` is an allowlisted, non-helpline number."""
    if phone.startswith(BLOCKED_PREFIXES):
        raise DialError("helpline and toll-free numbers are never dialled")
    if phone not in config.allowed_numbers():
        raise DialError("number is not on this stage's allowlist of consenting test phones")


def ivr_base_url() -> str:
    """Public base URL of this stage's Vobiz webhooks (contains the secret path token)."""
    api_url = config.settings().api_url
    if not api_url:
        raise config.ConfigError("JALSAKSHI_API_URL is not set")
    token = config.secrets.get(config.IVR_TOKEN_PARAM)
    return f"{api_url}/ivr/vobiz/{token}"


def dial(record: CallRecord, phone: str) -> str:
    """Ask Vobiz to call ``phone`` and run our IVR on answer; returns Vobiz's request uuid."""
    check_dialable(phone)
    base = ivr_base_url()
    query = urlencode({"call_id": record.call_id})
    auth = VobizAuth(
        auth_id=str(config.secrets.get(config.VOBIZ_AUTH_ID_PARAM)),
        auth_token=str(config.secrets.get(config.VOBIZ_AUTH_TOKEN_PARAM)),
    )
    method, url, headers, body = place_call_request(
        to=phone,
        from_=str(config.secrets.get(config.VOBIZ_DID_PARAM)),
        answer_url=f"{base}/answer?{query}",
        hangup_url=f"{base}/status?{query}",
        auth=auth,
    )
    response = config.http_client().request(method, url, headers=headers, json=body)
    if response.status_code >= 300:
        raise DialError(f"Vobiz refused the call with HTTP {response.status_code}")
    request_uuid = _request_uuid(response.json() if response.content else {})
    count("CallsPlaced")
    logger.info("call placed", extra={"call_id": record.call_id, "request_uuid": request_uuid})
    return request_uuid


def _request_uuid(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("request_uuid", "requestUuid", "RequestUUID"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, list) and value:
            return str(value[0])
    return ""
