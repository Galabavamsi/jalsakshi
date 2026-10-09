"""Config, secrets, masking, metrics and the public-context cache."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from jalsakshi.core.models import Freshness, SourceTag
from jalsakshi.data import BlockGroundwater, DailyRain, RainSummary, StateHGJ
from jalsakshi.handlers import common, config, context
from jalsakshi.handlers.config import ConfigError, Settings, VoiceProvider
from jalsakshi.store import Repository

from .fakes import BUCKET, STAGE, VID, LambdaContext, village

FETCHED = datetime(2026, 10, 8, 4, 0, tzinfo=UTC)


def tag(name: str, freshness: Freshness = Freshness.ANNUAL) -> SourceTag:
    return SourceTag(source=name, fetched_at=FETCHED, freshness=freshness)


# --- settings and secrets -------------------------------------------------------------------------


def test_settings_defaults_are_safe() -> None:
    cfg = Settings.from_env({})
    assert cfg.region == "ap-south-1" and cfg.stage == "dev"
    assert cfg.voice_provider is VoiceProvider.SIMULATOR
    assert cfg.brief_use_agent is True and cfg.verify_vobiz_signature is False
    assert cfg.ssm_prefix == "/jalsakshi/dev/"


def test_settings_parse_flags_lists_and_urls() -> None:
    cfg = Settings.from_env(
        {
            "JALSAKSHI_STAGE": "dev-x",
            "VOICE_PROVIDER": "VOBIZ",
            "JALSAKSHI_AUDIO_BASE_URL": "https://cdn/prompts/hi/",
            "JALSAKSHI_IVR_ALLOWED_CIDRS": "1.2.3.0/24, 5.6.7.8/32",
            "JALSAKSHI_BRIEF_USE_AGENT": "no",
            "AWS_REGION": "us-east-1",
        }
    )
    assert cfg.voice_provider is VoiceProvider.VOBIZ and cfg.region == "ap-south-1"
    assert cfg.audio_base_url == "https://cdn/prompts/hi"
    assert cfg.ivr_allowed_cidrs == ("1.2.3.0/24", "5.6.7.8/32")
    assert cfg.brief_use_agent is False


def test_settings_reject_unknown_provider() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"VOICE_PROVIDER": "bolna"})


def test_secrets_are_read_decrypted_and_cached(aws: dict[str, Any]) -> None:
    assert config.secrets.get(config.IVR_TOKEN_PARAM) == "s3cret-path-token"
    aws["ssm"].delete_parameter(Name=f"/jalsakshi/{STAGE}/ivr_path_token")
    assert config.secrets.get(config.IVR_TOKEN_PARAM) == "s3cret-path-token"
    config.secrets.clear()
    assert config.secrets.get(config.IVR_TOKEN_PARAM, required=False) is None
    with pytest.raises(ConfigError):
        config.secrets.get(config.IVR_TOKEN_PARAM)


def test_allowed_numbers(aws: dict[str, Any]) -> None:
    assert "+919800000001" in config.allowed_numbers()
    assert "+919800000009" not in config.allowed_numbers()


def test_repository_needs_a_table(aws: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JALSAKSHI_TABLE")
    config.reset()
    with pytest.raises(ConfigError):
        config.repository()


# --- common helpers -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("phone", "masked"),
    [("+919876543210", "+91XXXXXX3210"), ("+14155550100", "+14XXXXX0100"), (None, None)],
)
def test_mask_phone(phone: str | None, masked: str | None) -> None:
    assert common.mask_phone(phone) == masked


def test_dimensioned_metric_is_emitted_as_emf(capsys: pytest.CaptureFixture[str]) -> None:
    common.count("PolicyDenied", policy_id="calling-hours")
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if "_aws" in line]
    [emf] = lines
    assert emf["policy_id"] == "calling-hours" and emf["service"] == "jalsakshi"
    assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "JalSakshi"


def test_activity_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> Repository:
        raise RuntimeError("no table")

    monkeypatch.setattr(config, "repository", broken)
    common.activity("call", VID, "x", "y")


# --- public context -------------------------------------------------------------------------------


def sample_sources() -> tuple[list[BlockGroundwater], StateHGJ, RainSummary]:
    blocks = [
        BlockGroundwater(
            block="Patan",
            district="Durg",
            category="Semi Critical",
            stage_pct=84.2,
            source=tag("CGWB"),
        )
    ]
    state = StateHGJ(
        state="Chhattisgarh",
        villages=19658,
        reported=7603,
        certified=6594,
        as_on=date(2026, 10, 7),
        source=tag("JJM IMIS", Freshness.DAILY),
    )
    rain = RainSummary(
        total_mm=12.4,
        daily=[DailyRain(date=date(2026, 10, 7), mm=12.4)],
        source=tag("Open-Meteo", Freshness.MODEL),
    )
    return blocks, state, rain


def test_build_context_matches_the_api_contract() -> None:
    blocks, state, rain = sample_sources()
    hindi = village().model_copy(update={"block": "पाटन", "district": "दुर्ग"})
    built = context.build_context(hindi, blocks, state, rain)
    assert built["groundwater"]["stage_pct"] == 84.2
    assert built["groundwater"]["source"]["source"] == "CGWB"
    assert built["rain_7d_mm"]["value"] == 12.4
    assert set(built["state_hgj"]) == {"villages", "reported", "certified", "source"}
    assert context.build_context(village(), None, None, None) == {
        "groundwater": None,
        "rain_7d_mm": None,
        "state_hgj": None,
        "nearest_well": None,
        "district_rain": None,
    }


def test_rain_point_uses_district_hq() -> None:
    assert context.rain_point(village()) == (21.19, 81.28)
    assert context.rain_point(village().model_copy(update={"district": "Nowhere"})) is None


def test_refresh_writes_each_village(
    seeded: Repository, aws: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    blocks, state, _ = sample_sources()
    monkeypatch.setattr(context, "fetch_state_hgj", lambda *a, **k: state)
    monkeypatch.setattr(context, "fetch_block_groundwater_or_snapshot", lambda *a, **k: blocks)

    def no_rain(*_: Any, **__: Any) -> RainSummary:
        raise context.DataSourceError("open-meteo down")

    monkeypatch.setattr(context, "rain_last_days", no_rain)
    out = context.refresh({}, LambdaContext())
    assert out == {"villages": 1, "state_hgj": True, "groundwater": True}
    stored = context.load_context(VID)
    assert stored["rain_7d_mm"] is None and stored["state_hgj"]["villages"] == 19658
    obj = aws["s3"].get_object(Bucket=BUCKET, Key=context.context_key(VID))
    assert obj["ContentType"] == "application/json"


def test_load_context_missing_is_empty(aws: dict[str, Any]) -> None:
    assert context.load_context("nowhere") == {}
