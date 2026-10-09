"""A "Team test village" for the team's own phones (TEST_NUMBERS), so the whole loop can be tried
without touching a real village: TEST_NUMBERS[0] and [1] are families, TEST_NUMBERS[2] is the
pump operator. By default the families have NOT agreed yet, so their first call is the real
consent call (language choice, notice, press 1, name and mohalla); --consented skips that.

    uv run --no-sync python scripts/seed_team_test.py --stage dev-<name>
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from seed_demo import REGION, load_env, mask, parse_numbers  # noqa: E402

from jalsakshi.core.models import (  # noqa: E402
    AccessKind,
    Consent,
    ConsentStatus,
    Household,
    Operator,
    OperatorRole,
    Village,
    WaterPoint,
    WaterPointKind,
)

VID: Final = "test-team"


def main(argv: Sequence[str] | None = None) -> int:
    env = load_env()
    parser = argparse.ArgumentParser(description="Seed the team test village.")
    parser.add_argument("--stage", default=env.get("STAGE"))
    parser.add_argument("--profile", default=env.get("AWS_PROFILE"))
    parser.add_argument("--consented", action="store_true", help="families already agreed")
    parser.add_argument("--languages", default="hi,hne", help="call languages, first = default")
    args = parser.parse_args(argv)
    numbers = parse_numbers(env.get("TEST_NUMBERS"))
    now = datetime.now(UTC)
    village = Village(
        id=VID,
        name="Team test village",
        name_hi="टीम टेस्ट गाँव",
        block="Test",
        district="Test",
        checkin_local_time="19:00",
        quorum=1,
        languages=[code.strip() for code in args.languages.split(",") if code.strip()],
    )
    point = WaterPoint(
        id="wp-piped-1",
        village_id=VID,
        kind=WaterPointKind.PIPED,
        name="Test tap",
        name_hi="टेस्ट नल",
        operator_ids=["op-test-team"],
    )
    consent = Consent(
        given_at=now, channel="in_person", evidence_ref="team member: agreed to test calls"
    )
    households = [
        Household(
            id=f"hh-test-{n + 1}",
            village_id=VID,
            phone_e164=phone,
            display_name=None,
            consent=consent if args.consented else None,
            consent_status=ConsentStatus.GRANTED if args.consented else ConsentStatus.NONE,
            access=AccessKind.HOUSE_TAP if args.consented else None,
            water_point_id=point.id if args.consented else None,
            registered_via="seed" if args.consented else "console",
        )
        for n, phone in enumerate(dict.fromkeys(numbers[:2]))
    ]
    operator = Operator(
        id="op-test-team",
        role=OperatorRole.NAL_JAL_MITRA,
        phone_e164=numbers[2],
        display_name="Team pump operator (test)",
        village_ids=[VID],
    )
    import boto3

    from jalsakshi.store import Repository

    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    repo = Repository(
        f"jalsakshi-{args.stage}",
        region=REGION,
        client=session.client("dynamodb", region_name=REGION),
    )
    repo.put_village(village)
    repo.put_water_point(point)
    repo.put_operator(operator)
    for h in households:
        repo.put_household(h)
    print(
        f"{village.name}: families {[mask(h.phone_e164) for h in households]}, "
        f"operator {mask(operator.phone_e164)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
