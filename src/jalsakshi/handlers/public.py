"""Residents' view (ARCHITECTURE.md §15.11): ``GET /public/villages[/{vid}]``, no login.

Village-level facts only: the village and its codes, today's status per water point, the last
30 days, open complaints (number, problem, water point, age, state), repairs confirmed by
households, sent announcements, and the official record next to it. Never a name, a phone or a
single household's answer. Responses are cacheable for 60 seconds.
"""

from __future__ import annotations

import os
import statistics
from datetime import timedelta
from typing import Any, Final

from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response

from jalsakshi.core.clock import today_ist
from jalsakshi.core.models import BroadcastState, Ticket, TicketState, Village
from jalsakshi.core.tickets import TicketEventKind
from jalsakshi.data.official import load_official, official_age_note
from jalsakshi.handlers import config
from jalsakshi.handlers.common import dumps, entrypoint, install_error_handlers
from jalsakshi.store import Repository

DAYS: Final = 30
CACHE: Final = {"Cache-Control": "public, max-age=60"}

app = APIGatewayHttpResolver()
install_error_handlers(app)


@app.get("/public/villages")
def villages() -> Response:
    repo = config.repository()
    rows = [
        {"id": v.id, "name": v.name, "name_hi": v.name_hi, "lgd_code": v.lgd_code}
        for v in repo.list_villages()
        if v.active
    ]
    return _ok(rows)


@app.get("/public/villages/<village_id>")
def village(village_id: str) -> Response:
    repo = config.repository()
    found = repo.get_village(village_id)
    if found is None or not found.active:
        return Response(404, "application/json", dumps({"error": {"code": "not_found"}}))
    return _ok(public_view(repo, found))


def public_view(repo: Repository, village: Village) -> dict[str, Any]:
    """Everything a resident may see about their village (no personal data)."""
    now = config.now()
    today = today_ist(now)
    start = today - timedelta(days=DAYS - 1)
    points = repo.list_water_points(village.id)
    names = {p.id: p.name for p in points}
    names_hi = {p.id: p.name_hi for p in points}
    days = repo.list_day_statuses(village.id, start, today)
    tickets = repo.list_tickets(village_id=village.id)
    open_now = [t for t in tickets if t.state is not TicketState.CLOSED_VERIFIED]
    closed = [t for t in tickets if t.state is TicketState.CLOSED_VERIFIED]
    repair_hours = [h for h in (_repair_hours(t) for t in closed) if h is not None]
    official = load_official(village.lgd_code) if village.lgd_code else None
    households = repo.list_households(village.id, active_only=True)
    return {
        "village": {
            "id": village.id,
            "name": village.name,
            "name_hi": village.name_hi,
            "gram_panchayat": village.gram_panchayat,
            "block": village.block,
            "district": village.district,
            "lgd_code": village.lgd_code,
        },
        "generated_at": now.isoformat(),
        "water_points": [
            {"id": p.id, "name": p.name, "name_hi": p.name_hi, "kind": p.kind.value}
            for p in points
            if p.active
        ],
        "days": [
            {
                "date": d.date.isoformat(),
                "status": d.status.value,
                "points": [
                    {"water_point_id": p.water_point_id, "status": p.status.value} for p in d.points
                ],
                "answered": d.counts.answered,
            }
            for d in days
        ],
        "open_complaints": [
            {
                "number": t.number,
                "reason": t.reason.value,
                "water_point": names.get(t.water_point_id or ""),
                "water_point_hi": names_hi.get(t.water_point_id or ""),
                "state": t.state.value,
                "opened_at": t.opened_at.isoformat(),
                "age_hours": round((now - t.opened_at).total_seconds() / 3600, 1),
                "families": len(t.reporters),
            }
            for t in sorted(open_now, key=lambda t: t.opened_at)
        ],
        "repairs_confirmed": {
            "count": len(closed),
            "median_hours": round(statistics.median(repair_hours), 1) if repair_hours else None,
        },
        "announcements": [
            {"kind": b.kind.value, "text_hi": b.text_hi, "sent_at": b.sent_at.isoformat()}
            for b in repo.list_broadcasts(village.id)
            if b.state is BroadcastState.SENT and b.sent_at is not None
        ][:10],
        "families_reporting": len([h for h in households if h.consent_given]),
        "official": (
            {
                "households": official.households,
                "tap_connections": official.tap_connections,
                "hgj_status": official.hgj_status,
                "water_quality_note": official_age_note(official, now),
                "source": official.source.model_dump(mode="json"),
            }
            if official
            else None
        ),
        "sources": [
            "Families' answers by phone (JalSakshi): resident-reported, not a household census",
            "Government record: JJM IMIS / WQMIS public dashboard, as entered by the state",
        ],
        "missed_call_number": os.environ.get("JALSAKSHI_MISSED_CALL_NUMBER") or None,
    }


@entrypoint
def handler(event: Any, context: Any) -> Any:
    return app.resolve(event, context)


def _repair_hours(ticket: Ticket) -> float | None:
    closed_at = next((e.at for e in ticket.events if e.kind == TicketEventKind.VERIFIED_OK), None)
    if closed_at is None:
        return None
    return (closed_at - ticket.opened_at).total_seconds() / 3600


def _ok(body: Any) -> Response:
    return Response(200, "application/json", dumps(body), headers=CACHE)
