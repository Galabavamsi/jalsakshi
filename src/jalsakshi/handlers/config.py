"""Stage configuration, secrets and AWS clients for the Lambda handlers (ARCHITECTURE.md §6).

Plain settings come from environment variables that infra/ sets on every function. Secrets come
from SSM Parameter Store under ``/jalsakshi/{stage}/`` (decrypted, cached for a few minutes).
Every client names its region explicitly: ``$JALSAKSHI_REGION``, else ap-south-1, never
``AWS_REGION``. Tests swap clients and the clock with ``use_client`` and ``set_clock``.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import cache
from typing import Any, Final

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import ClientError

from jalsakshi.store import Repository

DEFAULT_REGION: Final = "ap-south-1"
DEFAULT_STAGE: Final = "dev"
SECRET_TTL_S: Final = 300.0
HTTP_TIMEOUT: Final = httpx.Timeout(10.0, connect=5.0)

# Names under /jalsakshi/{stage}/ in SSM Parameter Store.
IVR_TOKEN_PARAM: Final = "ivr_path_token"
VOBIZ_AUTH_ID_PARAM: Final = "vobiz_auth_id"
VOBIZ_AUTH_TOKEN_PARAM: Final = "vobiz_auth_token"
VOBIZ_DID_PARAM: Final = "vobiz_did"
ALLOWED_NUMBERS_PARAM: Final = "allowed_numbers"
SARVAM_API_KEY_PARAM: Final = "sarvam_api_key"

_BOTO_CONFIG: Final = Config(
    connect_timeout=3, read_timeout=10, retries={"max_attempts": 3, "mode": "standard"}
)


class ConfigError(RuntimeError):
    """A required setting or secret is missing."""


class VoiceProvider(StrEnum):
    """Who carries outbound calls: Vobiz PSTN, or the console's web-phone simulator."""

    VOBIZ = "vobiz"
    SIMULATOR = "simulator"


def _flag(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str | None) -> tuple[str, ...]:
    return tuple(part.strip() for part in (value or "").split(",") if part.strip())


def _optional(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name, "").strip()
    return value or None


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything a handler needs to know about its stage (no secrets)."""

    stage: str
    region: str
    table_name: str
    evidence_bucket: str | None
    audio_base_url: str | None
    api_url: str | None
    voice_provider: VoiceProvider
    checkin_sfn_arn: str | None
    ticket_sfn_arn: str | None
    brief_use_agent: bool
    verify_vobiz_signature: bool
    ivr_allowed_cidrs: tuple[str, ...]
    prompts_bucket: str | None = None
    outbound_fn: str | None = None
    notes_fn: str | None = None
    scheduler_group: str | None = None
    scheduler_role_arn: str | None = None
    outbound_fn_arn: str | None = None
    callback_delay_s: int = 15
    open_dialing: bool = False
    checkin_group: str | None = None
    checkin_role_arn: str | None = None
    user_pool_id: str | None = None

    @property
    def ssm_prefix(self) -> str:
        """Parameter Store path holding this stage's secrets."""
        return f"/jalsakshi/{self.stage}/"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Read settings from the environment (set by infra/ on each Lambda)."""
        env = os.environ if env is None else env
        provider = env.get("VOICE_PROVIDER", "").strip().lower() or VoiceProvider.SIMULATOR
        try:
            voice = VoiceProvider(provider)
        except ValueError as exc:
            raise ConfigError(
                f"VOICE_PROVIDER must be vobiz or simulator, got {provider!r}"
            ) from exc
        audio = _optional(env, "JALSAKSHI_AUDIO_BASE_URL")
        api = _optional(env, "JALSAKSHI_API_URL")
        return cls(
            stage=_optional(env, "JALSAKSHI_STAGE") or DEFAULT_STAGE,
            region=_optional(env, "JALSAKSHI_REGION") or DEFAULT_REGION,
            table_name=_optional(env, "JALSAKSHI_TABLE") or "",
            evidence_bucket=_optional(env, "JALSAKSHI_EVIDENCE_BUCKET"),
            audio_base_url=audio.rstrip("/") if audio else None,
            api_url=api.rstrip("/") if api else None,
            voice_provider=voice,
            checkin_sfn_arn=_optional(env, "JALSAKSHI_CHECKIN_SFN_ARN"),
            ticket_sfn_arn=_optional(env, "JALSAKSHI_TICKET_SFN_ARN"),
            brief_use_agent=_flag(env.get("JALSAKSHI_BRIEF_USE_AGENT"), True),
            verify_vobiz_signature=_flag(env.get("JALSAKSHI_VOBIZ_VERIFY_SIGNATURE"), False),
            ivr_allowed_cidrs=_csv(env.get("JALSAKSHI_IVR_ALLOWED_CIDRS")),
            prompts_bucket=_optional(env, "JALSAKSHI_PROMPTS_BUCKET"),
            outbound_fn=_optional(env, "JALSAKSHI_OUTBOUND_FN"),
            notes_fn=_optional(env, "JALSAKSHI_NOTES_FN"),
            scheduler_group=_optional(env, "JALSAKSHI_SCHEDULER_GROUP"),
            scheduler_role_arn=_optional(env, "JALSAKSHI_SCHEDULER_ROLE_ARN"),
            outbound_fn_arn=_optional(env, "JALSAKSHI_OUTBOUND_FN_ARN"),
            callback_delay_s=int(_optional(env, "JALSAKSHI_CALLBACK_DELAY_S") or 15),
            open_dialing=_flag(env.get("JALSAKSHI_OPEN_DIALING"), False),
            checkin_group=_optional(env, "JALSAKSHI_CHECKIN_GROUP"),
            checkin_role_arn=_optional(env, "JALSAKSHI_CHECKIN_ROLE_ARN"),
            user_pool_id=_optional(env, "JALSAKSHI_USER_POOL_ID"),
        )


@cache
def settings() -> Settings:
    """Settings for this process (read once)."""
    return Settings.from_env()


# --- clock ----------------------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


_clock: Callable[[], datetime] = _utcnow


def now() -> datetime:
    """Current time as an aware UTC datetime (replaceable in tests via ``set_clock``)."""
    return _clock()


def set_clock(clock: Callable[[], datetime]) -> None:
    """Replace the clock (tests and local replays)."""
    global _clock
    _clock = clock


# --- AWS clients ----------------------------------------------------------------------------------

_clients: dict[str, Any] = {}
_clients_lock = threading.Lock()


def client(service: str) -> Any:
    """A cached boto3 client for ``service`` in the configured region."""
    with _clients_lock:
        if service not in _clients:
            _clients[service] = boto3.client(
                service, region_name=settings().region, config=_BOTO_CONFIG
            )
        return _clients[service]


def use_client(service: str, instance: Any) -> None:
    """Install a client (a moto client or a fake) for ``service``."""
    with _clients_lock:
        _clients[service] = instance


_http: httpx.Client | None = None


def http_client() -> httpx.Client:
    """Shared outbound HTTP client (Vobiz API) with bounded timeouts."""
    global _http
    if _http is None:
        _http = httpx.Client(timeout=HTTP_TIMEOUT, headers={"User-Agent": "JalSakshi/0.1"})
    return _http


def use_http_client(instance: httpx.Client | None) -> None:
    """Install an HTTP client (tests use ``httpx.MockTransport``)."""
    global _http
    _http = instance


@cache
def repository() -> Repository:
    """The stage's DynamoDB repository (table from ``$JALSAKSHI_TABLE``)."""
    cfg = settings()
    if not cfg.table_name:
        raise ConfigError("JALSAKSHI_TABLE is not set")
    return Repository(cfg.table_name, region=cfg.region, client=client("dynamodb"), clock=now)


# --- secrets --------------------------------------------------------------------------------------


class SecretStore:
    """Reads ``/jalsakshi/{stage}/{name}`` from SSM with decryption and a short cache."""

    def __init__(self, ttl_s: float = SECRET_TTL_S) -> None:
        self._ttl_s = ttl_s
        self._cache: dict[str, tuple[float, str | None]] = {}
        self._lock = threading.Lock()

    def get(self, name: str, *, required: bool = True) -> str | None:
        """The parameter's value; None (or ConfigError when required) if it does not exist."""
        with self._lock:
            hit = self._cache.get(name)
            if hit is not None and time.monotonic() - hit[0] < self._ttl_s:
                value = hit[1]
            else:
                value = self._fetch(name)
                self._cache[name] = (time.monotonic(), value)
        if value is None and required:
            raise ConfigError(f"SSM parameter {settings().ssm_prefix}{name} is missing")
        return value

    def clear(self) -> None:
        """Forget cached values."""
        with self._lock:
            self._cache.clear()

    @staticmethod
    def _fetch(name: str) -> str | None:
        path = f"{settings().ssm_prefix}{name}"
        try:
            response = client("ssm").get_parameter(Name=path, WithDecryption=True)
        except ClientError as err:
            if err.response.get("Error", {}).get("Code") == "ParameterNotFound":
                return None
            raise
        value = str(response["Parameter"]["Value"]).strip()
        return value or None


secrets = SecretStore()


def allowed_numbers() -> frozenset[str]:
    """Consenting test numbers that may be dialled (SSM StringList); empty when unset."""
    raw = secrets.get(ALLOWED_NUMBERS_PARAM, required=False)
    return frozenset(_csv(raw))


def reset() -> None:
    """Drop every cache and override (tests)."""
    settings.cache_clear()
    repository.cache_clear()
    secrets.clear()
    with _clients_lock:
        _clients.clear()
    use_http_client(None)
    set_clock(_utcnow)
