"""Single-table layout: table spec, key builders and item (de)serialisation.

See docs/ARCHITECTURE.md section 8. Everything here is pure except `create_table`, which takes a
caller-supplied boto3 DynamoDB client (used by tests and local scripts; infra/ owns the real table).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Final

from boto3.dynamodb.types import Binary, TypeDeserializer, TypeSerializer
from pydantic import BaseModel

PK: Final = "PK"
SK: Final = "SK"
GSI1: Final = "GSI1"
GSI1PK: Final = "GSI1PK"
GSI1SK: Final = "GSI1SK"
TTL_ATTR: Final = "ttl"
ENTITY_ATTR: Final = "entity"
VERSION_ATTR: Final = "version_ts"

TABLE_SPEC: Final[dict[str, Any]] = {
    "partition_key": PK,
    "sort_key": SK,
    "key_type": "S",
    "global_secondary_indexes": [
        {"index_name": GSI1, "partition_key": GSI1PK, "sort_key": GSI1SK, "projection": "ALL"},
    ],
    "ttl_attribute": TTL_ATTR,
    "billing_mode": "PAY_PER_REQUEST",
    "point_in_time_recovery": True,
}

SEP: Final = "#"
META_SK: Final = "META"
OPEN_TICKET_SK: Final = "OPENTKT"
VILLAGES_GSI_PK: Final = "VILLAGES"
HH_PREFIX: Final = "HH#"
CHK_PREFIX: Final = "CHK#"
DAY_PREFIX: Final = "DAY#"
TKT_PREFIX: Final = "TKT#"
EVT_PREFIX: Final = "EVT#"
OP_PREFIX: Final = "OP#"
STEP_PREFIX: Final = "STEP#"
MAX_ATTEMPT: Final = 999

_SERIALIZER: Final = TypeSerializer()
_DESERIALIZER: Final = TypeDeserializer()


# --- key builders -------------------------------------------------------------------------------


def _part(value: object) -> str:
    """Return a key component, rejecting empty values and the separator."""
    text = str(value)
    if not text or SEP in text:
        raise ValueError(f"invalid key component {value!r}: must be non-empty without '{SEP}'")
    return text


def _day(day: date) -> str:
    """Format a calendar date as yyyy-mm-dd (datetimes are rejected as ambiguous)."""
    if isinstance(day, datetime) or not isinstance(day, date):
        raise TypeError(f"expected a date, got {type(day).__name__}")
    return day.isoformat()


def iso_ts(ts: datetime) -> str:
    """Normalise a datetime to a fixed-width, sortable UTC ISO string (naive means UTC)."""
    aware = ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat(timespec="microseconds")


def utc_date(ts: datetime) -> date:
    """Calendar date of a timestamp in UTC (naive means UTC)."""
    aware = ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
    return aware.astimezone(UTC).date()


def village_pk(vid: str) -> str:
    """`VILLAGE#{vid}`: partition for a village and everything it owns."""
    return f"VILLAGE{SEP}{_part(vid)}"


def hh_sk(hid: str) -> str:
    """`HH#{hid}`: household under its village."""
    return f"{HH_PREFIX}{_part(hid)}"


def day_sk(day: date) -> str:
    """`DAY#{yyyy-mm-dd}`: reconciled day status under its village."""
    return f"{DAY_PREFIX}{_day(day)}"


def chk_prefix(day: date, purpose: str | None = None) -> str:
    """Sort-key prefix selecting the check-ins of one day (optionally one purpose)."""
    base = f"{CHK_PREFIX}{_day(day)}{SEP}"
    return base if purpose is None else f"{base}{_part(purpose)}{SEP}"


def chk_sk(day: date, purpose: str, hid: str, attempt: int) -> str:
    """`CHK#{date}#{purpose}#{hid}#{attempt:03d}` (attempt zero-padded so it sorts)."""
    if not 1 <= attempt <= MAX_ATTEMPT:
        raise ValueError(f"attempt must be 1..{MAX_ATTEMPT}, got {attempt}")
    return f"{chk_prefix(day, purpose)}{_part(hid)}{SEP}{attempt:03d}"


def tkt_sk(tid: str) -> str:
    """`TKT#{tid}`: ticket under its village."""
    return f"{TKT_PREFIX}{_part(tid)}"


def tkt_pk(tid: str) -> str:
    """`TKT#{tid}`: partition holding the ticket pointer (META) and its events (EVT#)."""
    return f"{TKT_PREFIX}{_part(tid)}"


def evt_sk(ts: datetime, seq: int | None = None) -> str:
    """`EVT#{iso_ts}` plus `#{seq:04d}` when given, so same-instant events stay distinct."""
    base = f"{EVT_PREFIX}{iso_ts(ts)}"
    return base if seq is None else f"{base}{SEP}{seq:04d}"


def ticket_state_gsi_pk(state: str) -> str:
    """`TKTSTATE#{state}`: GSI1 partition listing tickets by state."""
    return f"TKTSTATE{SEP}{_part(state)}"


def call_pk(call_id: str) -> str:
    """`CALL#{call_id}`: call session (META) and its idempotent IVR steps (STEP#)."""
    return f"CALL{SEP}{_part(call_id)}"


def step_sk(step: str) -> str:
    """`STEP#{step}`: idempotency marker for one IVR step (last component, so '#' is allowed)."""
    if not step:
        raise ValueError("step must be non-empty")
    return f"{STEP_PREFIX}{step}"


def op_pk(oid: str) -> str:
    """`OP#{oid}`: operator partition."""
    return f"{OP_PREFIX}{_part(oid)}"


def op_link_sk(oid: str) -> str:
    """`OP#{oid}` under a village: denormalised copy listing the village's operators."""
    return f"{OP_PREFIX}{_part(oid)}"


def activity_pk(day: date) -> str:
    """`ACTIVITY#{yyyy-mm-dd}` (UTC day): one partition of the console feed."""
    return f"ACTIVITY{SEP}{_day(day)}"


def activity_sk(at: datetime, uid: str) -> str:
    """`{iso_ts}#{uid}`: chronological, collision-free feed entry key."""
    return f"{iso_ts(at)}{SEP}{_part(uid)}"


# --- value conversion -----------------------------------------------------------------------------


def to_dynamo(value: Any) -> Any:
    """Convert a Python value into one boto3's TypeSerializer accepts (floats become Decimal)."""
    if value is None or isinstance(value, bool | int | bytes):
        return value
    if isinstance(value, str):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"DynamoDB cannot store non-finite number {value!r}")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"DynamoDB cannot store non-finite number {value!r}")
        return Decimal(repr(value))
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return to_dynamo(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(k): to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_dynamo(v) for v in value]
    raise TypeError(f"cannot store value of type {type(value).__name__}")


def from_dynamo(value: Any) -> Any:
    """Convert a deserialised DynamoDB value to plain Python (Decimal becomes int or float)."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, Binary):
        return bytes(value)
    if isinstance(value, Mapping):
        return {k: from_dynamo(v) for k, v in value.items()}
    if isinstance(value, set | frozenset):
        return sorted(from_dynamo(v) for v in value)
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    return value


def marshal(item: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Plain dict to DynamoDB wire format (`{"S": ...}` etc.)."""
    return {key: _SERIALIZER.serialize(to_dynamo(val)) for key, val in item.items()}


def unmarshal(raw: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """DynamoDB wire format to a plain dict."""
    return {key: from_dynamo(_DESERIALIZER.deserialize(val)) for key, val in raw.items()}


def model_to_item(model: BaseModel, keys: Mapping[str, Any], entity: str) -> dict[str, Any]:
    """Model fields (JSON mode: ISO dates, enum values) plus key attributes and an entity tag."""
    item: dict[str, Any] = model.model_dump(mode="json")
    item.update(keys)
    item[ENTITY_ATTR] = entity
    return item


def item_to_model[M: BaseModel](item: Mapping[str, Any], cls: type[M]) -> M:
    """Validate a plain item into `cls`, ignoring key and bookkeeping attributes."""
    fields = cls.model_fields
    return cls.model_validate({k: v for k, v in item.items() if k in fields})


# --- table definition -----------------------------------------------------------------------------


def create_table_kwargs(table_name: str) -> dict[str, Any]:
    """`CreateTable` arguments matching TABLE_SPEC (on-demand billing)."""
    key_type = TABLE_SPEC["key_type"]
    gsis = TABLE_SPEC["global_secondary_indexes"]
    names = [PK, SK] + [n for g in gsis for n in (g["partition_key"], g["sort_key"])]
    return {
        "TableName": table_name,
        "BillingMode": TABLE_SPEC["billing_mode"],
        "AttributeDefinitions": [{"AttributeName": n, "AttributeType": key_type} for n in names],
        "KeySchema": [
            {"AttributeName": PK, "KeyType": "HASH"},
            {"AttributeName": SK, "KeyType": "RANGE"},
        ],
        "GlobalSecondaryIndexes": [
            {
                "IndexName": g["index_name"],
                "KeySchema": [
                    {"AttributeName": g["partition_key"], "KeyType": "HASH"},
                    {"AttributeName": g["sort_key"], "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": g["projection"]},
            }
            for g in gsis
        ],
    }


def create_table(client: Any, table_name: str) -> None:
    """Create the table with TTL enabled and wait until it is active (tests and local dev)."""
    client.create_table(**create_table_kwargs(table_name))
    client.get_waiter("table_exists").wait(TableName=table_name)
    client.update_time_to_live(
        TableName=table_name,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": TTL_ATTR},
    )
