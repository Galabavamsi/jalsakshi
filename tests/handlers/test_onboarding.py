"""First-time setup (ARCHITECTURE §16): accounts see only their villages; setup creates the
village and team; pasted numbers each get one consent call; team phones are never families."""

from __future__ import annotations

from typing import Any

import pytest

from jalsakshi.core.models import ConsentStatus, OperatorRole
from jalsakshi.handlers import api, api_onboarding, config
from jalsakshi.store import Repository

from .fakes import VID, FakeLambda, HttpEvent, call

NEW_USER = {"sub": "user-new", "username": "sita", "cognito:groups": "[PANCHAYAT_SECRETARY]"}
OTHER_USER = {"sub": "user-other", "username": "ravi"}
ADMIN = {"sub": "user-admin", "username": "vamsi", "cognito:groups": "[ADMIN]"}


def get(path: str, claims: dict[str, Any]) -> Any:
    return call(api.handler, HttpEvent("GET", path, claims=claims))


def post(path: str, body: Any, claims: dict[str, Any]) -> Any:
    return call(api.handler, HttpEvent("POST", path, body, claims=claims))


@pytest.fixture
def lambdas(monkeypatch: pytest.MonkeyPatch) -> FakeLambda:
    monkeypatch.setenv("JALSAKSHI_OUTBOUND_FN", "jalsakshi-test-outbound")
    config.settings.cache_clear()
    fake = FakeLambda()
    config.use_client("lambda", fake)
    return fake


def test_a_new_account_needs_setup_and_sees_no_villages(seeded: Repository) -> None:
    status, me, _ = get("/api/me", NEW_USER)
    assert status == 200 and me["needs_setup"] is True and me["village_ids"] == []
    status, rows, _ = get("/api/villages", NEW_USER)
    assert rows == []
    assert get(f"/api/villages/{VID}", NEW_USER)[0] == 404


def test_admins_see_every_village(seeded: Repository) -> None:
    _, me, _ = get("/api/me", ADMIN)
    assert me["is_admin"] is True and VID in me["village_ids"]


def test_setup_creates_a_known_village_with_its_team(seeded: Repository) -> None:
    body = {
        "lgd_code": "442569",
        "operator": {"name": "Ramesh", "phone": "98765 43210"},
        "sarpanch": {"name": "Sunita", "phone": "+91 91234 56780"},
    }
    status, village, _ = post("/api/villages", body, NEW_USER)
    assert status == 201 and village["id"] == "lgd-442569" and village["lgd_code"] == "442569"
    status, me, _ = get("/api/me", NEW_USER)
    assert me["village_ids"] == ["lgd-442569"] and me["needs_setup"] is False
    status, team, _ = get("/api/villages/lgd-442569/team", NEW_USER)
    roles = {t["role"]: t for t in team}
    assert set(roles) == {OperatorRole.NAL_JAL_MITRA.value, OperatorRole.SARPANCH.value}
    assert roles["NAL_JAL_MITRA"]["display_name"] == "Ramesh"
    assert "43210" not in str(team).replace("XXXXXX3210", "")  # masked
    assert get("/api/villages/lgd-442569", OTHER_USER)[0] == 404


def test_setup_accepts_a_village_not_in_the_list(seeded: Repository) -> None:
    status, village, _ = post(
        "/api/villages", {"name": "Navagaon", "block": "Patan", "district": "Durg"}, NEW_USER
    )
    assert status == 201 and village["id"] == "v-navagaon"
    assert post("/api/villages", {"name": ""}, OTHER_USER)[0] == 400


def test_pasted_numbers_each_get_one_consent_call(seeded: Repository, lambdas: FakeLambda) -> None:
    post("/api/villages", {"name": "Navagaon", "block": "Patan", "district": "Durg"}, NEW_USER)
    phones = "98765 43210\n+91 91234 56780\n12345\n09876543210\n98765 43210\n"
    status, body, _ = post("/api/villages/v-navagaon/households/bulk", {"phones": phones}, NEW_USER)
    assert status == 200
    assert len(body["added"]) == 2
    whys = [s["why"] for s in body["skipped"]]
    assert "not a mobile number" in whys and any(w.startswith("already added") for w in whys)
    assert len(lambdas.events("register")) == 2
    families = seeded.list_households("v-navagaon")
    assert all(h.effective_consent is ConsentStatus.NONE for h in families)


def test_no_more_than_25_families_wait_for_their_call(
    seeded: Repository, lambdas: FakeLambda
) -> None:
    post("/api/villages", {"name": "Navagaon", "block": "Patan", "district": "Durg"}, NEW_USER)
    phones = [f"98000{n:05d}" for n in range(30)]
    _, body, _ = post("/api/villages/v-navagaon/households/bulk", {"phones": phones}, NEW_USER)
    assert len(body["added"]) == api_onboarding.MAX_PENDING_FAMILIES
    assert len(body["skipped"]) == 5


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("98765 43210", "+919876543210"),
        ("+91-98765-43210", "+919876543210"),
        ("09876543210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("12345", None),
        ("5876543210", None),
    ],
)
def test_normalise_mobile(raw: str, expected: str | None) -> None:
    assert api_onboarding.normalise_mobile(raw) == expected
