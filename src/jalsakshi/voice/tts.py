"""Runtime Sarvam Bulbul text-to-speech with an S3 cache (docs/ARCHITECTURE.md section 15.12).

A ``Play`` with no pre-rendered clip (a household count above 9, a water point name, an approved
announcement) is rendered once at request time and cached in the prompt bucket. Vobiz ``Speak``
has no Hindi voice, so Hindi text is never sent to it when this works.

Audio matches ``prompts/render.py`` exactly: ``bulbul:v3``, speaker ``ritu``, pace 0.9, 8 kHz
MP3, ``hi-IN``. Vobiz ``<Play>`` accepts MP3, and every pre-rendered clip is MP3 too.

Where a clip lives. The prompt bucket sits behind CloudFront with the bucket root as the origin,
and ``JALSAKSHI_AUDIO_BASE_URL`` is ``https://<cdn>/prompts/hi`` (``AUDIO_PREFIX`` in
``infra/jalsakshi_infra/data_stack.py``). So a dynamic clip ``dyn/<hash>.mp3`` is stored at
``s3://<bucket>/prompts/hi/dyn/<hash>.mp3`` and served at ``{audio_base_url}/dyn/<hash>.mp3``.
The name is a hash of the voice and the text, so a cached object never changes and is served
with an immutable cache header.

Long text is split on sentence ends into chunks of at most 450 characters. Each chunk is its own
clip, played back to back (MP3 files are not concatenated, because an encoder header in the
first file can make players stop at its length).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from collections.abc import Sequence
from typing import Any, Final

import httpx
from botocore.exceptions import BotoCoreError, ClientError

from jalsakshi.voice.actions import Action, GetDigits, Play
from jalsakshi.voice.catalog import PromptCatalog, default_catalog
from jalsakshi.voice.stt import sniff_audio_format

logger = logging.getLogger(__name__)

SARVAM_TTS_URL: Final = "https://api.sarvam.ai/text-to-speech"
DEFAULT_MODEL: Final = "bulbul:v3"
DEFAULT_SPEAKER: Final = "ritu"
DEFAULT_PACE: Final = 0.9
DEFAULT_LANGUAGE: Final = "hi-IN"
SAMPLE_RATE_HZ: Final = 8000
AUDIO_CODEC: Final = "mp3"
AUDIO_EXTENSION: Final = "mp3"
CONTENT_TYPE: Final = "audio/mpeg"
CACHE_CONTROL: Final = "public, max-age=31536000, immutable"
DEFAULT_KEY_PREFIX: Final = "prompts/hi"
"""S3 prefix that ``audio_base_url`` points at (``AUDIO_PREFIX`` in the data stack)."""
DYN_DIR: Final = "dyn"
MAX_CHUNK_CHARS: Final = 450
DEFAULT_TIMEOUT_S: Final = 8.0

_SENTENCE_END = re.compile(r"(?<=[.?!।॥]) ")
_MISSING_CODES = frozenset({"404", "NoSuchKey", "NotFound"})


class TtsError(RuntimeError):
    """Text could not be turned into a served clip (Sarvam or S3 failed, or no text)."""


def dyn_key(text: str, voice: str = DEFAULT_SPEAKER) -> str:
    """Clip name relative to ``audio_base_url``: ``dyn/<32 hex of sha256(voice|text)>.mp3``."""
    digest = hashlib.sha256(f"{voice}|{text}".encode()).hexdigest()[:32]
    return f"{DYN_DIR}/{digest}.{AUDIO_EXTENSION}"


def split_text(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Whitespace-normalised text in chunks of at most ``limit`` characters.

    Chunks break at a space after ``.``, ``?``, ``!`` or ``।`` where possible, then between
    words, and only cut a word that is longer than ``limit`` on its own. Joining the chunks with
    single spaces gives the normalised text back (unless a word had to be cut). Empty text gives
    an empty list.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    clean = " ".join(text.split())
    if not clean:
        return []
    if len(clean) <= limit:
        return [clean]
    pieces: list[str] = []
    for sentence in _SENTENCE_END.split(clean):
        pieces.extend([sentence] if len(sentence) <= limit else _split_words(sentence, limit))
    return _pack(pieces, limit)


def _split_words(sentence: str, limit: int) -> list[str]:
    words: list[str] = []
    for word in sentence.split(" "):
        words.extend(word[i : i + limit] for i in range(0, len(word), limit))
    return _pack(words, limit)


def _pack(pieces: Sequence[str], limit: int) -> list[str]:
    """Join pieces with spaces, greedily, without letting a chunk pass ``limit``."""
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}" if current else piece
        if len(candidate) <= limit:
            current = candidate
            continue
        chunks.append(current)
        current = piece
    if current:
        chunks.append(current)
    return chunks


class RuntimeTts:
    """Renders text with Sarvam once and serves it from the prompt bucket via CloudFront.

    ``s3`` is a boto3 S3 client (or a fake with ``head_object`` and ``put_object``). The Lambda
    needs ``s3:GetObject`` and ``s3:PutObject`` on ``{key_prefix}/dyn/*``, and ``s3:ListBucket``
    so that a missing clip answers 404 rather than 403 (both are treated as "not cached").
    """

    def __init__(
        self,
        api_key: str,
        bucket: str,
        s3: Any,
        http: httpx.Client,
        audio_base_url: str,
        speaker: str = DEFAULT_SPEAKER,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        *,
        key_prefix: str = DEFAULT_KEY_PREFIX,
        model: str = DEFAULT_MODEL,
        pace: float = DEFAULT_PACE,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        if not audio_base_url:
            raise ValueError("audio_base_url is required")
        self._api_key = api_key
        self.bucket = bucket
        self._s3 = s3
        self._http = http
        self.audio_base_url = audio_base_url.rstrip("/")
        self.speaker = speaker
        self.timeout_s = timeout_s
        self.key_prefix = key_prefix.strip("/")
        self.model = model
        self.pace = pace
        self.language = language
        self._cached: set[str] = set()

    def __repr__(self) -> str:
        return f"RuntimeTts(bucket={self.bucket!r}, prefix={self.key_prefix!r})"

    def url_for(self, key: str) -> str:
        """Public URL of a clip key such as ``dyn/<hash>.mp3``."""
        return f"{self.audio_base_url}/{key}"

    def object_key(self, key: str) -> str:
        """S3 object key of a clip key: ``{key_prefix}/dyn/<hash>.mp3``."""
        return f"{self.key_prefix}/{key}" if self.key_prefix else key

    def ensure(self, text: str) -> str:
        """URL of the clip for one chunk of text, rendering and caching it if needed.

        Raises ``TtsError`` for empty text, text longer than one chunk (use ``ensure_all``), or a
        Sarvam or S3 failure.
        """
        chunks = split_text(text)
        if not chunks:
            raise TtsError("no text to speak")
        if len(chunks) > 1:
            raise TtsError(f"text is longer than {MAX_CHUNK_CHARS} characters; use ensure_all")
        return self._ensure_chunk(chunks[0])

    def ensure_all(self, text: str) -> list[str]:
        """URLs of the clips for ``split_text(text)``, in order (one URL for short text)."""
        chunks = split_text(text)
        if not chunks:
            raise TtsError("no text to speak")
        return [self._ensure_chunk(chunk) for chunk in chunks]

    def payload(self, text: str) -> dict[str, Any]:
        """JSON body for one Sarvam request (the same shape as ``prompts/render.py``)."""
        return {
            "text": text,
            "language_code": self.language,
            "model": self.model,
            "speaker": self.speaker,
            "pace": self.pace,
            "speech_sample_rate": SAMPLE_RATE_HZ,
            "output_audio_codec": AUDIO_CODEC,
        }

    def _ensure_chunk(self, chunk: str) -> str:
        key = dyn_key(chunk, self.speaker)
        object_key = self.object_key(key)
        if object_key in self._cached or self._exists(object_key):
            self._cached.add(object_key)
            return self.url_for(key)
        audio = self._synthesize(chunk)
        try:
            self._s3.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=audio,
                ContentType=CONTENT_TYPE,
                CacheControl=CACHE_CONTROL,
            )
        except (ClientError, BotoCoreError) as exc:
            raise TtsError(f"could not store clip {key}: {type(exc).__name__}") from exc
        self._cached.add(object_key)
        logger.info("rendered dynamic clip %s (%d chars, %d bytes)", key, len(chunk), len(audio))
        return self.url_for(key)

    def _exists(self, object_key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=object_key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in _MISSING_CODES:
                logger.warning("head_object %s failed (%s); rendering again", object_key, code)
            return False
        except BotoCoreError as exc:
            logger.warning("head_object %s failed (%s); rendering again", object_key, exc)
            return False
        return True

    def _synthesize(self, text: str) -> bytes:
        headers = {"api-subscription-key": self._api_key, "Content-Type": "application/json"}
        try:
            response = self._http.post(
                SARVAM_TTS_URL, json=self.payload(text), headers=headers, timeout=self.timeout_s
            )
        except httpx.HTTPError as exc:
            raise TtsError(f"Sarvam TTS request failed: {type(exc).__name__}") from exc
        if response.status_code != httpx.codes.OK:
            raise TtsError(f"Sarvam TTS failed: HTTP {response.status_code} {_error(response)}")
        return _decode_audio(response)


def fill_dynamic_audio(
    actions: Sequence[Action],
    tts: RuntimeTts | None,
    catalog: PromptCatalog | None = None,
) -> list[Action]:
    """Copy of ``actions`` where each Play without a clip gets runtime-TTS audio.

    A Play is filled when it has no ``audio_url`` and the catalog has no pre-rendered clip for
    its ``prompt_key``. Text longer than one chunk becomes several Plays, in order, in the same
    place (top level, or inside ``GetDigits.prompts``). With no ``tts``, or on ``TtsError``, the
    Play is left as it is (the adapter falls back) and a warning is logged.
    """
    cat = catalog or default_catalog()

    def needs_audio(play: Play) -> bool:
        return not play.audio_url and not cat.has_audio(play.prompt_key) and bool(play.text_hi)

    def expand(play: Play) -> list[Play]:
        if not needs_audio(play):
            return [play]
        if tts is None:
            logger.warning("no runtime TTS configured; %s has no audio", play.prompt_key)
            return [play]
        chunks = split_text(play.text_hi)
        if not chunks:
            return [play]
        try:
            urls = [tts.ensure(chunk) for chunk in chunks]
        except TtsError as exc:
            logger.warning("runtime TTS failed for %s: %s", play.prompt_key, exc)
            return [play]
        if len(chunks) == 1:
            return [play.model_copy(update={"audio_url": urls[0]})]
        return [
            play.model_copy(update={"text_hi": chunk, "audio_url": url})
            for chunk, url in zip(chunks, urls, strict=True)
        ]

    filled: list[Action] = []
    for action in actions:
        if isinstance(action, Play):
            filled.extend(expand(action))
        elif isinstance(action, GetDigits):
            prompts = [part for play in action.prompts for part in expand(play)]
            filled.append(action.model_copy(update={"prompts": prompts}))
        else:
            filled.append(action)
    return filled


def _decode_audio(response: httpx.Response) -> bytes:
    try:
        body = response.json()
        audios = body.get("audios") if isinstance(body, dict) else None
        audio = base64.b64decode("".join(audios or []), validate=True)
    except (ValueError, TypeError) as exc:
        raise TtsError("Sarvam TTS returned an unreadable body") from exc
    if not audio:
        raise TtsError("Sarvam TTS returned no audio")
    if sniff_audio_format(audio) != AUDIO_EXTENSION:
        raise TtsError("Sarvam TTS did not return MP3 audio")
    return audio


def _error(response: httpx.Response) -> str:
    """Sarvam's error message (``{"error": {"message": ...}}``), shortened for logs."""
    try:
        body = response.json()
    except ValueError:
        return " ".join(response.text.split())[:200]
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message", "") if isinstance(error, dict) else ""
    return " ".join(str(message).split())[:200]
