"""Fixtures: moto-backed DynamoDB, SSM and S3 in ap-south-1, a fake Step Functions client, a
fixed IST morning clock, and a seeded test village. Nothing can reach a real account."""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from jalsakshi.handlers import config
from jalsakshi.store import Repository, create_table

from .fakes import (
    BUCKET,
    CHECKIN_ARN,
    IVR_TOKEN,
    PHONES,
    STAGE,
    TABLE,
    Clock,
    FakeSfn,
    household,
    operator,
    village,
)

REGION = "ap-south-1"


@pytest.fixture(autouse=True)
def _quiet_empty_metrics() -> Iterator[None]:
    """Invocations that emit no metric are normal; Powertools warns about them."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="No application metrics to publish")
        yield


@pytest.fixture
def aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake credentials and the settings infra/ would set on a Lambda."""
    for key in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_REGION"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    env = {
        "JALSAKSHI_STAGE": STAGE,
        "JALSAKSHI_REGION": REGION,
        "JALSAKSHI_TABLE": TABLE,
        "JALSAKSHI_EVIDENCE_BUCKET": BUCKET,
        "JALSAKSHI_AUDIO_BASE_URL": "https://cdn.example.test/prompts/hi",
        "JALSAKSHI_API_URL": "https://abc123.execute-api.ap-south-1.amazonaws.com",
        "JALSAKSHI_CHECKIN_SFN_ARN": CHECKIN_ARN,
        "JALSAKSHI_BRIEF_USE_AGENT": "false",
        "VOICE_PROVIDER": "simulator",
        "POWERTOOLS_METRICS_NAMESPACE": "JalSakshi",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in ("JALSAKSHI_VOBIZ_VERIFY_SIGNATURE", "JALSAKSHI_IVR_ALLOWED_CIDRS"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def sfn_fake() -> FakeSfn:
    return FakeSfn()


@pytest.fixture
def aws(aws_env: None, clock: Clock, sfn_fake: FakeSfn) -> Iterator[dict[str, Any]]:
    """Mocked AWS with the table, the evidence bucket and the stage's SSM parameters."""
    with mock_aws():
        config.reset()
        ddb = boto3.client("dynamodb", region_name=REGION)
        ssm = boto3.client("ssm", region_name=REGION)
        s3 = boto3.client("s3", region_name=REGION)
        create_table(ddb, TABLE)
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        prefix = f"/jalsakshi/{STAGE}/"
        params = {
            "ivr_path_token": ("SecureString", IVR_TOKEN),
            "vobiz_auth_id": ("SecureString", "MA_TEST"),
            "vobiz_auth_token": ("SecureString", "vobiz-token"),
            "vobiz_did": ("SecureString", "+918000000000"),
            "allowed_numbers": ("StringList", ",".join(PHONES[:3])),
        }
        for name, (kind, value) in params.items():
            ssm.put_parameter(Name=f"{prefix}{name}", Type=kind, Value=value)
        config.use_client("dynamodb", ddb)
        config.use_client("ssm", ssm)
        config.use_client("s3", s3)
        config.use_client("stepfunctions", sfn_fake)
        config.set_clock(clock)
        yield {"ddb": ddb, "ssm": ssm, "s3": s3}
        config.reset()


@pytest.fixture
def repo(aws: dict[str, Any]) -> Repository:
    return config.repository()


@pytest.fixture
def seeded(repo: Repository) -> Repository:
    """Village v-test (quorum 2): h1 and h2 consented, h3 without consent, operator op-1."""
    repo.put_village(village())
    repo.put_household(household("h1", PHONES[0]))
    repo.put_household(household("h2", PHONES[1]))
    repo.put_household(household("h3", PHONES[3], consent=False))
    repo.put_operator(operator())
    return repo
