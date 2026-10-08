"""scripts/build_lambda.py and scripts/seed_demo.py, offline (fake runner, moto)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import boto3
import pytest
from moto import mock_aws

from jalsakshi.store import Repository, create_table

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
NUMBERS = "+919800000001,+919800000002,+919800000003"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"jalsakshi_script_{name}", SCRIPTS / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build_lambda = load("build_lambda")
seed_demo = load("seed_demo")


# --- build_lambda ---------------------------------------------------------------------------------

EXPORTED = """\
annotated-types==0.7.0
aws-lambda-powertools==3.35.0
boto3==1.43.109
botocore==1.43.109
cedarpy==4.12.1
colorama==0.4.6 ; sys_platform == 'win32'
jmespath==1.1.0
pydantic==2.12.0
s3transfer==0.14.0
-e .
"""


class FakeRunner:
    """Stands in for subprocess.run: answers uv export, fakes uv pip install."""

    def __init__(self, export_code: int = 0) -> None:
        self.commands: list[list[str]] = []
        self.export_code = export_code

    def __call__(self, cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(cmd)
        if cmd[:2] == ["uv", "export"]:
            return subprocess.CompletedProcess(cmd, self.export_code, EXPORTED, "lock is stale")
        target = Path(cmd[cmd.index("--target") + 1])
        (target / "pydantic").mkdir(parents=True, exist_ok=True)
        (target / "pydantic" / "__init__.py").write_text("", encoding="utf-8")
        (target / "bin").mkdir(exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")


def test_filter_requirements_drops_runtime_provided_and_comments() -> None:
    kept = build_lambda.filter_requirements(EXPORTED, build_lambda.RUNTIME_PROVIDED)
    assert kept == [
        "annotated-types==0.7.0",
        "aws-lambda-powertools==3.35.0",
        "cedarpy==4.12.1",
        "colorama==0.4.6 ; sys_platform == 'win32'",
        "pydantic==2.12.0",
    ]


def test_build_installs_manylinux_wheels_and_copies_sources(tmp_path: Path) -> None:
    out = tmp_path / "lambda"
    runner = FakeRunner()
    assert build_lambda.main(["--out", str(out)], runner=runner) == 0
    install = runner.commands[1]
    assert install[:3] == ["uv", "pip", "install"]
    for flag, value in [
        ("--python-platform", "x86_64-manylinux2014"),
        ("--python-version", "3.12"),
        ("--only-binary", ":all:"),
    ]:
        assert install[install.index(flag) + 1] == value
    assert "--no-deps" in install
    requirements = (tmp_path / "requirements-lambda.txt").read_text(encoding="utf-8")
    assert "boto3" not in requirements and "cedarpy==4.12.1" in requirements
    assert (out / "jalsakshi/policy/policies/jalsakshi.cedar").is_file()
    assert (out / "prompts/hi.yaml").is_file()
    assert not (out / "bin").exists()
    assert not list(out.rglob("__pycache__"))
    marker = json.loads((out / build_lambda.MARKER).read_text(encoding="utf-8"))
    assert marker["platform"] == "x86_64-manylinux2014" and marker["requirements"] == 5


def test_source_only_refreshes_code_and_keeps_dependencies(tmp_path: Path) -> None:
    out = tmp_path / "lambda"
    assert build_lambda.main(["--out", str(out), "--source-only"], runner=FakeRunner()) == 1
    build_lambda.main(["--out", str(out)], runner=FakeRunner())
    runner = FakeRunner()
    assert build_lambda.main(["--out", str(out), "--source-only"], runner=runner) == 0
    assert runner.commands == []
    assert (out / "pydantic/__init__.py").is_file()


def test_stale_lock_fails_with_advice(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = build_lambda.main(["--out", str(tmp_path / "x")], runner=FakeRunner(export_code=2))
    assert code == 1 and "uv lock" in capsys.readouterr().err


def test_include_boto3_keeps_it(tmp_path: Path) -> None:
    build_lambda.main(["--out", str(tmp_path / "l"), "--include-boto3"], runner=FakeRunner())
    assert "boto3==" in (tmp_path / "requirements-lambda.txt").read_text(encoding="utf-8")


# --- seed_demo ------------------------------------------------------------------------------------


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> Iterator[boto3.Session]:
    for key in ("AWS_PROFILE", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        boto_session = boto3.Session(region_name="ap-south-1")
        create_table(boto_session.client("dynamodb"), "jalsakshi-dev-seed")
        yield boto_session


def test_parse_numbers_needs_three_e164() -> None:
    assert seed_demo.parse_numbers(NUMBERS)[2] == "+919800000003"
    for bad in ("", "+919800000001,+919800000002", "+91980,+919800000002,+919800000003"):
        with pytest.raises(ValueError):
            seed_demo.parse_numbers(bad)


def test_demo_data_is_labelled_and_consented() -> None:
    data = seed_demo.demo_data(NUMBERS.split(","), datetime(2026, 10, 8, tzinfo=UTC))
    assert [v.id for v in data.villages] == ["v-nayapara", "v-amlidih"]
    assert all("डेमो" in v.name and v.district == "Durg" for v in data.villages)
    assert all(
        v.claimed_source and v.claimed_source.freshness == "simulated" for v in data.villages
    )
    consented = [h for h in data.households if h.consent_given]
    assert len(consented) == 4 and len(data.households) == 6
    assert {h.phone_e164 for h in consented} == {"+919800000001", "+919800000002"}
    assert [o.role for o in data.operators] == ["NAL_JAL_MITRA", "NAL_JAL_MITRA", "PHED_AE_SIM"]


def test_schedule_request_is_ist_cron_with_dlq() -> None:
    village = seed_demo.demo_data(NUMBERS.split(","), datetime.now(UTC)).villages[0]
    outputs = {"CheckInRunArn": "arn:sfn", "SchedulerRoleArn": "arn:role", "SchedulerDlqArn": "q"}
    request = seed_demo.schedule_request(village, outputs, group="g")
    assert request["ScheduleExpression"] == "cron(30 10 * * ? *)"
    assert request["ScheduleExpressionTimezone"] == "Asia/Kolkata"
    assert json.loads(request["Target"]["Input"])["village_id"] == "v-nayapara"
    late = village.model_copy(update={"checkin_local_time": "21:30"})
    with pytest.raises(ValueError):
        seed_demo.schedule_request(late, outputs, group="g")


def test_dry_run_writes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    code = seed_demo.main(["--stage", "dev-seed", "--numbers", NUMBERS, "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0 and "DRY RUN" in out
    assert "+919800000001" not in out and "+91XXXXXX0001" in out


def test_seed_writes_data_allowlist_and_token(session: boto3.Session) -> None:
    argv = ["--stage", "dev-seed", "--numbers", NUMBERS, "--allowlist", "--ivr-token"]
    assert seed_demo.main(argv, session=session) == 0
    repo = Repository("jalsakshi-dev-seed", client=session.client("dynamodb"))
    assert [v.id for v in repo.list_villages()] == ["v-amlidih", "v-nayapara"]
    assert len(repo.list_households("v-nayapara")) == 3
    assert [o.id for o in repo.list_operators_for_village("v-nayapara")] == [
        "op-nyp-njm",
        "op-phed-ae",
    ]
    ssm = session.client("ssm")
    allowed = ssm.get_parameter(Name="/jalsakshi/dev-seed/allowed_numbers")["Parameter"]
    assert allowed["Value"] == NUMBERS and allowed["Type"] == "StringList"
    token = ssm.get_parameter(Name="/jalsakshi/dev-seed/ivr_path_token", WithDecryption=True)
    assert len(token["Parameter"]["Value"]) >= 24
    assert seed_demo.ensure_ivr_token(ssm, "dev-seed") is False


class FakeScheduler:
    class exceptions:
        class ResourceNotFoundException(Exception):
            pass

    def __init__(self) -> None:
        self.schedules: dict[str, dict[str, Any]] = {}

    def update_schedule(self, **request: Any) -> None:
        if request["Name"] not in self.schedules:
            raise self.exceptions.ResourceNotFoundException
        self.schedules[request["Name"]] = request

    def create_schedule(self, **request: Any) -> None:
        self.schedules[request["Name"]] = request


def test_schedules_are_upserted() -> None:
    data = seed_demo.demo_data(NUMBERS.split(","), datetime.now(UTC))
    outputs = {
        "ScheduleGroupName": "jalsakshi-dev-seed-checkins",
        "CheckInRunArn": "arn:sfn",
        "SchedulerRoleArn": "arn:role",
        "SchedulerDlqArn": "arn:dlq",
    }
    fake = FakeScheduler()
    assert seed_demo.upsert_schedules(fake, data.villages, outputs) == 2
    assert seed_demo.upsert_schedules(fake, data.villages, outputs) == 2
    assert set(fake.schedules) == {"checkin-v-nayapara", "checkin-v-amlidih"}
    assert fake.schedules["checkin-v-amlidih"]["ScheduleExpression"] == "cron(0 11 * * ? *)"
