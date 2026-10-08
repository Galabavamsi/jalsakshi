"""Fixtures for the agent tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from agent_fakes import NOW, make_ticket

from jalsakshi.agent.evidence import BriefInput
from jalsakshi.core.models import Freshness, SourceTag, TicketReason, Village


@pytest.fixture
def brief_input() -> BriefInput:
    """A week in one village: 7 observed days, one verified repair (26.5 h), one open ticket."""
    claimed = SourceTag(
        source="JJM IMIS Har Ghar Jal report",
        observed_at=datetime(2026, 9, 30, tzinfo=UTC),
        fetched_at=NOW,
        freshness=Freshness.DAILY,
        url="https://ejalshakti.gov.in/jjmreport/JJMIndia.aspx?state=22",
    )
    village = Village(
        id="v-kumhari",
        name="Kumhari",
        block="Patan",
        district="Durg",
        imis_village_code="438211",
        claimed_hgj=True,
        hgj_certified=False,
        claimed_source=claimed,
    )
    tickets = [
        make_ticket(
            "TKT-0001",
            datetime(2026, 10, 2, 5, 0, tzinfo=UTC),
            closed=datetime(2026, 10, 3, 7, 30, tzinfo=UTC),
        ),
        make_ticket("TKT-0002", datetime(2026, 10, 6, 5, 0, tzinfo=UTC), reason=TicketReason.DIRTY),
    ]
    checkins = SourceTag(
        source="JalSakshi household check-ins",
        observed_at=datetime(2026, 10, 7, 5, 0, tzinfo=UTC),
        fetched_at=NOW,
        freshness=Freshness.SIMULATED,
    )
    return BriefInput(
        village=village,
        period_from=date(2026, 10, 1),
        period_to=date(2026, 10, 7),
        summary={
            "days": 7,
            "supplied": 3,
            "no_supply": 2,
            "partial": 1,
            "dirty": 1,
            "unverified": 0,
            "tickets_opened": 2,
            "tickets_closed_verified": 1,
            "median_hours_to_verified_fix": 26.5,
        },
        tickets=tickets,
        sources=[checkins],
    )
