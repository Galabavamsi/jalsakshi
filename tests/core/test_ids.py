import re
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from jalsakshi.core.clock import IST
from jalsakshi.core.ids import id_timestamp, new_id

ID_SHAPE = re.compile(r"tkt_[0-9a-hjkmnp-tv-z]{26}")


def test_shape_and_prefix() -> None:
    assert ID_SHAPE.fullmatch(new_id("tkt"))
    assert new_id("tkt_").startswith("tkt_")
    assert not new_id("tkt").startswith("tkt__")


@pytest.mark.parametrize("bad", ["", "_", "Tkt", "1tkt", "tk-t", "a" * 17, "tkt__"])
def test_bad_prefix_rejected(bad: str) -> None:
    with pytest.raises(ValueError, match="prefix"):
        new_id(bad)


def test_unique() -> None:
    assert len({new_id("chk") for _ in range(2000)}) == 2000


def test_timestamp_round_trip_to_the_millisecond() -> None:
    at = datetime(2026, 10, 9, 10, 30, 15, 123_456, tzinfo=IST)
    assert id_timestamp(new_id("tkt", at=at)) == at.replace(microsecond=123_000)
    assert id_timestamp(new_id("tkt", at=at)).tzinfo is UTC


def test_default_time_is_now() -> None:
    assert abs(id_timestamp(new_id("x")) - datetime.now(UTC)) < timedelta(seconds=5)


def test_bad_times_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        new_id("tkt", at=datetime(2026, 10, 9))
    with pytest.raises(ValueError, match="1970"):
        new_id("tkt", at=datetime(1969, 12, 31, tzinfo=UTC))


@pytest.mark.parametrize("bad", ["tkt", "tkt_short", "tkt_" + "u" * 26, "tkt_" + "0" * 27])
def test_id_timestamp_rejects_foreign_ids(bad: str) -> None:
    with pytest.raises(ValueError):
        id_timestamp(bad)


@given(
    st.datetimes(min_value=datetime(1970, 1, 2), max_value=datetime(9999, 12, 30)),
    st.datetimes(min_value=datetime(1970, 1, 2), max_value=datetime(9999, 12, 30)),
)
def test_ids_sort_by_creation_millisecond(a: datetime, b: datetime) -> None:
    a, b = a.replace(tzinfo=UTC), b.replace(tzinfo=UTC)
    id_a, id_b = new_id("tkt", at=a), new_id("tkt", at=b)
    if id_timestamp(id_a) < id_timestamp(id_b):
        assert id_a < id_b
    elif id_timestamp(id_a) > id_timestamp(id_b):
        assert id_a > id_b
