"""Builders and hypothesis strategies shared by the core tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from hypothesis import strategies as st

from jalsakshi.core.clock import IST
from jalsakshi.core.models import (
    CallOutcome,
    CheckIn,
    CleanAnswer,
    DayStatusValue,
    Purpose,
    Village,
    WaterAnswer,
)

DAY = date(2026, 10, 9)
T0 = datetime(2026, 10, 9, 10, 30, tzinfo=IST)
VILLAGE = Village(id="v1", name="Pathariya", block="Dhamdha", district="Durg", quorum=2)

# Worse statuses rank lower. UNVERIFIED is deliberately absent: it is not on the scale.
SEVERITY_RANK = {
    DayStatusValue.SUPPLIED: 3,
    DayStatusValue.PARTIAL: 2,
    DayStatusValue.DIRTY: 1,
    DayStatusValue.NO_SUPPLY: 0,
}


def checkin(
    household_id: str,
    water: WaterAnswer | None = None,
    *,
    clean: CleanAnswer | None = None,
    outcome: CallOutcome = CallOutcome.ANSWERED,
    attempt: int = 1,
    purpose: Purpose = Purpose.DAILY,
    village_id: str = "v1",
    day: date = DAY,
    captured_at: datetime | None = None,
) -> CheckIn:
    """Build one check-in with sensible defaults."""
    return CheckIn(
        village_id=village_id,
        date=day,
        household_id=household_id,
        attempt=attempt,
        call_id=f"call-{household_id}-{purpose}-{attempt}",
        purpose=purpose,
        outcome=outcome,
        water=water,
        clean=clean,
        captured_at=captured_at or T0 + timedelta(minutes=attempt),
    )


def answers(*waters: WaterAnswer, purpose: Purpose = Purpose.DAILY) -> list[CheckIn]:
    """One answered check-in per water answer, households h0, h1, ..."""
    return [checkin(f"h{i}", water, purpose=purpose) for i, water in enumerate(waters)]


def unreachable(*household_ids: str, purpose: Purpose = Purpose.DAILY) -> list[CheckIn]:
    """UNREACHABLE check-ins for the given households."""
    return [checkin(hid, outcome=CallOutcome.UNREACHABLE, purpose=purpose) for hid in household_ids]


HOUSEHOLDS = [f"h{i}" for i in range(8)]
ANY_HOUSEHOLD = st.sampled_from(HOUSEHOLDS)
ANY_PURPOSE = st.sampled_from([Purpose.DAILY, Purpose.VERIFY])
ANY_OUTCOME = st.sampled_from(list(CallOutcome))
NOT_ANSWERED = st.sampled_from([CallOutcome.UNREACHABLE, CallOutcome.DECLINED])
ANY_CLEAN = st.none() | st.sampled_from(list(CleanAnswer))


@st.composite
def checkins(
    draw: st.DrawFn,
    *,
    household_ids: st.SearchStrategy[str] = ANY_HOUSEHOLD,
    purposes: st.SearchStrategy[Purpose] = ANY_PURPOSE,
    outcomes: st.SearchStrategy[CallOutcome] = ANY_OUTCOME,
) -> CheckIn:
    """Any check-in for village v1 on DAY. Water/clean are drawn even for unanswered calls."""
    return CheckIn(
        village_id="v1",
        date=DAY,
        household_id=draw(household_ids),
        attempt=draw(st.integers(min_value=1, max_value=3)),
        call_id=f"call-{draw(st.integers(min_value=0, max_value=50))}",
        purpose=draw(purposes),
        outcome=draw(outcomes),
        water=draw(st.none() | st.sampled_from(list(WaterAnswer))),
        clean=draw(ANY_CLEAN),
        captured_at=T0 + timedelta(minutes=draw(st.integers(min_value=0, max_value=600))),
    )
