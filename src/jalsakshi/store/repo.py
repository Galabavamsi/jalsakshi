"""DynamoDB single-table repository (docs/ARCHITECTURE.md section 8).

Base-table reads are strongly consistent; GSI1 reads (village list, tickets by state) are
eventually consistent, as DynamoDB requires. Every client call names the region explicitly:
`region` argument, else $JALSAKSHI_REGION, else ap-south-1.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel

from jalsakshi.core.models import (
    CheckIn,
    DayStatus,
    Household,
    Operator,
    Purpose,
    Ticket,
    TicketEvent,
    TicketState,
    Village,
)
from jalsakshi.store import table as t
from jalsakshi.store.errors import ConflictError, NotFoundError, StoreError
from jalsakshi.store.records import ActivityEntry, CallSession

logger = logging.getLogger(__name__)

REGION_ENV: Final = "JALSAKSHI_REGION"
DEFAULT_REGION: Final = "ap-south-1"
TABLE_ENV: Final = "JALSAKSHI_TABLE"
CALL_TTL_DAYS: Final = 2
ACTIVITY_TTL_DAYS: Final = 30
ACTIVITY_LOOKBACK_DAYS: Final = 7
MAX_TRANSACT_ITEMS: Final = 100

_BATCH_SIZE: Final = 25
_BATCH_RETRIES: Final = 5
_OPEN_RETRIES: Final = 3
_ABSENT: Final = "attribute_not_exists(PK)"
_CONDITION_FAILED: Final = "ConditionalCheckFailed"
_TX_CONFLICT: Final = "TransactionConflict"
_AFTER_ANY_UID: Final = "#~"  # sorts after "#<hex uid>", so `since` itself is excluded

DynamoClient = Any  # botocore DynamoDB client; typed stubs are not a project dependency


class _Cancelled(Exception):
    """A TransactWriteItems call was cancelled; `codes` align with the submitted items."""

    def __init__(self, codes: list[str]) -> None:
        super().__init__(", ".join(codes) or "transaction cancelled")
        self.codes = codes

    @property
    def is_conflict(self) -> bool:
        """True when a condition failed or a concurrent write interfered (or no reasons)."""
        return not self.codes or any(c in (_CONDITION_FAILED, _TX_CONFLICT) for c in self.codes)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def _expiry(now: datetime, days: int) -> int:
    """Epoch seconds `days` after `now`, for the DynamoDB TTL attribute."""
    return int((_aware(now) + timedelta(days=days)).timestamp())


def _error_code(err: ClientError) -> str:
    return str(err.response.get("Error", {}).get("Code", ""))


def _cancellation_codes(err: ClientError) -> list[str]:
    """Per-item reason codes of a cancelled transaction (parsed from the message as fallback)."""
    reasons = err.response.get("CancellationReasons")
    if reasons:
        return [str(reason.get("Code", "None")) for reason in reasons]
    message = str(err.response.get("Error", {}).get("Message", ""))
    match = re.search(r"\[([^\]]*)\]", message)
    return [code.strip() for code in match.group(1).split(",")] if match else []


class Repository:
    """Typed reads and writes for the JalSakshi single table."""

    def __init__(
        self,
        table_name: str,
        region: str | None = None,
        client: DynamoClient | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.table_name = table_name
        self.region = region or os.environ.get(REGION_ENV) or DEFAULT_REGION
        self._client = client if client is not None else self._new_client(self.region)
        self._clock = clock or _utcnow

    @staticmethod
    def _new_client(region: str) -> DynamoClient:
        return boto3.client("dynamodb", region_name=region)

    @classmethod
    def from_env(cls, client: DynamoClient | None = None) -> Repository:
        """Repository for the table named by $JALSAKSHI_TABLE (set by infra on each Lambda)."""
        name = os.environ.get(TABLE_ENV, "").strip()
        if not name:
            raise StoreError(f"environment variable {TABLE_ENV} is not set")
        return cls(name, client=client)

    # --- villages ---------------------------------------------------------------------------------

    def put_village(self, village: Village) -> None:
        """Create or replace a village (also indexed on GSI1 for listing)."""
        keys = {
            t.PK: t.village_pk(village.id),
            t.SK: t.META_SK,
            t.GSI1PK: t.VILLAGES_GSI_PK,
            t.GSI1SK: village.id,
        }
        self._put_item(t.model_to_item(village, keys, "Village"))

    def get_village(self, village_id: str) -> Village | None:
        """One village, or None."""
        item = self._get_item(t.village_pk(village_id), t.META_SK)
        return None if item is None else t.item_to_model(item, Village)

    def list_villages(self) -> list[Village]:
        """All villages, ordered by id."""
        items = self._query(t.VILLAGES_GSI_PK, index=t.GSI1)
        return [t.item_to_model(item, Village) for item in items]

    # --- households -------------------------------------------------------------------------------

    def put_household(self, household: Household) -> None:
        """Create or replace a household under its village."""
        keys = {t.PK: t.village_pk(household.village_id), t.SK: t.hh_sk(household.id)}
        self._put_item(t.model_to_item(household, keys, "Household"))

    def get_household(self, village_id: str, household_id: str) -> Household | None:
        """One household, or None."""
        item = self._get_item(t.village_pk(village_id), t.hh_sk(household_id))
        return None if item is None else t.item_to_model(item, Household)

    def list_households(self, village_id: str, *, active_only: bool = False) -> list[Household]:
        """Households of a village, ordered by id."""
        items = self._query(t.village_pk(village_id), sk_prefix=t.HH_PREFIX)
        households = [t.item_to_model(item, Household) for item in items]
        return [h for h in households if h.active] if active_only else households

    # --- operators --------------------------------------------------------------------------------

    def put_operator(self, operator: Operator) -> None:
        """Create or replace an operator and its per-village listing copies (stale ones removed)."""
        previous = self.get_operator(operator.id)
        villages = list(dict.fromkeys(operator.village_ids))
        before = dict.fromkeys(previous.village_ids) if previous else {}
        dropped = [vid for vid in before if vid not in villages]
        meta_keys = {t.PK: t.op_pk(operator.id), t.SK: t.META_SK}
        requests: list[dict[str, Any]] = [self._put_request(operator, meta_keys, "Operator")]
        for vid in villages:
            link_keys = {t.PK: t.village_pk(vid), t.SK: t.op_link_sk(operator.id)}
            requests.append(self._put_request(operator, link_keys, "OperatorLink"))
        for vid in dropped:
            key = {t.PK: t.village_pk(vid), t.SK: t.op_link_sk(operator.id)}
            requests.append({"DeleteRequest": {"Key": t.marshal(key)}})
        self._batch_write(requests)

    def get_operator(self, operator_id: str) -> Operator | None:
        """One operator, or None."""
        item = self._get_item(t.op_pk(operator_id), t.META_SK)
        return None if item is None else t.item_to_model(item, Operator)

    def list_operators_for_village(self, village_id: str) -> list[Operator]:
        """Operators serving a village, ordered by id."""
        items = self._query(t.village_pk(village_id), sk_prefix=t.OP_PREFIX)
        return [t.item_to_model(item, Operator) for item in items]

    # --- check-ins and day status -----------------------------------------------------------------

    def put_checkin(self, checkin: CheckIn) -> bool:
        """Store a check-in once. False when that (date, purpose, household, attempt) exists."""
        sk = t.chk_sk(checkin.date, checkin.purpose, checkin.household_id, checkin.attempt)
        keys = {t.PK: t.village_pk(checkin.village_id), t.SK: sk}
        return self._put_if_absent(t.model_to_item(checkin, keys, "CheckIn"))

    def list_checkins(
        self, village_id: str, day: date, purpose: Purpose | None = None
    ) -> list[CheckIn]:
        """Every attempt for a village and day; `purpose=None` returns all purposes."""
        items = self._query(t.village_pk(village_id), sk_prefix=t.chk_prefix(day, purpose))
        return [t.item_to_model(item, CheckIn) for item in items]

    def put_day_status(self, status: DayStatus) -> None:
        """Create or replace the reconciled status of one village-day."""
        keys = {t.PK: t.village_pk(status.village_id), t.SK: t.day_sk(status.date)}
        self._put_item(t.model_to_item(status, keys, "DayStatus"))

    def get_day_status(self, village_id: str, day: date) -> DayStatus | None:
        """One day status, or None."""
        item = self._get_item(t.village_pk(village_id), t.day_sk(day))
        return None if item is None else t.item_to_model(item, DayStatus)

    def list_day_statuses(self, village_id: str, start: date, end: date) -> list[DayStatus]:
        """Day statuses from `start` to `end` inclusive, oldest first."""
        if end < start:
            return []
        bounds = (t.day_sk(start), t.day_sk(end))
        items = self._query(t.village_pk(village_id), sk_between=bounds)
        return [t.item_to_model(item, DayStatus) for item in items]

    # --- tickets ----------------------------------------------------------------------------------

    def open_ticket_if_none(self, ticket: Ticket) -> Ticket | None:
        """Atomically open `ticket` unless its village already has an open ticket.

        Returns the stored ticket, or None when another ticket is open. Replaying the same
        ticket id (a retried Lambda) returns the stored ticket, so retries are safe.
        """
        if ticket.state is TicketState.CLOSED_VERIFIED:
            raise ValueError("cannot open a ticket that is already CLOSED_VERIFIED")
        vpk = t.village_pk(ticket.village_id)
        guard = {
            t.PK: vpk,
            t.SK: t.OPEN_TICKET_SK,
            "ticket_id": ticket.id,
            "opened_at": t.iso_ts(ticket.opened_at),
            t.ENTITY_ATTR: "OpenTicketGuard",
        }
        pointer = {
            t.PK: t.tkt_pk(ticket.id),
            t.SK: t.META_SK,
            "ticket_id": ticket.id,
            "village_id": ticket.village_id,
            t.ENTITY_ATTR: "TicketPointer",
        }
        ops = [
            self._tx_put(guard, _ABSENT),
            self._tx_put(self._ticket_item(ticket), _ABSENT),
            self._tx_put(pointer, _ABSENT),
            *self._event_ops(ticket, start=0),
        ]
        for _ in range(_OPEN_RETRIES):
            try:
                self._transact(ops)
            except _Cancelled as exc:
                holder = self._get_item(vpk, t.OPEN_TICKET_SK)
                if holder is not None:
                    if holder.get("ticket_id") == ticket.id:
                        return self.get_ticket(ticket.village_id, ticket.id)
                    logger.info("village %s already has open ticket", ticket.village_id)
                    return None
                if _TX_CONFLICT not in exc.codes:
                    raise StoreError(f"ticket id {ticket.id!r} already exists") from exc
                continue
            return ticket
        raise ConflictError(f"could not open a ticket for village {ticket.village_id!r}")

    def get_open_ticket(self, village_id: str) -> Ticket | None:
        """The village's open (not yet CLOSED_VERIFIED) ticket, or None."""
        holder = self._get_item(t.village_pk(village_id), t.OPEN_TICKET_SK)
        return None if holder is None else self.get_ticket(village_id, str(holder["ticket_id"]))

    def get_ticket(self, village_id: str, ticket_id: str) -> Ticket | None:
        """One ticket with its events, or None."""
        item = self._get_item(t.village_pk(village_id), t.tkt_sk(ticket_id))
        return None if item is None else t.item_to_model(item, Ticket)

    def get_ticket_by_id(self, ticket_id: str) -> Ticket | None:
        """One ticket found through its `TKT#{tid}/META` pointer, or None."""
        pointer = self._get_item(t.tkt_pk(ticket_id), t.META_SK)
        return None if pointer is None else self.get_ticket(str(pointer["village_id"]), ticket_id)

    def list_tickets(
        self, state: TicketState | None = None, village_id: str | None = None
    ) -> list[Ticket]:
        """Tickets newest first (by opened_at), optionally filtered by state and/or village."""
        if state is None and village_id is not None:
            items = self._query(t.village_pk(village_id), sk_prefix=t.TKT_PREFIX)
        else:
            states = list(TicketState) if state is None else [TicketState(state)]
            where = None if village_id is None else {"village_id": village_id}
            items = [
                item
                for s in states
                for item in self._query(t.ticket_state_gsi_pk(s), index=t.GSI1, where=where)
            ]
        tickets = [t.item_to_model(item, Ticket) for item in items]
        return sorted(tickets, key=lambda tk: t.iso_ts(tk.opened_at), reverse=True)

    def list_ticket_events(self, ticket_id: str) -> list[TicketEvent]:
        """The ticket's append-only audit trail (`EVT#` items), oldest first."""
        items = self._query(t.tkt_pk(ticket_id), sk_prefix=t.EVT_PREFIX)
        return [t.item_to_model(item, TicketEvent) for item in items]

    def save_ticket(self, ticket: Ticket, expected_updated_at: datetime) -> Ticket:
        """Save `ticket` if the stored copy still has `expected_updated_at` (optimistic lock).

        The caller must bump `ticket.updated_at`. Events beyond the stored ones are appended as
        `EVT#` items, and reaching CLOSED_VERIFIED releases the village's open-ticket guard.
        Raises ConflictError when the stored ticket changed, NotFoundError when it is missing.
        """
        expected = t.iso_ts(expected_updated_at)
        if t.iso_ts(ticket.updated_at) == expected:
            raise ValueError("ticket.updated_at must change on every save")
        vpk = t.village_pk(ticket.village_id)
        current_item = self._get_item(vpk, t.tkt_sk(ticket.id))
        if current_item is None:
            raise NotFoundError(f"ticket {ticket.id!r} not found in village {ticket.village_id!r}")
        if current_item.get(t.VERSION_ATTR) != expected:
            raise ConflictError(f"ticket {ticket.id!r} was changed by someone else")
        current = t.item_to_model(current_item, Ticket)
        if len(ticket.events) < len(current.events):
            raise ValueError("ticket events are append-only")
        ops = [self._tx_put(self._ticket_item(ticket), f"{t.VERSION_ATTR} = :v", {":v": expected})]
        if self._releases_guard(current, ticket):
            ops.append(self._guard_release_op(ticket))
        ops.extend(self._event_ops(ticket, start=len(current.events)))
        try:
            self._transact(ops)
        except _Cancelled as exc:
            if exc.is_conflict:
                raise ConflictError(f"ticket {ticket.id!r} was changed by someone else") from exc
            raise StoreError(f"saving ticket {ticket.id!r} failed: {exc}") from exc
        return ticket

    def _releases_guard(self, current: Ticket, ticket: Ticket) -> bool:
        """True when this save closes the ticket and the village guard still points at it."""
        closing = TicketState.CLOSED_VERIFIED
        if ticket.state is not closing or current.state is closing:
            return False
        holder = self._get_item(t.village_pk(ticket.village_id), t.OPEN_TICKET_SK)
        return holder is not None and holder.get("ticket_id") == ticket.id

    def _guard_release_op(self, ticket: Ticket) -> dict[str, Any]:
        delete = {
            "TableName": self.table_name,
            "Key": t.marshal({t.PK: t.village_pk(ticket.village_id), t.SK: t.OPEN_TICKET_SK}),
            "ConditionExpression": "ticket_id = :tid",
            "ExpressionAttributeValues": t.marshal({":tid": ticket.id}),
        }
        return {"Delete": delete}

    def _ticket_item(self, ticket: Ticket) -> dict[str, Any]:
        keys = {
            t.PK: t.village_pk(ticket.village_id),
            t.SK: t.tkt_sk(ticket.id),
            t.GSI1PK: t.ticket_state_gsi_pk(ticket.state),
            t.GSI1SK: t.iso_ts(ticket.opened_at),
            t.VERSION_ATTR: t.iso_ts(ticket.updated_at),
        }
        return t.model_to_item(ticket, keys, "Ticket")

    def _event_ops(self, ticket: Ticket, *, start: int) -> list[dict[str, Any]]:
        ops: list[dict[str, Any]] = []
        for seq in range(start, len(ticket.events)):
            event = ticket.events[seq]
            keys = {
                t.PK: t.tkt_pk(ticket.id),
                t.SK: t.evt_sk(event.at, seq),
                "ticket_id": ticket.id,
                "village_id": ticket.village_id,
                "seq": seq,
            }
            ops.append(self._tx_put(t.model_to_item(event, keys, "TicketEvent")))
        return ops

    # --- call sessions ----------------------------------------------------------------------------

    def put_call_session(
        self, call_id: str, data: Mapping[str, Any], ttl_days: int = CALL_TTL_DAYS
    ) -> None:
        """Create or update a call session's data; recorded steps and the task token are kept."""
        now = self._clock()
        assign = {
            "call_id": call_id,
            "data": dict(data),
            "updated_at": t.iso_ts(now),
            t.TTL_ATTR: _expiry(now, ttl_days),
            t.ENTITY_ATTR: "CallSession",
        }
        self._upsert_call(call_id, assign, {"created_at": t.iso_ts(now)})

    def get_call_session(self, call_id: str) -> CallSession | None:
        """The session with its steps in recorded order, or None if nothing (unexpired) exists."""
        now_epoch = int(_aware(self._clock()).timestamp())
        items = [
            item
            for item in self._query(t.call_pk(call_id))
            if item.get(t.TTL_ATTR) is None or int(item[t.TTL_ATTR]) > now_epoch
        ]
        if not items:
            return None
        meta = next((item for item in items if item[t.SK] == t.META_SK), {})
        steps = sorted(
            (item for item in items if str(item[t.SK]).startswith(t.STEP_PREFIX)),
            key=lambda item: (str(item.get("recorded_at", "")), str(item[t.SK])),
        )
        ttl = meta.get(t.TTL_ATTR)
        return CallSession(
            call_id=call_id,
            data=meta.get("data") or {},
            steps={str(item["step"]): item.get("payload") for item in steps},
            last_step=str(steps[-1]["step"]) if steps else None,
            task_token=meta.get("task_token"),
            created_at=meta.get("created_at"),
            updated_at=meta.get("updated_at"),
            expires_at=None if ttl is None else datetime.fromtimestamp(int(ttl), UTC),
        )

    def record_call_step(
        self, call_id: str, step: str, payload: Mapping[str, Any] | None = None
    ) -> bool:
        """Record one IVR step once. False when (call_id, step) was already recorded (replay)."""
        now = self._clock()
        item = {
            t.PK: t.call_pk(call_id),
            t.SK: t.step_sk(step),
            "step": step,
            "payload": dict(payload or {}),
            "recorded_at": t.iso_ts(now),
            t.TTL_ATTR: _expiry(now, CALL_TTL_DAYS),
            t.ENTITY_ATTR: "CallStep",
        }
        return self._put_if_absent(item)

    def set_task_token(self, call_id: str, token: str) -> None:
        """Attach the Step Functions task token to a call (creates the session if needed)."""
        now = self._clock()
        assign = {
            "call_id": call_id,
            "task_token": token,
            "updated_at": t.iso_ts(now),
            t.ENTITY_ATTR: "CallSession",
        }
        defaults = {
            "created_at": t.iso_ts(now),
            "data": {},
            t.TTL_ATTR: _expiry(now, CALL_TTL_DAYS),
        }
        self._upsert_call(call_id, assign, defaults)

    def _upsert_call(
        self, call_id: str, assign: Mapping[str, Any], defaults: Mapping[str, Any]
    ) -> None:
        """SET `assign` attributes, and `defaults` only where absent, on the call's META item."""
        names: dict[str, str] = {}
        values: dict[str, Any] = {}
        parts: list[str] = []
        for n, (attr, value) in enumerate(assign.items()):
            names[f"#a{n}"], values[f":a{n}"] = attr, value
            parts.append(f"#a{n} = :a{n}")
        for n, (attr, value) in enumerate(defaults.items()):
            names[f"#d{n}"], values[f":d{n}"] = attr, value
            parts.append(f"#d{n} = if_not_exists(#d{n}, :d{n})")
        self._client.update_item(
            TableName=self.table_name,
            Key=t.marshal({t.PK: t.call_pk(call_id), t.SK: t.META_SK}),
            UpdateExpression="SET " + ", ".join(parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=t.marshal(values),
        )

    # --- activity feed ----------------------------------------------------------------------------

    def put_activity(
        self,
        kind: str,
        village_id: str | None,
        text_en: str,
        text_hi: str,
        *,
        at: datetime | None = None,
    ) -> ActivityEntry:
        """Append one line to the console feed (`ACTIVITY#{utc day}`, kept 30 days)."""
        entry = ActivityEntry(
            at=at or self._clock(),
            kind=kind,
            village_id=village_id,
            text_en=text_en,
            text_hi=text_hi,
        )
        keys = {
            t.PK: t.activity_pk(t.utc_date(entry.at)),
            t.SK: t.activity_sk(entry.at, uuid.uuid4().hex),
            t.TTL_ATTR: _expiry(entry.at, ACTIVITY_TTL_DAYS),
        }
        self._put_item(t.model_to_item(entry, keys, "Activity"))
        return entry

    def list_activity(self, since: datetime, *, limit: int = 200) -> list[ActivityEntry]:
        """Entries strictly after `since`, oldest first; the newest `limit` if there are more.

        Looks back at most ACTIVITY_LOOKBACK_DAYS UTC days from now.
        """
        if limit <= 0:
            return []
        today = t.utc_date(self._clock())
        day = max(t.utc_date(since), today - timedelta(days=ACTIVITY_LOOKBACK_DAYS - 1))
        after = t.iso_ts(since) + _AFTER_ANY_UID
        entries: list[ActivityEntry] = []
        while day <= today:
            items = self._query(t.activity_pk(day), sk_after=after)
            entries.extend(t.item_to_model(item, ActivityEntry) for item in items)
            day += timedelta(days=1)
        return entries[-limit:]

    # --- low-level helpers ------------------------------------------------------------------------

    def _get_item(self, pk: str, sk: str) -> dict[str, Any] | None:
        response = self._client.get_item(
            TableName=self.table_name,
            Key=t.marshal({t.PK: pk, t.SK: sk}),
            ConsistentRead=True,
        )
        raw = response.get("Item")
        return None if raw is None else t.unmarshal(raw)

    def _put_item(self, item: Mapping[str, Any]) -> None:
        self._client.put_item(TableName=self.table_name, Item=t.marshal(item))

    def _put_if_absent(self, item: Mapping[str, Any]) -> bool:
        """Conditional put; False when an item with the same key already exists."""
        try:
            self._client.put_item(
                TableName=self.table_name,
                Item=t.marshal(item),
                ConditionExpression=_ABSENT,
            )
        except ClientError as err:
            if _error_code(err) == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def _put_request(
        self, model: BaseModel, keys: Mapping[str, Any], entity: str
    ) -> dict[str, Any]:
        return {"PutRequest": {"Item": t.marshal(t.model_to_item(model, keys, entity))}}

    def _tx_put(
        self,
        item: Mapping[str, Any],
        condition: str | None = None,
        values: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        put: dict[str, Any] = {"TableName": self.table_name, "Item": t.marshal(item)}
        if condition:
            put["ConditionExpression"] = condition
        if values:
            put["ExpressionAttributeValues"] = t.marshal(values)
        return {"Put": put}

    def _transact(self, ops: Sequence[Mapping[str, Any]]) -> None:
        """TransactWriteItems; raises _Cancelled with per-item reason codes."""
        if len(ops) > MAX_TRANSACT_ITEMS:
            raise ValueError(f"a transaction holds at most {MAX_TRANSACT_ITEMS} items")
        try:
            self._client.transact_write_items(TransactItems=list(ops))
        except ClientError as err:
            if _error_code(err) == "TransactionCanceledException":
                raise _Cancelled(_cancellation_codes(err)) from err
            raise

    def _batch_write(self, requests: Sequence[Mapping[str, Any]]) -> None:
        """BatchWriteItem in chunks of 25, retrying unprocessed items with backoff."""
        for offset in range(0, len(requests), _BATCH_SIZE):
            chunk = list(requests[offset : offset + _BATCH_SIZE])
            pending: dict[str, Any] = {self.table_name: chunk}
            for attempt in range(_BATCH_RETRIES):
                response = self._client.batch_write_item(RequestItems=pending)
                pending = response.get("UnprocessedItems") or {}
                if not pending:
                    break
                time.sleep(0.05 * 2**attempt)
            else:
                raise StoreError("DynamoDB left items unprocessed after retries")

    def _query(
        self,
        pk: str,
        *,
        index: str | None = None,
        sk_prefix: str | None = None,
        sk_between: tuple[str, str] | None = None,
        sk_after: str | None = None,
        where: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Query one partition (base table or GSI1) with at most one sort-key condition."""
        names = {"#pk": t.GSI1PK if index else t.PK, "#sk": t.GSI1SK if index else t.SK}
        values: dict[str, Any] = {":pk": pk}
        condition = "#pk = :pk"
        if sk_prefix is not None:
            condition += " AND begins_with(#sk, :sk)"
            values[":sk"] = sk_prefix
        elif sk_between is not None:
            condition += " AND #sk BETWEEN :lo AND :hi"
            values[":lo"], values[":hi"] = sk_between
        elif sk_after is not None:
            condition += " AND #sk > :sk"
            values[":sk"] = sk_after
        else:
            del names["#sk"]
        kwargs: dict[str, Any] = {"TableName": self.table_name, "KeyConditionExpression": condition}
        if where:
            filters = []
            for n, (attr, value) in enumerate(where.items()):
                names[f"#w{n}"], values[f":w{n}"] = attr, value
                filters.append(f"#w{n} = :w{n}")
            kwargs["FilterExpression"] = " AND ".join(filters)
        if index:
            kwargs["IndexName"] = index
        else:
            kwargs["ConsistentRead"] = True
        kwargs["ExpressionAttributeNames"] = names
        kwargs["ExpressionAttributeValues"] = t.marshal(values)
        return list(self._paginate(kwargs))

    def _paginate(self, kwargs: dict[str, Any]) -> Iterator[dict[str, Any]]:
        while True:
            response = self._client.query(**kwargs)
            yield from (t.unmarshal(raw) for raw in response.get("Items", []))
            last = response.get("LastEvaluatedKey")
            if not last:
                return
            kwargs = {**kwargs, "ExclusiveStartKey": last}
