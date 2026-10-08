"""Key builders, value conversion and table definition."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel

from jalsakshi.core.models import Purpose, TicketState
from jalsakshi.store import table as t

from .factories import IST, NOW, TABLE, checkin, day_status, household, operator, ticket, village


def test_key_builders_match_architecture_layout() -> None:
    assert t.village_pk("v1") == "VILLAGE#v1"
    assert t.hh_sk("h1") == "HH#h1"
    assert t.day_sk(date(2026, 10, 9)) == "DAY#2026-10-09"
    assert t.chk_sk(date(2026, 10, 9), Purpose.VERIFY, "h1", 2) == "CHK#2026-10-09#VERIFY#h1#002"
    assert t.tkt_sk("t1") == "TKT#t1"
    assert t.tkt_pk("t1") == "TKT#t1"
    assert t.call_pk("c1") == "CALL#c1"
    assert t.op_pk("op1") == "OP#op1"
    assert t.op_link_sk("op1") == "OP#op1"
    assert t.ticket_state_gsi_pk(TicketState.OPEN) == "TKTSTATE#OPEN"
    assert t.activity_pk(date(2026, 10, 9)) == "ACTIVITY#2026-10-09"
    assert t.step_sk("Q_WATER") == "STEP#Q_WATER"


def test_chk_prefix_selects_day_and_purpose() -> None:
    day = date(2026, 10, 9)
    assert t.chk_prefix(day) == "CHK#2026-10-09#"
    assert t.chk_prefix(day, Purpose.DAILY) == "CHK#2026-10-09#DAILY#"
    assert t.chk_sk(day, Purpose.DAILY, "h1", 1).startswith(t.chk_prefix(day, Purpose.DAILY))


def test_evt_and_activity_keys_use_normalised_utc() -> None:
    at = datetime(2026, 10, 9, 10, 30, tzinfo=IST)
    assert t.evt_sk(at) == "EVT#2026-10-09T05:00:00.000000+00:00"
    assert t.evt_sk(at, 3) == "EVT#2026-10-09T05:00:00.000000+00:00#0003"
    assert t.activity_sk(at, "abc") == "2026-10-09T05:00:00.000000+00:00#abc"


@pytest.mark.parametrize("bad", ["", "a#b", "#"])
def test_key_components_reject_separator_and_empty(bad: str) -> None:
    with pytest.raises(ValueError):
        t.village_pk(bad)
    with pytest.raises(ValueError):
        t.chk_sk(date(2026, 10, 9), Purpose.DAILY, bad, 1)


def test_step_key_allows_separator_but_not_empty() -> None:
    assert t.step_sk("Q_WATER#retry") == "STEP#Q_WATER#retry"
    with pytest.raises(ValueError):
        t.step_sk("")


@pytest.mark.parametrize("attempt", [0, -1, 1000])
def test_chk_sk_rejects_out_of_range_attempt(attempt: int) -> None:
    with pytest.raises(ValueError):
        t.chk_sk(date(2026, 10, 9), Purpose.DAILY, "h1", attempt)


def test_day_keys_reject_datetimes() -> None:
    with pytest.raises(TypeError):
        t.day_sk(NOW)  # type: ignore[arg-type]


def test_iso_ts_normalises_to_utc_and_treats_naive_as_utc() -> None:
    assert t.iso_ts(datetime(2026, 10, 9, 10, 30, tzinfo=IST)) == "2026-10-09T05:00:00.000000+00:00"
    assert t.iso_ts(datetime(2026, 10, 9, 5, 0)) == "2026-10-09T05:00:00.000000+00:00"
    assert t.utc_date(datetime(2026, 10, 10, 1, 0, tzinfo=IST)) == date(2026, 10, 9)


@given(
    st.datetimes(
        min_value=datetime(2000, 1, 2), max_value=datetime(2100, 1, 1), timezones=st.just(UTC)
    ),
    st.timedeltas(min_value=timedelta(microseconds=1), max_value=timedelta(days=400)),
)
def test_iso_ts_sorts_like_time_across_timezones(a: datetime, gap: timedelta) -> None:
    later = (a + gap).astimezone(IST)
    assert t.iso_ts(a) < t.iso_ts(later)


@given(st.integers(1, t.MAX_ATTEMPT - 1))
def test_attempts_sort_numerically(attempt: int) -> None:
    day = date(2026, 10, 9)
    assert t.chk_sk(day, "DAILY", "h", attempt) < t.chk_sk(day, "DAILY", "h", attempt + 1)


_finite_floats = st.floats(
    min_value=-1e15, max_value=1e15, allow_nan=False, allow_infinity=False
).filter(lambda f: f == 0 or abs(f) > 1e-100)
_scalars = (
    st.none()
    | st.booleans()
    | st.integers(-(10**15), 10**15)
    | _finite_floats
    | st.text(max_size=12)
)
_json = st.recursive(
    _scalars,
    lambda inner: (
        st.lists(inner, max_size=4)
        | st.dictionaries(st.text(min_size=1, max_size=8), inner, max_size=4)
    ),
    max_leaves=12,
)


@given(st.dictionaries(st.text(min_size=1, max_size=8), _json, max_size=6))
def test_marshal_round_trips_json_values(value: dict[str, Any]) -> None:
    assert t.unmarshal(t.marshal(value)) == value


def test_to_dynamo_makes_values_decimal_safe() -> None:
    converted = t.to_dynamo(
        {"f": 0.1, "d": Decimal("2.5"), "e": Purpose.DAILY, "ts": NOW, "l": (1, 2.0), "s": {"x"}}
    )
    assert converted["f"] == Decimal("0.1")
    assert converted["d"] == Decimal("2.5")
    assert converted["e"] == "DAILY" and type(converted["e"]) is str
    assert converted["ts"] == NOW.isoformat()
    assert converted["l"] == [1, Decimal("2.0")]
    assert converted["s"] == ["x"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), Decimal("NaN")])
def test_to_dynamo_rejects_non_finite_numbers(bad: Any) -> None:
    with pytest.raises(ValueError):
        t.to_dynamo(bad)


def test_to_dynamo_rejects_unknown_types() -> None:
    with pytest.raises(TypeError):
        t.to_dynamo(object())


def test_from_dynamo_turns_decimals_into_int_or_float() -> None:
    assert t.from_dynamo({"a": Decimal("3"), "b": [Decimal("0.25")], "c": {Decimal("1")}}) == {
        "a": 3,
        "b": [0.25],
        "c": [1],
    }
    assert type(t.from_dynamo(Decimal("3"))) is int


@pytest.mark.parametrize(
    "model",
    [village(), household(), operator(), checkin(), day_status(), ticket()],
    ids=lambda m: type(m).__name__,
)
def test_models_round_trip_through_items(model: BaseModel) -> None:
    item = t.model_to_item(model, {t.PK: "P", t.SK: "S"}, type(model).__name__)
    raw = t.marshal(item)
    assert raw[t.PK] == {"S": "P"}
    assert raw[t.ENTITY_ATTR] == {"S": type(model).__name__}
    assert t.item_to_model(t.unmarshal(raw), type(model)) == model


def test_create_table_kwargs_follow_table_spec() -> None:
    kwargs = t.create_table_kwargs(TABLE)
    assert kwargs["TableName"] == TABLE
    assert kwargs["BillingMode"] == t.TABLE_SPEC["billing_mode"] == "PAY_PER_REQUEST"
    assert {a["AttributeName"] for a in kwargs["AttributeDefinitions"]} == {
        "PK",
        "SK",
        "GSI1PK",
        "GSI1SK",
    }
    (gsi,) = kwargs["GlobalSecondaryIndexes"]
    assert gsi["IndexName"] == "GSI1"
    assert [k["AttributeName"] for k in gsi["KeySchema"]] == ["GSI1PK", "GSI1SK"]
    assert t.TABLE_SPEC["ttl_attribute"] == "ttl"


def test_create_table_enables_ttl(ddb: Any) -> None:
    table = ddb.describe_table(TableName=TABLE)["Table"]
    assert [k["AttributeName"] for k in table["KeySchema"]] == ["PK", "SK"]
    assert table["GlobalSecondaryIndexes"][0]["IndexName"] == "GSI1"
    ttl = ddb.describe_time_to_live(TableName=TABLE)["TimeToLiveDescription"]
    assert ttl["AttributeName"] == "ttl"
    assert ttl["TimeToLiveStatus"] == "ENABLED"
