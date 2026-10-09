"""Sarvam speech-to-text for residents' voice notes (docs/ARCHITECTURE.md section 15.6).

One REST call per note (the REST endpoint takes audio under 30 s; notes are capped at 25 s).
Keyterms bias recognition toward the water words people actually say on these calls; they do not
guarantee a term appears. A failed or empty transcription raises ``SttError`` so the caller can
store the note as "not transcribed" instead of guessing.

Sarvam speech-to-text REST API (read 2026-10-09):
https://docs.sarvam.ai/api-reference-docs/speech-to-text/transcribe
POST https://api.sarvam.ai/speech-to-text, header ``api-subscription-key``, multipart form
``file``, ``model`` (``saaras:v4`` default), ``language_code`` and ``keyterms`` (a JSON-encoded
array, ``saaras:v4`` only, at most 50 terms of at most 64 characters each). The response is
``{request_id, transcript, language_code}``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Any, Final

import httpx
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

SARVAM_STT_URL: Final = "https://api.sarvam.ai/speech-to-text"
DEFAULT_MODEL: Final = "saaras:v4"
DEFAULT_LANGUAGE: Final = "hi-IN"
DEFAULT_TIMEOUT_S: Final = 30.0
MAX_KEYTERMS: Final = 50
MAX_KEYTERM_CHARS: Final = 64
KEYTERM_MODEL_PREFIX: Final = "saaras:v4"

DEFAULT_KEYTERMS: Final[tuple[str, ...]] = (
    "नल",
    "पानी",
    "टंकी",
    "पाइप",
    "मोटर",
    "हैंडपंप",
    "बोरवेल",
    "टैंकर",
    "नल जल मित्र",
    "सरपंच",
    "लीकेज",
    "गंदा पानी",
    "कुटेलाभाटा",
    "खपरी",
)
"""Hindi and Chhattisgarhi water words (Devanagari), plus the two pilot village names."""

CONTENT_TYPES: Final[dict[str, str]] = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "bin": "application/octet-stream",
}
"""MIME type for each ``sniff_audio_format`` result."""


class SttError(RuntimeError):
    """Speech could not be transcribed (HTTP failure, unreadable reply or empty transcript)."""


class Transcript(BaseModel):
    """What Sarvam heard in one voice note."""

    model_config = ConfigDict(frozen=True)

    text: str
    language_code: str | None = None
    request_id: str | None = None
    model: str


def sniff_audio_format(data: bytes) -> str:
    """Container format from the first bytes: ``wav``, ``mp3``, ``ogg`` or ``bin`` (unknown).

    Recording URLs and file names can lie about the extension, so the bytes decide. An MPEG frame
    needs the 11-bit sync word plus a valid version and a non-zero layer, which keeps AAC (ADTS,
    layer 0) out.
    """
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:3] == b"ID3":
        return "mp3"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        version_reserved = (data[1] & 0x18) == 0x08
        layer_reserved = (data[1] & 0x06) == 0
        if not version_reserved and not layer_reserved:
            return "mp3"
    if data[:4] == b"OggS":
        return "ogg"
    return "bin"


def normalize_keyterms(terms: Sequence[str]) -> list[str]:
    """Terms Sarvam accepts: trimmed, non-empty, unique, at most 64 characters, at most 50.

    Longer terms are dropped and extra terms cut, each with a warning, so a long list of village
    names never blocks a transcription.
    """
    cleaned: list[str] = []
    for raw in terms:
        term = " ".join(str(raw).split())
        if not term or term in cleaned:
            continue
        if len(term) > MAX_KEYTERM_CHARS:
            logger.warning("dropping STT keyterm longer than %d characters", MAX_KEYTERM_CHARS)
            continue
        cleaned.append(term)
    if len(cleaned) > MAX_KEYTERMS:
        logger.warning("keeping the first %d of %d STT keyterms", MAX_KEYTERMS, len(cleaned))
        cleaned = cleaned[:MAX_KEYTERMS]
    return cleaned


def transcribe(
    audio: bytes,
    filename: str,
    *,
    api_key: str,
    http: httpx.Client,
    language: str = DEFAULT_LANGUAGE,
    keyterms: Sequence[str] = DEFAULT_KEYTERMS,
    model: str = DEFAULT_MODEL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> Transcript:
    """Transcribe one recording with Sarvam; raises ``SttError`` on failure or silence."""
    if not audio:
        raise SttError("no audio to transcribe")
    fmt = sniff_audio_format(audio)
    form: dict[str, str] = {"model": model, "language_code": language}
    if model.startswith(KEYTERM_MODEL_PREFIX):
        terms = normalize_keyterms(keyterms)
        if terms:
            form["keyterms"] = json.dumps(terms, ensure_ascii=False)
    files = {"file": (_upload_name(filename, fmt), audio, CONTENT_TYPES[fmt])}
    headers = {"api-subscription-key": api_key}
    try:
        response = http.post(
            SARVAM_STT_URL, data=form, files=files, headers=headers, timeout=timeout_s
        )
    except httpx.HTTPError as exc:
        raise SttError(f"Sarvam STT request failed: {type(exc).__name__}") from exc
    if response.status_code != httpx.codes.OK:
        raise SttError(f"Sarvam STT failed: HTTP {response.status_code} {_error(response)}")
    body = _json(response)
    text = " ".join(str(body.get("transcript") or "").split())
    if not text:
        raise SttError("Sarvam STT returned an empty transcript")
    return Transcript(
        text=text,
        language_code=_optional_str(body.get("language_code")),
        request_id=_optional_str(body.get("request_id")),
        model=model,
    )


def _upload_name(filename: str, fmt: str) -> str:
    """The file's base name, with the sniffed extension when the format is known."""
    path = PurePosixPath(filename.replace("\\", "/"))
    stem = path.stem or "note"
    if fmt == "bin":
        return path.name or stem
    return f"{stem}.{fmt}"


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise SttError("Sarvam STT returned a body that is not JSON") from exc
    if not isinstance(body, dict):
        raise SttError("Sarvam STT returned an unexpected body")
    return body


def _error(response: httpx.Response) -> str:
    """Sarvam's error message (``{"error": {"message": ...}}``), shortened for logs."""
    try:
        body = response.json()
    except ValueError:
        return " ".join(response.text.split())[:200]
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message", "") if isinstance(error, dict) else ""
    return " ".join(str(message).split())[:200]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
