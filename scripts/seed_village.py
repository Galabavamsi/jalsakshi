"""Seed one stage with the REAL pilot village (Kutelabhatha, LGD 442569) for v2 (§15).

Only real, verifiable records go in: the village master record (LGD, Census 2011, location with
its source), one water point for the village's piped scheme as listed in JJM IMIS, and the pilot
coordinator who stands in for the Panchayat (clearly named as such). Families are added with
``--families`` and get **no answers seeded**: their first call is the consent (registration) call.
The team's own test phones stay in the demo villages (scripts/seed_demo.py), so nothing a team
member presses is ever recorded against a real village.

    uv run --no-sync python scripts/seed_village.py --stage dev-<name> [--dry-run]
        [--families +91...,+91...] [--register-calls] [--allowlist] [--schedule]

--families        consenting-to-be-called numbers of real families (also read from
                  PILOT_FAMILIES in .env); each gets a household with consent NONE
--register-calls  invoke the outbound Lambda to place each family's consent call now
                  (only between 09:00 and 21:00 IST; Cedar checks again)
--allowlist       write SSM allowed_numbers = TEST_NUMBERS + families
--schedule        daily CheckInRun schedule for the village at its check-in time (19:00 IST)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

REPO: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from seed_demo import (  # noqa: E402
    REGION,
    load_env,
    mask,
    parse_numbers,
    stack_outputs,
    upsert_schedules,
    write_allowlist,
)

from jalsakshi.core.models import (  # noqa: E402
    ConsentStatus,
    Household,
    Operator,
    OperatorRole,
    Village,
    WaterPoint,
    WaterPointKind,
)
from jalsakshi.data.villages import load_villages  # noqa: E402

PILOT_LGD: Final = "442569"
COORDINATOR_ID: Final = "op-pilot-coordinator"
PIPED_POINT_ID: Final = "wp-piped-1"


def pilot_village() -> Village:
    """Kutelabhatha from the bundled LGD/Census master (inbound missed calls register here)."""
    village = next(v for v in load_villages() if v.lgd_code == PILOT_LGD)
    return village.model_copy(
        update={"inbound": True, "active": True, "checkin_local_time": "19:00"}
    )


def piped_point(village: Village) -> WaterPoint:
    """The village's piped scheme, as JJM IMIS lists it (retrofit 40006378, deep tubewell)."""
    return WaterPoint(
        id=PIPED_POINT_ID,
        village_id=village.id,
        kind=WaterPointKind.PIPED,
        name="Kutelabhatha piped water scheme (IMIS 40006378)",
        name_hi="कुटेलाभाटा नल जल योजना",
        operator_ids=[COORDINATOR_ID],
        provisional=False,
    )


def coordinator(village: Village, phone: str) -> Operator:
    """The pilot coordinator: receives complaints and passes them to the Panchayat."""
    return Operator(
        id=COORDINATOR_ID,
        role=OperatorRole.PANCHAYAT_SECRETARY,
        phone_e164=phone,
        display_name="Pilot coordinator, IIT Bhilai team (stands in for the Panchayat)",
        village_ids=[village.id],
    )


def family(village: Village, phone: str) -> Household:
    """A real family's number before its consent call (never called for answers until then)."""
    hid = "hh-" + hashlib.sha256(phone.encode()).hexdigest()[:10]
    return Household(
        id=hid,
        village_id=village.id,
        phone_e164=phone,
        consent_status=ConsentStatus.NONE,
        registered_via="console",
    )


def main(argv: Sequence[str] | None = None, *, session: Any = None) -> int:
    env = load_env()
    parser = argparse.ArgumentParser(description="Seed the real JalSakshi pilot village.")
    parser.add_argument("--stage", default=env.get("STAGE"))
    parser.add_argument("--profile", default=env.get("AWS_PROFILE"))
    parser.add_argument("--numbers", default=env.get("TEST_NUMBERS"))
    parser.add_argument("--families", default=env.get("PILOT_FAMILIES", ""))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--register-calls", action="store_true")
    parser.add_argument("--allowlist", action="store_true")
    parser.add_argument("--schedule", action="store_true")
    args = parser.parse_args(argv)
    if not args.stage:
        parser.error("--stage is required (or STAGE in .env)")
    team = parse_numbers(args.numbers)
    families = [n.strip() for n in args.families.split(",") if n.strip()]
    if any(not n.startswith("+91") or len(n) != 13 for n in families):
        parser.error("--families must be +91XXXXXXXXXX numbers, comma separated")
    if set(families) & set(team):
        parser.error("a team test phone cannot be a pilot family (keeps real data honest)")
    village = pilot_village()
    point = piped_point(village)
    op = coordinator(village, team[2])
    households = [family(village, n) for n in families]
    mode = "DRY RUN" if args.dry_run else f"writing to jalsakshi-{args.stage}"
    print(f"Pilot village {village.id} {village.name} (LGD {village.lgd_code}): {mode}")
    print(f"  water point {point.id}: {point.name}")
    print(f"  coordinator {op.id} {mask(op.phone_e164)}")
    for h in households:
        print(f"  family {h.id} {mask(h.phone_e164)} (consent call pending)")
    if args.dry_run:
        return 0
    if session is None:
        import boto3

        session = boto3.Session(profile_name=args.profile, region_name=REGION)
    from jalsakshi.store import Repository

    table = f"jalsakshi-{args.stage}"
    repo = Repository(table, region=REGION, client=session.client("dynamodb", region_name=REGION))
    repo.put_village(village)
    repo.put_water_point(point)
    repo.put_operator(op)
    for h in households:
        existing = repo.get_household(village.id, h.id)
        if existing is None or existing.effective_consent is ConsentStatus.NONE:
            repo.put_household(h)
    if args.allowlist:
        numbers = list(dict.fromkeys([*team, *families]))
        write_allowlist(session.client("ssm", region_name=REGION), args.stage, numbers)
        print(f"allowlist: {len(numbers)} numbers")
    if args.schedule:
        outputs = stack_outputs(session.client("cloudformation", region_name=REGION), args.stage)
        upsert_schedules(session.client("scheduler", region_name=REGION), [village], outputs)
        print(f"schedule: daily check-in at {village.checkin_local_time} IST")
    if args.register_calls:
        lam = session.client("lambda", region_name=REGION)
        for h in households:
            job = {"kind": "register", "village_id": village.id, "household_id": h.id}
            lam.invoke(
                FunctionName=f"jalsakshi-{args.stage}-outbound",
                InvocationType="Event",
                Payload=json.dumps(job).encode(),
            )
            print(f"  consent call queued for {mask(h.phone_e164)}")
    print(f"seeded at {datetime.now(UTC).isoformat(timespec='seconds')}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
