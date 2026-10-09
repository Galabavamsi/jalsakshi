"""Runtime speech for the handlers: Sarvam TTS for text only known at call time, and the
Vobiz credentials used to fetch recordings (ARCHITECTURE.md §15.6, §15.12).

Both are optional: without a prompts bucket or a Sarvam key the IVR still works with its
pre-rendered clips, and a prompt that cannot be rendered is played through the adapter's
fallback instead of failing the call.
"""

from __future__ import annotations

from collections.abc import Sequence

from jalsakshi.handlers import config
from jalsakshi.handlers.common import logger
from jalsakshi.voice.actions import Action
from jalsakshi.voice.adapters.vobiz import VobizAuth
from jalsakshi.voice.catalog import CALL_LANGUAGES, catalog_for, sarvam_language
from jalsakshi.voice.tts import RuntimeTts, fill_dynamic_audio

_by_language: dict[str, RuntimeTts] = {}


def runtime_tts(language: str | None = None) -> RuntimeTts | None:
    """The stage's TTS renderer for a call language, or None when it cannot be configured."""
    code = sarvam_language(language)
    if code in _by_language:
        return _by_language[code]
    cfg = config.settings()
    key = config.secrets.get(config.SARVAM_API_KEY_PARAM, required=False)
    if not (cfg.prompts_bucket and cfg.audio_base_url and key):
        logger.warning("runtime TTS is not configured")
        return None
    _by_language[code] = RuntimeTts(
        api_key=key,
        bucket=cfg.prompts_bucket,
        s3=config.client("s3"),
        http=config.http_client(),
        audio_base_url=cfg.audio_base_url,
        language=code,
    )
    return _by_language[code]


def use_tts(instance: RuntimeTts | None) -> None:
    """Install a renderer for every language (tests); None forgets them all."""
    _by_language.clear()
    if instance is not None:
        for _, code in CALL_LANGUAGES.values():
            _by_language[code] = instance


def with_dynamic_audio(actions: Sequence[Action], language: str | None = None) -> list[Action]:
    """Fill audio URLs for prompts that have no pre-rendered clip (best effort)."""
    try:
        return fill_dynamic_audio(actions, runtime_tts(language), catalog_for(language))
    except Exception as exc:  # never break a live call over audio
        logger.warning("dynamic audio failed", extra={"error": str(exc)})
        return list(actions)


def vobiz_auth() -> VobizAuth:
    return VobizAuth(
        auth_id=str(config.secrets.get(config.VOBIZ_AUTH_ID_PARAM)),
        auth_token=str(config.secrets.get(config.VOBIZ_AUTH_TOKEN_PARAM)),
    )
