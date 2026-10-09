"""Seed a clearly labelled SAMPLE village with 30 days of generated history (§16).

For showing the whole product (reports, reliability, repair times) before a real village has
history. Everything here is generated: the village is named "Sample village (नमूना गाँव)", its
id starts with ``sample-``, every answer is stored with ``captured_via = SIMULATOR`` (so every
number's source reads "simulated"), and the families' numbers are ``+910000…`` placeholders
that the dialler never calls. Day statuses are computed by the real reconciler from those
answers; complaints follow the real state machine. Never used for a real, named village.

    uv run --no-sync python scripts/seed_sample.py --stage dev-<name> [--days 30] [--dry-run]
"""

from __future__ import annotations

import argparse
import random
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from seed_demo import REGION, load_env  # noqa: E402

from jalsakshi.core.clock import IST  # noqa: E402
from jalsakshi.core.models import (  # noqa: E402
    AccessKind,
    CallOutcome,
    CapturedVia,
    CheckIn,
    CleanAnswer,
    Consent,
    ConsentStatus,
    Household,
    Operator,
    OperatorRole,
    Purpose,
    TicketOrigin,
    TicketReason,
    Village,
    WaterAnswer,
    WaterPoint,
    WaterPointKind,
)
from jalsakshi.core.reconcile import reconcile_day  # noqa: E402
from jalsakshi.core.tickets import TicketEventKind, new_ticket, transition  # noqa: E402

VID: Final = "sample-village"
POINTS: Final = [
    ("wp-piped-1", WaterPointKind.PIPED, "Village tap scheme", "गाँव की नल जल योजना"),
    ("wp-handpump-1", WaterPointKind.HANDPUMP, "Handpump near school", "स्कूल के पास हैंडपंप"),
]
# (water point, access) for 8 sample families
FAMILIES: Final = [("wp-piped-1", AccessKind.HOUSE_TAP)] * 5 + [
    ("wp-handpump-1", AccessKind.HANDPUMP)
] * 3
OUTAGES: Final = {
    ("wp-piped-1", 6),
    ("wp-piped-1", 7),
    ("wp-piped-1", 19),
    ("wp-handpump-1", 12),
    ("wp-handpump-1", 28),
}
DIRTY: Final = {("wp-piped-1", 24)}


def build(days: int, today: date, rng: random.Random) -> dict:
    now = datetime.now(UTC)
    village = Village(
        id=VID,
        name="Sample village",
        name_hi="नमूना गाँव",
        block="Sample block",
        district="Sample district",
        gram_panchayat="Sample Gram Panchayat",
        checkin_local_time="19:00",
        quorum=2,
    )
    points = [
        WaterPoint(id=i, village_id=VID, kind=k, name=n, name_hi=h, operator_ids=["op-sample-njm"])
        for i, k, n, h in POINTS
    ]
    operators = [
        Operator(
            id="op-sample-njm",
            role=OperatorRole.NAL_JAL_MITRA,
            phone_e164="+910000000901",
            display_name="Sample pump operator",
            village_ids=[VID],
        ),
        Operator(
            id="op-sample-sarpanch",
            role=OperatorRole.SARPANCH,
            phone_e164="+910000000902",
            display_name="Sample sarpanch",
            village_ids=[VID],
        ),
    ]
    start = today - timedelta(days=days)
    households = [
        Household(
            id=f"hh-sample-{n + 1}",
            village_id=VID,
            phone_e164=f"+9100000001{n + 1:02d}",
            consent=Consent(
                given_at=datetime.combine(start, datetime.min.time(), IST), channel="ivr_keypad"
            ),
            consent_status=ConsentStatus.GRANTED,
            access=access,
            water_point_id=wp,
            registered_via="ivr",
        )
        for n, (wp, access) in enumerate(FAMILIES)
    ]
    checkins, statuses, tickets = [], [], []
    for offset in range(days):
        day = start + timedelta(days=offset + 1)
        at = datetime.combine(day, datetime.min.time(), IST).replace(hour=19, minute=2)
        for h in households:
            if rng.random() < 0.18:
                outcome, water, clean = CallOutcome.UNREACHABLE, None, None
            else:
                bad = (h.water_point_id, offset) in OUTAGES
                dirty = (h.water_point_id, offset) in DIRTY
                water = WaterAnswer.NO if bad and rng.random() < 0.85 else WaterAnswer.YES
                if not bad and rng.random() < 0.06:
                    water = WaterAnswer.PARTIAL
                clean = (
                    CleanAnswer.NO
                    if dirty and water is not WaterAnswer.NO
                    else (CleanAnswer.YES if water is not WaterAnswer.NO else None)
                )
                outcome = CallOutcome.ANSWERED
            checkins.append(
                CheckIn(
                    village_id=VID,
                    date=day,
                    household_id=h.id,
                    call_id=f"sample-{h.id}-{day:%Y%m%d}",
                    purpose=Purpose.DAILY,
                    outcome=outcome,
                    water=water,
                    hours=rng.choice([2, 3, 4]) if water is WaterAnswer.YES else None,
                    clean=clean,
                    water_point_id=h.water_point_id,
                    captured_via=CapturedVia.SIMULATOR,
                    captured_at=at + timedelta(minutes=rng.randint(0, 20)),
                )
            )
        day_checkins = [c for c in checkins if c.date == day]
        status = reconcile_day(day_checkins, village, day, at + timedelta(minutes=40), points)
        statuses.append(status)
        for point in status.points:
            reason = {"NO_SUPPLY": TicketReason.NO_SUPPLY, "DIRTY": TicketReason.DIRTY}.get(
                point.status.value
            )
            if reason:
                number = len(tickets) + 1
                tickets.append(
                    _ticket(number, point.water_point_id, reason, at, day, today, households, rng)
                )
    return {
        "village": village,
        "points": points,
        "operators": operators,
        "households": households,
        "checkins": checkins,
        "statuses": statuses,
        "tickets": tickets,
        "now": now,
    }


def _ticket(number, wpid, reason, at, day, today, households, rng):
    reporters = [h.id for h in households if h.water_point_id == wpid][:2]
    ticket = new_ticket(
        VID,
        reason,
        at + timedelta(minutes=45),
        ticket_id=f"tkt_sample_{number:03d}",
        water_point_id=wpid,
        origin=TicketOrigin.RECONCILE,
        reporters=reporters,
        quorum=2,
        number=number,
    )
    initial = ticket
    t = at + timedelta(minutes=46)
    steps = [(TicketEventKind.NOTIFIED, "system:ticket-flow", 1)]
    still_open = (today - day).days <= 1
    if not still_open:
        fix_h = rng.choice([6, 10, 14, 20, 28])
        steps += [
            (TicketEventKind.OPERATOR_FIXED, "operator:op-sample-njm", fix_h),
            (TicketEventKind.VERIFY_STARTED, "system:ticket-flow", 0.1),
            (TicketEventKind.VERIFIED_OK, "system:verify", 0.6),
        ]
    for kind, actor, hours in steps:
        t = t + timedelta(hours=hours)
        ticket = transition(ticket, kind, actor, t, {"sample": True})
    return initial, ticket


def main(argv: Sequence[str] | None = None) -> int:
    env = load_env()
    parser = argparse.ArgumentParser(description="Seed the labelled sample village.")
    parser.add_argument("--stage", default=env.get("STAGE"))
    parser.add_argument("--profile", default=env.get("AWS_PROFILE"))
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    today = datetime.now(IST).date()
    data = build(args.days, today, random.Random(11))
    closed = sum(final.state.value == "CLOSED_VERIFIED" for _, final in data["tickets"])
    print(
        f"sample village: {len(data['households'])} families, {len(data['statuses'])} days, "
        f"{len(data['tickets'])} complaints ({closed} closed after families confirmed)"
    )
    if args.dry_run:
        return 0
    import boto3

    from jalsakshi.store import Repository

    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    repo = Repository(
        f"jalsakshi-{args.stage}",
        region=REGION,
        client=session.client("dynamodb", region_name=REGION),
    )
    repo.put_village(data["village"])
    for p in data["points"]:
        repo.put_water_point(p)
    for o in data["operators"]:
        repo.put_operator(o)
    for h in data["households"]:
        repo.put_household(h)
    for c in data["checkins"]:
        repo.put_checkin(c)
    for s in data["statuses"]:
        repo.put_day_status(s)
    for initial, final in data["tickets"]:
        if repo.open_ticket_if_none(initial) is not None:
            repo.save_ticket(final, expected_updated_at=initial.updated_at)
    repo.next_ticket_number(VID)  # keep the counter past the sample complaints
    for _ in range(len(data["tickets"]) - 1):
        repo.next_ticket_number(VID)
    print("seeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
