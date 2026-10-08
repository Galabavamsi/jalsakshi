"""Repository behaviour against a moto DynamoDB table."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from botocore.exceptions import ClientError

from jalsakshi.core.models import (
    DayStatusValue,
    OperatorRole,
    Purpose,
    TicketState,
    WaterAnswer,
)
from jalsakshi.store import (
    ConflictError,
    NotFoundError,
    Repository,
    StoreError,
)
from jalsakshi.store import repo as repo_module

from .factories import (
    DAY,
    IST,
    NOW,
    TABLE,
    Clock,
    advance,
    checkin,
    day_status,
    household,
    operator,
    ticket,
    village,
)

LATER = NOW + timedelta(minutes=5)


class ClientProxy:
    """Wraps a real client so a test can override single operations."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _cancelled(*codes: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": "TransactionCanceledException", "Message": "Transaction cancelled"},
            "CancellationReasons": [{"Code": code} for code in codes],
        },
        "TransactWriteItems",
    )


def _count(ddb: Any, pk: str, prefix: str) -> int:
    response = ddb.query(
        TableName=TABLE,
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
        ExpressionAttributeValues={":pk": {"S": pk}, ":sk": {"S": prefix}},
    )
    return int(response["Count"])


# --- construction ---------------------------------------------------------------------------------


def test_region_defaults_to_mumbai(aws_env: None) -> None:
    repo = Repository(TABLE)
    assert repo.region == "ap-south-1"
    assert repo._client.meta.region_name == "ap-south-1"


def test_region_comes_from_env_unless_given(aws_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JALSAKSHI_REGION", "ap-south-2")
    assert Repository(TABLE).region == "ap-south-2"
    assert Repository(TABLE, region="ap-south-1").region == "ap-south-1"


def test_from_env_reads_table_name(aws_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(StoreError):
        Repository.from_env()
    monkeypatch.setenv("JALSAKSHI_TABLE", "jalsakshi-dev-varun")
    assert Repository.from_env().table_name == "jalsakshi-dev-varun"


# --- villages and households ----------------------------------------------------------------------


def test_village_put_get_list(repo: Repository) -> None:
    v2, v1 = village("v2", name="Kodiya"), village("v1")
    repo.put_village(v2)
    repo.put_village(v1)
    assert repo.get_village("v1") == v1
    assert repo.get_village("missing") is None
    assert repo.list_villages() == [v1, v2]
    renamed = v1.model_copy(update={"name": "Renamed", "quorum": 3})
    repo.put_village(renamed)
    assert repo.get_village("v1") == renamed
    assert len(repo.list_villages()) == 2


def test_households_are_scoped_to_their_village(repo: Repository) -> None:
    h1, h2 = household("h1"), household("h2", active=False, consent=None)
    for hh in (h2, h1, household("h9", vid="v2")):
        repo.put_household(hh)
    repo.put_village(village("v1"))
    repo.put_checkin(checkin("h1"))
    assert repo.list_households("v1") == [h1, h2]
    assert repo.list_households("v1", active_only=True) == [h1]
    assert repo.get_household("v1", "h1") == h1
    assert repo.get_household("v1", "h9") is None
    assert repo.get_household("v1", "h1").consent_given  # type: ignore[union-attr]


# --- operators ------------------------------------------------------------------------------------


def test_operator_listing_follows_village_ids(repo: Repository) -> None:
    op = operator("op1", ("v1", "v2", "v1"))
    repo.put_operator(op)
    repo.put_operator(operator("op2", ("v1",), role=OperatorRole.SARPANCH))
    assert repo.get_operator("op1") == op
    assert repo.get_operator("nobody") is None
    assert [o.id for o in repo.list_operators_for_village("v1")] == ["op1", "op2"]
    assert repo.list_operators_for_village("v2") == [op]

    moved = operator("op1", ("v2", "v3"))
    repo.put_operator(moved)
    assert [o.id for o in repo.list_operators_for_village("v1")] == ["op2"]
    assert repo.list_operators_for_village("v2") == [moved]
    assert repo.list_operators_for_village("v3") == [moved]


def test_operator_listing_ignores_open_ticket_guard(repo: Repository) -> None:
    repo.put_operator(operator())
    repo.open_ticket_if_none(ticket())
    assert [o.id for o in repo.list_operators_for_village("v1")] == ["op1"]


def test_batch_write_retries_unprocessed_items(
    ddb: Any, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repo_module.time, "sleep", lambda _s: None)

    class Unprocessed(ClientProxy):
        left = 1

        def batch_write_item(self, RequestItems: Any) -> Any:
            if self.left:
                self.left -= 1
                return {"UnprocessedItems": RequestItems}
            return self._inner.batch_write_item(RequestItems=RequestItems)

    Repository(TABLE, client=Unprocessed(ddb), clock=clock).put_operator(operator())
    assert Repository(TABLE, client=ddb).get_operator("op1") == operator()

    stuck = Unprocessed(ddb)
    stuck.left = 99
    with pytest.raises(StoreError):
        Repository(TABLE, client=stuck, clock=clock).put_operator(operator("op9"))


# --- check-ins and day status ---------------------------------------------------------------------


def test_put_checkin_is_idempotent(repo: Repository) -> None:
    first = checkin("h1", water=WaterAnswer.NO)
    assert repo.put_checkin(first) is True
    assert repo.put_checkin(first.model_copy(update={"water": WaterAnswer.YES})) is False
    assert repo.list_checkins("v1", DAY) == [first]


def test_list_checkins_filters_by_day_and_purpose(repo: Repository) -> None:
    daily = [checkin("h1"), checkin("h1", attempt=2), checkin("h2")]
    verify = checkin("h1", purpose=Purpose.VERIFY)
    for item in [*daily, verify, checkin("h1", day=DAY + timedelta(days=1))]:
        assert repo.put_checkin(item)
    assert repo.list_checkins("v1", DAY, Purpose.DAILY) == daily
    assert repo.list_checkins("v1", DAY, Purpose.VERIFY) == [verify]
    assert len(repo.list_checkins("v1", DAY)) == 4
    assert repo.list_checkins("v2", DAY) == []


def test_day_status_put_get_and_range(repo: Repository) -> None:
    days = [date(2026, 10, d) for d in (6, 7, 8, 9)]
    for d in days:
        repo.put_day_status(day_status(d))
    recomputed = day_status(days[-1], status=DayStatusValue.NO_SUPPLY)
    repo.put_day_status(recomputed)
    assert repo.get_day_status("v1", days[-1]) == recomputed
    assert repo.get_day_status("v1", date(2026, 10, 1)) is None
    window = repo.list_day_statuses("v1", days[1], days[3])
    assert [s.date for s in window] == days[1:]
    assert window[-1].status is DayStatusValue.NO_SUPPLY
    assert repo.list_day_statuses("v1", days[3], days[0]) == []


# --- tickets: opening -----------------------------------------------------------------------------


def test_open_ticket_stores_ticket_pointer_and_events(repo: Repository, ddb: Any) -> None:
    tk = ticket()
    assert repo.open_ticket_if_none(tk) == tk
    assert repo.get_ticket("v1", "t1") == tk
    assert repo.get_ticket_by_id("t1") == tk
    assert repo.get_ticket_by_id("nope") is None
    assert repo.get_open_ticket("v1") == tk
    assert repo.list_ticket_events("t1") == tk.events
    assert _count(ddb, "TKT#t1", "EVT#") == 1


def test_only_one_open_ticket_per_village(repo: Repository) -> None:
    assert repo.open_ticket_if_none(ticket("t1"))
    assert repo.open_ticket_if_none(ticket("t2", opened_at=LATER)) is None
    assert repo.open_ticket_if_none(ticket("t3", vid="v2")) is not None
    assert repo.get_ticket("v1", "t2") is None
    assert repo.get_ticket_by_id("t2") is None
    assert [tk.id for tk in repo.list_tickets(village_id="v1")] == ["t1"]


def test_open_ticket_replay_returns_stored_ticket(repo: Repository) -> None:
    tk = ticket()
    repo.open_ticket_if_none(tk)
    assigned = advance(tk, TicketState.ASSIGNED, LATER)
    repo.save_ticket(assigned, tk.updated_at)
    assert repo.open_ticket_if_none(tk) == assigned


def test_open_ticket_rejects_closed_ticket(repo: Repository) -> None:
    closed = advance(ticket(), TicketState.CLOSED_VERIFIED, LATER)
    with pytest.raises(ValueError):
        repo.open_ticket_if_none(closed)


def test_open_ticket_rejects_reused_id_after_close(repo: Repository) -> None:
    tk = ticket()
    repo.open_ticket_if_none(tk)
    repo.save_ticket(advance(tk, TicketState.CLOSED_VERIFIED, LATER), tk.updated_at)
    with pytest.raises(StoreError):
        repo.open_ticket_if_none(tk)


def test_open_ticket_retries_transaction_conflicts(ddb: Any, clock: Clock) -> None:
    class Flaky(ClientProxy):
        failures = 1

        def transact_write_items(self, **kwargs: Any) -> Any:
            if self.failures:
                self.failures -= 1
                raise _cancelled("TransactionConflict", "None", "None", "None")
            return self._inner.transact_write_items(**kwargs)

    assert Repository(TABLE, client=Flaky(ddb), clock=clock).open_ticket_if_none(ticket())
    always = Flaky(ddb)
    always.failures = 99
    with pytest.raises(ConflictError):
        Repository(TABLE, client=always, clock=clock).open_ticket_if_none(ticket("t2", vid="v2"))


def test_unexpected_client_errors_propagate(ddb: Any, clock: Clock) -> None:
    class Broken(ClientProxy):
        def transact_write_items(self, **kwargs: Any) -> Any:
            raise ClientError({"Error": {"Code": "ValidationException"}}, "TransactWriteItems")

    with pytest.raises(ClientError):
        Repository(TABLE, client=Broken(ddb), clock=clock).open_ticket_if_none(ticket())


# --- tickets: saving ------------------------------------------------------------------------------


def test_save_ticket_appends_only_new_events(repo: Repository, ddb: Any) -> None:
    tk = ticket()
    repo.open_ticket_if_none(tk)
    assigned = advance(tk, TicketState.ASSIGNED, LATER)
    assert repo.save_ticket(assigned, tk.updated_at) == assigned
    fixed = advance(assigned, TicketState.OPERATOR_REPORTED_FIXED, LATER + timedelta(hours=1))
    verifying = advance(fixed, TicketState.VERIFYING, fixed.updated_at + timedelta(microseconds=1))
    repo.save_ticket(verifying, assigned.updated_at)
    assert repo.get_ticket("v1", "t1") == verifying
    assert repo.list_ticket_events("t1") == verifying.events
    assert _count(ddb, "TKT#t1", "EVT#") == 4


def test_save_ticket_keeps_same_instant_events_distinct(repo: Repository) -> None:
    tk = ticket()
    repo.open_ticket_if_none(tk)
    fixed = advance(tk, TicketState.OPERATOR_REPORTED_FIXED, LATER)
    verifying = advance(fixed, TicketState.VERIFYING, LATER)
    verifying = verifying.model_copy(update={"updated_at": LATER + timedelta(microseconds=1)})
    repo.save_ticket(verifying, tk.updated_at)
    assert [e.to_state for e in repo.list_ticket_events("t1")] == [
        TicketState.OPEN,
        TicketState.OPERATOR_REPORTED_FIXED,
        TicketState.VERIFYING,
    ]


def test_save_ticket_rejects_stale_copy(repo: Repository) -> None:
    tk = ticket()
    repo.open_ticket_if_none(tk)
    repo.save_ticket(advance(tk, TicketState.ASSIGNED, LATER), tk.updated_at)
    late = advance(tk, TicketState.ESCALATED, LATER + timedelta(minutes=1))
    with pytest.raises(ConflictError):
        repo.save_ticket(late, tk.updated_at)
    assert repo.get_ticket("v1", "t1").state is TicketState.ASSIGNED  # type: ignore[union-attr]


def test_save_ticket_detects_write_between_read_and_commit(ddb: Any, clock: Clock) -> None:
    rival_repo = Repository(TABLE, client=ddb, clock=clock)
    tk = ticket()
    rival_repo.open_ticket_if_none(tk)
    rival = advance(tk, TicketState.ASSIGNED, LATER)

    class Racing(ClientProxy):
        def transact_write_items(self, **kwargs: Any) -> Any:
            rival_repo.save_ticket(rival, tk.updated_at)
            return self._inner.transact_write_items(**kwargs)

    mine = advance(tk, TicketState.ESCALATED, LATER + timedelta(minutes=1))
    with pytest.raises(ConflictError):
        Repository(TABLE, client=Racing(ddb), clock=clock).save_ticket(mine, tk.updated_at)
    assert rival_repo.get_ticket("v1", "t1") == rival
    assert rival_repo.list_ticket_events("t1") == rival.events


def test_save_ticket_validates_input(repo: Repository) -> None:
    tk = ticket()
    with pytest.raises(NotFoundError):
        repo.save_ticket(advance(tk, TicketState.ASSIGNED, LATER), tk.updated_at)
    repo.open_ticket_if_none(tk)
    with pytest.raises(ValueError, match="updated_at"):
        repo.save_ticket(tk, tk.updated_at)
    truncated = tk.model_copy(update={"events": [], "updated_at": LATER})
    with pytest.raises(ValueError, match="append-only"):
        repo.save_ticket(truncated, tk.updated_at)


def test_expected_updated_at_is_compared_as_an_instant(repo: Repository) -> None:
    tk = ticket()
    repo.open_ticket_if_none(tk)
    same_instant_in_ist = tk.updated_at.astimezone(IST)
    saved = repo.save_ticket(advance(tk, TicketState.ASSIGNED, LATER), same_instant_in_ist)
    assert saved.state is TicketState.ASSIGNED


def test_closing_verified_releases_guard(repo: Repository) -> None:
    tk = ticket()
    repo.open_ticket_if_none(tk)
    closed = advance(tk, TicketState.CLOSED_VERIFIED, LATER)
    repo.save_ticket(closed, tk.updated_at)
    assert repo.get_open_ticket("v1") is None
    nxt = ticket("t2", opened_at=LATER + timedelta(days=1))
    assert repo.open_ticket_if_none(nxt) == nxt
    assert repo.get_open_ticket("v1") == nxt

    # Re-saving the old closed ticket must not release the new ticket's guard.
    note = closed.model_copy(update={"updated_at": LATER + timedelta(days=2)})
    repo.save_ticket(note, closed.updated_at)
    assert repo.get_open_ticket("v1") == nxt


def test_reopened_ticket_keeps_guard(repo: Repository) -> None:
    tk = ticket()
    repo.open_ticket_if_none(tk)
    reopened = advance(tk, TicketState.REOPENED, LATER)
    repo.save_ticket(reopened, tk.updated_at)
    assert repo.get_open_ticket("v1") == reopened
    assert repo.open_ticket_if_none(ticket("t2", opened_at=LATER)) is None


def test_list_tickets_by_state_and_village(repo: Repository) -> None:
    a = ticket("a", vid="v1", opened_at=NOW)
    b = ticket("b", vid="v2", opened_at=NOW + timedelta(hours=1))
    c = ticket("c", vid="v3", opened_at=NOW + timedelta(hours=2))
    for tk in (a, b, c):
        repo.open_ticket_if_none(tk)
    b2 = advance(b, TicketState.ASSIGNED, LATER + timedelta(hours=1))
    repo.save_ticket(b2, b.updated_at)

    assert [tk.id for tk in repo.list_tickets()] == ["c", "b", "a"]
    assert [tk.id for tk in repo.list_tickets(state=TicketState.OPEN)] == ["c", "a"]
    assert repo.list_tickets(state=TicketState.ASSIGNED) == [b2]
    assert repo.list_tickets(state=TicketState.OPEN, village_id="v1") == [a]
    assert repo.list_tickets(state=TicketState.ASSIGNED, village_id="v1") == []
    assert repo.list_tickets(village_id="v2") == [b2]
    assert repo.list_tickets(state=TicketState.CLOSED_VERIFIED) == []


# --- call sessions --------------------------------------------------------------------------------


def test_call_session_round_trip(repo: Repository) -> None:
    assert repo.get_call_session("c1") is None
    data = {"household_id": "h1", "purpose": "DAILY", "score": 0.5, "nested": {"n": [1, 2]}}
    repo.put_call_session("c1", data)
    session = repo.get_call_session("c1")
    assert session is not None
    assert session.data == data
    assert session.steps == {} and session.last_step is None and session.task_token is None
    assert session.created_at == NOW
    assert session.expires_at == NOW + timedelta(days=2)


def test_record_call_step_is_idempotent(repo: Repository, clock: Clock) -> None:
    repo.put_call_session("c1", {"household_id": "h1"})
    assert repo.record_call_step("c1", "Q_WATER", {"digits": "2"}) is True
    clock.advance(seconds=5)
    assert repo.record_call_step("c1", "Q_CLEAN", {"digits": "1"}) is True
    assert repo.record_call_step("c1", "Q_WATER", {"digits": "1"}) is False
    session = repo.get_call_session("c1")
    assert session is not None
    assert session.steps == {"Q_WATER": {"digits": "2"}, "Q_CLEAN": {"digits": "1"}}
    assert list(session.steps) == ["Q_WATER", "Q_CLEAN"]
    assert session.last_step == "Q_CLEAN"


def test_task_token_and_data_updates_preserve_each_other(repo: Repository, clock: Clock) -> None:
    repo.set_task_token("c1", "token-abc")
    early = repo.get_call_session("c1")
    assert early is not None and early.task_token == "token-abc" and early.data == {}
    repo.record_call_step("c1", "GREET")
    clock.advance(minutes=1)
    repo.put_call_session("c1", {"household_id": "h1"}, ttl_days=1)
    session = repo.get_call_session("c1")
    assert session is not None
    assert session.task_token == "token-abc"
    assert session.steps == {"GREET": {}}
    assert session.data == {"household_id": "h1"}
    assert session.created_at == NOW
    assert session.updated_at == NOW + timedelta(minutes=1)
    assert session.expires_at == NOW + timedelta(days=1, minutes=1)


def test_expired_call_session_is_hidden(repo: Repository, clock: Clock) -> None:
    repo.put_call_session("c1", {"household_id": "h1"})
    repo.record_call_step("c1", "GREET")
    clock.advance(days=2, seconds=1)
    assert repo.get_call_session("c1") is None


# --- activity feed --------------------------------------------------------------------------------


def test_activity_feed_since_is_exclusive_and_chronological(repo: Repository) -> None:
    yesterday_late = datetime(2026, 10, 8, 23, 30, tzinfo=UTC)
    entries = [
        repo.put_activity("ticket_opened", "v1", "Ticket opened", "शिकायत खुली", at=yesterday_late),
        repo.put_activity("call", "v1", "Called h1", "h1 को कॉल", at=NOW - timedelta(hours=1)),
        repo.put_activity("system", None, "Scheduler ran", "शेड्यूलर चला"),
    ]
    since = datetime(2026, 10, 8, tzinfo=UTC)
    assert repo.list_activity(since) == entries
    assert repo.list_activity(entries[0].at) == entries[1:]
    assert repo.list_activity(entries[0].at.astimezone(IST)) == entries[1:]
    assert repo.list_activity(since, limit=2) == entries[1:]
    assert repo.list_activity(since, limit=0) == []
    assert repo.list_activity(NOW) == []
    assert entries[2].at == NOW and entries[2].village_id is None


def test_activity_feed_looks_back_a_bounded_number_of_days(repo: Repository) -> None:
    old = repo.put_activity("call", "v1", "old", "पुराना", at=NOW - timedelta(days=10))
    recent = repo.put_activity("call", "v1", "recent", "नया", at=NOW - timedelta(days=6))
    feed = repo.list_activity(old.at - timedelta(seconds=1))
    assert feed == [recent]
