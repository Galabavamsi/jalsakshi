"""Stage settings: explicit -c context beats per-stage cdk.json defaults; custom console domain."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

cdk = pytest.importorskip("aws_cdk")
from aws_cdk.assertions import Match, Template  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))
from jalsakshi_infra.settings import StageSettings  # noqa: E402
from jalsakshi_infra.web_stack import WebStack  # noqa: E402

CERT = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"


def settings(**context: object) -> StageSettings:
    return StageSettings.from_app(cdk.App(context=dict(context)))


def test_stage_defaults_apply() -> None:
    cfg = settings(
        stage="dev-x", stages={"dev-x": {"voice_provider": "vobiz", "retry_wait_minutes": 2}}
    )
    assert cfg.voice_provider == "vobiz"
    assert cfg.retry_wait_minutes == 2


def test_explicit_context_wins_over_stage_defaults() -> None:
    cfg = settings(
        stage="dev-x", voice_provider="simulator", stages={"dev-x": {"voice_provider": "vobiz"}}
    )
    assert cfg.voice_provider == "simulator"


def test_other_stages_keep_safe_defaults() -> None:
    cfg = settings(stage="dev-y", stages={"dev-x": {"voice_provider": "vobiz"}})
    assert cfg.voice_provider == "simulator"
    assert cfg.web_domain is None


def test_custom_domain_on_console_distribution() -> None:
    cfg = settings(
        stage="dev-x", stages={"dev-x": {"web_domain": "js.example.org", "web_cert_arn": CERT}}
    )
    app = cdk.App()
    stack = WebStack(
        app, "Web", cfg=cfg, env=cdk.Environment(account="123456789012", region="ap-south-1")
    )
    t = Template.from_stack(stack)
    t.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {"DistributionConfig": Match.object_like({"Aliases": ["js.example.org"]})},
    )
    t.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {"CallbackURLs": Match.array_with(["https://js.example.org/auth/callback"])},
    )
    assert stack.web_url == "https://js.example.org"
