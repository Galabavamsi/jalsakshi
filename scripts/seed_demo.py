"""Seed one stage with DEMO data: two invented villages in Durg district, their households and
operators. Households and the pump operator are the team's consenting test phones from
``.env`` TEST_NUMBERS (household 1, household 2, pump operator); a third household per village
has no consent on file, so Cedar's consent-required rule can be shown. Every village carries a
``simulated`` SourceTag and a "(डेमो)" name: this is demo data, not an IMIS record.

    uv run --no-sync python scripts/seed_demo.py --stage dev-<name> [--dry-run]
        [--allowlist] [--ivr-token] [--schedules]

--allowlist   write SSM /jalsakshi/{stage}/allowed_numbers (StringList) from TEST_NUMBERS
--ivr-token   create SSM /jalsakshi/{stage}/ivr_path_token (SecureString) if it is missing
--schedules   create or update one EventBridge Scheduler schedule per village (Asia/Kolkata),
              using the outputs of the JalSakshi-{stage}-App stack
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

REPO: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from jalsakshi.core.clock import parse_hhmm  # noqa: E402
from jalsakshi.core.models import (  # noqa: E402
    Consent,
    Freshness,
    Household,
    Operator,
    OperatorRole,
    SourceTag,
    Village,
)

REGION: Final = "ap-south-1"
TIMEZONE: Final = "Asia/Kolkata"
NO_CONSENT_PHONE: Final = "+910000000001"  # placeholder: never on the allowlist, never dialled
CONSENT_REF: Final = "demo-team-consent-2026-10-08"
_E164 = re.compile(r"^\+\d{10,15}$")


@dataclass(frozen=True, slots=True)
class DemoData:
    """Everything the seed writes to the table."""

    villages: list[Village]
    households: list[Household]
    operators: list[Operator]


def parse_numbers(raw: str | None) -> list[str]:
    """TEST_NUMBERS as E.164 numbers; needs household 1, household 2 and the pump operator."""
    numbers = [part.strip() for part in (raw or "").split(",") if part.strip()]
    bad = [n for n in numbers if not _E164.match(n)]
    if bad or len(numbers) < 3:
        raise ValueError("TEST_NUMBERS needs at least 3 E.164 numbers like +919876543210")
    return numbers


def demo_data(numbers: Sequence[str], now: datetime) -> DemoData:
    """The two demo villages, their households and operators."""
    claimed = SourceTag(
        source="Demo data: invented village, not an IMIS record",
        fetched_at=now,
        freshness=Freshness.SIMULATED,
    )
    consent = Consent(given_at=now, channel="in_person", evidence_ref=CONSENT_REF)
    specs = [
        ("v-nayapara", "नयापारा (डेमो)", "Patan", "10:30", "nyp"),
        ("v-amlidih", "अमलीडीह (डेमो)", "Dhamdha", "11:00", "aml"),
    ]
    villages, households, operators = [], [], []
    for vid, name, block, at, short in specs:
        villages.append(
            Village(
                id=vid,
                name=name,
                block=block,
                district="Durg",
                claimed_hgj=True,
                hgj_certified=False,
                claimed_source=claimed,
                checkin_local_time=at,
                quorum=2,
            )
        )
        for n, phone in enumerate(numbers[:2], start=1):
            households.append(
                Household(
                    id=f"hh-{short}-{n}",
                    village_id=vid,
                    phone_e164=phone,
                    display_name=f"Demo household {n}",
                    consent=consent,
                )
            )
        households.append(
            Household(
                id=f"hh-{short}-3",
                village_id=vid,
                phone_e164=NO_CONSENT_PHONE,
                display_name="Demo household without consent",
            )
        )
        operators.append(
            Operator(
                id=f"op-{short}-njm",
                role=OperatorRole.NAL_JAL_MITRA,
                phone_e164=numbers[2],
                display_name=f"Demo Nal Jal Mitra ({name})",
                village_ids=[vid],
            )
        )
    operators.append(
        Operator(
            id="op-phed-ae",
            role=OperatorRole.PHED_AE_SIM,
            phone_e164=numbers[2],
            display_name="PHED AE (simulated)",
            village_ids=[v.id for v in villages],
        )
    )
    return DemoData(villages, households, operators)


def schedule_request(village: Village, outputs: Mapping[str, str], *, group: str) -> dict[str, Any]:
    """EventBridge Scheduler request that starts CheckInRun at the village's local time."""
    at = parse_hhmm(village.checkin_local_time)
    if not 9 <= at.hour < 21:
        raise ValueError(f"{village.id}: check-ins must be between 09:00 and 21:00 IST")
    payload = {"village_id": village.id, "purpose": "DAILY", "trigger": "schedule"}
    return {
        "Name": f"checkin-{village.id}",
        "GroupName": group,
        "ScheduleExpression": f"cron({at.minute} {at.hour} * * ? *)",
        "ScheduleExpressionTimezone": TIMEZONE,
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "State": "ENABLED",
        "Description": f"JalSakshi daily check-in for {village.id} (demo)",
        "Target": {
            "Arn": outputs["CheckInRunArn"],
            "RoleArn": outputs["SchedulerRoleArn"],
            "Input": json.dumps(payload),
            "DeadLetterConfig": {"Arn": outputs["SchedulerDlqArn"]},
            "RetryPolicy": {"MaximumRetryAttempts": 2, "MaximumEventAgeInSeconds": 3600},
        },
    }


def mask(phone: str) -> str:
    """Show only the last four digits."""
    return f"{phone[:3]}{'X' * max(len(phone) - 7, 0)}{phone[-4:]}"


# --- AWS side effects -----------------------------------------------------------------------------


def write_data(repo: Any, data: DemoData) -> None:
    """Put every village, household and operator (idempotent upserts)."""
    for village in data.villages:
        repo.put_village(village)
    for household in data.households:
        repo.put_household(household)
    for operator in data.operators:
        repo.put_operator(operator)


def write_allowlist(ssm: Any, stage: str, numbers: Sequence[str]) -> None:
    """The dialler only calls numbers on this list (handlers/dialer.py)."""
    ssm.put_parameter(
        Name=f"/jalsakshi/{stage}/allowed_numbers",
        Type="StringList",
        Value=",".join(numbers),
        Overwrite=True,
        Description="Consenting test phones JalSakshi may dial (team only)",
    )


def ensure_ivr_token(ssm: Any, stage: str) -> bool:
    """Create the secret webhook path token once; True when a new one was written."""
    name = f"/jalsakshi/{stage}/ivr_path_token"
    try:
        ssm.get_parameter(Name=name, WithDecryption=True)
    except ssm.exceptions.ParameterNotFound:
        ssm.put_parameter(Name=name, Type="SecureString", Value=secrets.token_urlsafe(24))
        return True
    return False


def stack_outputs(cloudformation: Any, stage: str) -> dict[str, str]:
    """Outputs of the stage's App stack."""
    stack = cloudformation.describe_stacks(StackName=f"JalSakshi-{stage}-App")["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def upsert_schedules(
    scheduler: Any, villages: Sequence[Village], outputs: Mapping[str, str]
) -> int:
    """Create or update one schedule per village; returns how many were written."""
    group = outputs["ScheduleGroupName"]
    for village in villages:
        request = schedule_request(village, outputs, group=group)
        try:
            scheduler.update_schedule(**request)
        except scheduler.exceptions.ResourceNotFoundException:
            scheduler.create_schedule(**request)
    return len(villages)


# --- CLI ------------------------------------------------------------------------------------------


def load_env() -> dict[str, str]:
    """Values from the repo's .env (gitignored), if python-dotenv and the file exist."""
    try:
        from dotenv import dotenv_values
    except ImportError:
        return {}
    path = REPO / ".env"
    return {k: v for k, v in dotenv_values(path).items() if v} if path.is_file() else {}


def main(argv: Sequence[str] | None = None, *, session: Any = None) -> int:
    """CLI entrypoint; ``session`` is a boto3 Session (tests pass one bound to moto)."""
    env = load_env()
    parser = argparse.ArgumentParser(description="Seed JalSakshi demo data for one stage.")
    parser.add_argument("--stage", default=env.get("STAGE"))
    parser.add_argument("--table", help="defaults to jalsakshi-{stage}")
    parser.add_argument("--profile", default=env.get("AWS_PROFILE"))
    parser.add_argument("--numbers", default=env.get("TEST_NUMBERS"), help="defaults to .env")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allowlist", action="store_true")
    parser.add_argument("--ivr-token", action="store_true")
    parser.add_argument("--schedules", action="store_true")
    args = parser.parse_args(argv)
    if not args.stage:
        parser.error("--stage is required (or STAGE in .env)")
    try:
        numbers = parse_numbers(args.numbers)
    except ValueError as exc:
        parser.error(str(exc))
    data = demo_data(numbers, datetime.now(UTC))
    table = args.table or f"jalsakshi-{args.stage}"
    _report(data, table, args)
    if args.dry_run:
        return 0
    if session is None:
        import boto3

        session = boto3.Session(profile_name=args.profile, region_name=REGION)
    from jalsakshi.store import Repository

    repo = Repository(table, region=REGION, client=session.client("dynamodb", region_name=REGION))
    write_data(repo, data)
    ssm = session.client("ssm", region_name=REGION)
    if args.allowlist:
        write_allowlist(ssm, args.stage, numbers)
        print(f"allowlist: {len(numbers)} numbers")
    if args.ivr_token:
        created = ensure_ivr_token(ssm, args.stage)
        print("ivr_path_token: " + ("created" if created else "already set"))
    if args.schedules:
        outputs = stack_outputs(session.client("cloudformation", region_name=REGION), args.stage)
        count = upsert_schedules(
            session.client("scheduler", region_name=REGION), data.villages, outputs
        )
        print(f"schedules: {count} written to {outputs['ScheduleGroupName']}")
    print("seeded.")
    return 0


def _report(data: DemoData, table: str, args: argparse.Namespace) -> None:
    mode = "DRY RUN, nothing written" if args.dry_run else f"writing to {table} ({REGION})"
    print(f"JalSakshi demo seed for stage {args.stage}: {mode}")
    for village in data.villages:
        print(f"  village {village.id} {village.name} at {village.checkin_local_time} IST")
    for household in data.households:
        consent = "consent" if household.consent_given else "NO consent"
        print(f"  household {household.id} {mask(household.phone_e164)} ({consent})")
    for operator in data.operators:
        print(f"  operator {operator.id} {operator.role} {mask(operator.phone_e164)}")


if __name__ == "__main__":
    raise SystemExit(main())
