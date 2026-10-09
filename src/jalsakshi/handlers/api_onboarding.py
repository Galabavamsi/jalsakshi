"""First-time setup for a Panchayat (ARCHITECTURE.md §16): who the signed-in user is, creating
their village, its team (pump operator, sarpanch) and adding many families at once.

A secretary signs up, creates (or claims) one village and from then on sees only the villages
bound to their account; team members in the ``ADMIN`` group see every village. Adding families
only queues each family's consent call: nobody gets a check-in call before they press 1.
"""

from __future__ import annotations

import base64
import re
import secrets
from typing import Any, Final

from jalsakshi.agent.reader import ReaderError, read_register
from jalsakshi.core.models import ConsentStatus, Household, Operator, OperatorRole, Village
from jalsakshi.data.villages import load_villages
from jalsakshi.handlers import config, later, residents
from jalsakshi.handlers.api import (
    _actor,
    _claims,
    _dump,
    _groups,
    _masked_household,
    _masked_operator,
    _role,
    _village,
    app,
    user_id,
)
from jalsakshi.handlers.api_panchayat import _invoke_outbound
from jalsakshi.handlers.common import (
    ApiError,
    activity,
    json_body,
    json_response,
    logger,
    mask_phone,
)
from jalsakshi.store import Repository
from jalsakshi.voice.catalog import CALL_LANGUAGES, available_languages

ADMIN_GROUP: Final = "ADMIN"
MAX_PENDING_FAMILIES: Final = 25
_PHONE_DIGITS: Final = re.compile(r"\D")
_SLUG: Final = re.compile(r"[^a-z0-9]+")
_USERNAME: Final = re.compile(r"^[a-z0-9._-]{3,30}$")
TEAM_ROLES: Final = {
    "operator": OperatorRole.NAL_JAL_MITRA,
    "sarpanch": OperatorRole.SARPANCH,
    "secretary": OperatorRole.PANCHAYAT_SECRETARY,
}


def is_admin() -> bool:
    return ADMIN_GROUP in set(_groups(_claims().get("cognito:groups")))


@app.get("/api/me")
def me() -> Any:
    """The signed-in user, their role and the villages they look after (empty: needs setup)."""
    claims = _claims()
    repo = config.repository()
    admin = is_admin()
    villages = [v.id for v in repo.list_villages()] if admin else repo.user_villages(user_id())
    return json_response(
        200,
        {
            "username": claims.get("username") or claims.get("cognito:username"),
            "email": claims.get("email"),
            "role": _role().value,
            "is_admin": admin,
            "village_ids": villages,
            "needs_setup": not villages,
            "can_approve_announcements": _role() is OperatorRole.SARPANCH,
        },
    )


@app.get("/api/places")
def places() -> Any:
    """Known villages (LGD + Census records) to pick from during setup."""
    q = (app.current_event.get_query_string_value("q") or "").strip().lower()
    rows = [
        {
            "lgd_code": v.lgd_code,
            "name": v.name,
            "name_hi": v.name_hi,
            "gram_panchayat": v.gram_panchayat,
            "block": v.block,
            "district": v.district,
            "census_households": v.census_households,
        }
        for v in load_villages()
        if not q or q in v.name.lower() or q in (v.name_hi or "")
    ]
    return json_response(200, rows)


@app.post("/api/villages")
def create_village() -> Any:
    """Setup step 1+2: the village and who fixes water problems. Binds it to this account."""
    body = json_body(app)
    repo = config.repository()
    village = _new_village(repo, body)
    existing = repo.get_village(village.id)
    if existing is None:
        if not any(v.inbound for v in repo.list_villages()):
            village = village.model_copy(update={"inbound": True})
        repo.put_village(village)
    else:
        village = existing
    repo.bind_user_village(user_id(), village.id)
    try:
        later.schedule_daily_checkin(village.id, village.checkin_local_time)
    except Exception as exc:  # setup must not fail on the schedule; Settings can retry it
        logger.warning("daily schedule not created", extra={"error": str(exc)[:200]})
    for key in ("operator", "sarpanch"):
        person = body.get(key)
        if isinstance(person, dict) and person.get("phone"):
            _put_team_member(repo, village, key, person)
    activity(
        "setup",
        village.id,
        f"{village.name} was set up on JalSakshi",
        f"{village.name_hi or village.name} JalSakshi पर जुड़ा",
    )
    return json_response(201, _dump(village))


@app.get("/api/villages/<village_id>/team")
def get_team(village_id: str) -> Any:
    repo = config.repository()
    village = _village(repo, village_id)
    return json_response(
        200, [_masked_operator(o) for o in repo.list_operators_for_village(village.id)]
    )


@app.post("/api/villages/<village_id>/team")
def put_team(village_id: str) -> Any:
    """Add or change the pump operator, sarpanch or secretary (name + mobile)."""
    repo = config.repository()
    village = _village(repo, village_id)
    body = json_body(app)
    key = str(body.get("role") or "operator").lower()
    if key not in TEAM_ROLES:
        raise ApiError(400, "invalid_request", "role must be operator, sarpanch or secretary")
    operator = _put_team_member(repo, village, key, body)
    return json_response(200, _masked_operator(operator))


@app.post("/api/villages/<village_id>/households/bulk")
def add_households_bulk(village_id: str) -> Any:
    """Setup step 3: paste many numbers; each new family gets one consent call (25 waiting max)."""
    repo = config.repository()
    village = _village(repo, village_id)
    body = json_body(app)
    raw = body.get("phones")
    lines = raw if isinstance(raw, list) else str(raw or "").splitlines()
    details: dict[str, dict[str, str | None]] = {}
    for row in body.get("families") or []:
        if isinstance(row, dict) and row.get("phone"):
            lines.append(str(row["phone"]))
            phone_key = normalise_mobile(str(row["phone"]))
            if phone_key:
                details[phone_key] = {
                    "name": (str(row.get("name") or "").strip() or None),
                    "area": (str(row.get("area") or "").strip() or None),
                }
    added, skipped = [], []
    budget = MAX_PENDING_FAMILIES - _pending_count(repo, village.id)
    for entry in lines:
        phone = normalise_mobile(str(entry))
        if phone is None:
            if str(entry).strip():
                skipped.append({"input": str(entry)[:20], "why": "not a mobile number"})
            continue
        same = [h for h in repo.find_households_by_phone(phone) if h.village_id == village.id]
        if same:
            status = same[0].effective_consent.value
            skipped.append({"input": mask_phone(phone), "why": f"already added ({status})"})
            continue
        if budget <= 0:
            skipped.append(
                {
                    "input": mask_phone(phone),
                    "why": "25 families are already waiting for their call",
                }
            )
            continue
        extra = details.get(phone, {})
        household = Household(
            id=residents.new_household_id(phone),
            village_id=village.id,
            phone_e164=phone,
            display_name=extra.get("name"),
            hamlet=extra.get("area"),
            language=village.languages[0] if village.languages else "hi",
            consent_status=ConsentStatus.NONE,
            registered_via="console",
        )
        repo.put_household(household)
        _invoke_outbound(
            {
                "kind": "register",
                "village_id": village.id,
                "household_id": household.id,
                "requested_at": config.now().isoformat(),
            }
        )
        added.append(_masked_household(household))
        budget -= 1
    if added:
        activity(
            "consent",
            village.id,
            f"{_actor()} added {len(added)} families; each gets a consent call",
            f"{len(added)} परिवार जोड़े गए; हर परिवार को सहमति की कॉल जाएगी",
        )
    return json_response(200, {"added": added, "skipped": skipped})


def normalise_mobile(raw: str) -> str | None:
    """An Indian mobile number in +91XXXXXXXXXX form, or None."""
    digits = _PHONE_DIGITS.sub("", raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "6789":
        return None
    return "+91" + digits


def _new_village(repo: Repository, body: dict[str, Any]) -> Village:
    lgd = str(body.get("lgd_code") or "").strip()
    known = next((v for v in load_villages() if lgd and v.lgd_code == lgd), None)
    if known is not None:
        return known.model_copy(update={"checkin_local_time": "19:00", "inbound": False})
    name = str(body.get("name") or "").strip()
    if not name:
        raise ApiError(400, "invalid_request", "village name is required")
    slug = _SLUG.sub("-", name.lower()).strip("-")[:30] or "village"
    return Village(
        id=f"v-{slug}",
        name=name,
        name_hi=(str(body.get("name_hi") or "").strip() or None),
        gram_panchayat=(str(body.get("gram_panchayat") or "").strip() or None),
        block=str(body.get("block") or "").strip() or "-",
        district=str(body.get("district") or "").strip() or "-",
        state=str(body.get("state") or "Chhattisgarh"),
        checkin_local_time="19:00",
    )


def _put_team_member(
    repo: Repository, village: Village, key: str, body: dict[str, Any]
) -> Operator:
    phone = normalise_mobile(str(body.get("phone") or ""))
    if phone is None:
        raise ApiError(400, "invalid_request", "enter a 10-digit mobile number")
    role = TEAM_ROLES[key]
    oid = f"op-{village.id}-{key}"[:60]
    existing = repo.get_operator(oid)
    villages = sorted({village.id, *(existing.village_ids if existing else [])})
    operator = Operator(
        id=oid,
        role=role,
        phone_e164=phone,
        display_name=(str(body.get("name") or "").strip() or None),
        village_ids=villages,
    )
    repo.put_operator(operator)
    return operator


def _pending_count(repo: Repository, village_id: str) -> int:
    """Families added from the console who have not answered their consent call yet."""
    return sum(
        1
        for h in repo.list_households(village_id)
        if h.registered_via == "console" and h.effective_consent is ConsentStatus.NONE
    )


@app.post("/api/villages/<village_id>/register-photo")
def read_register_photo(village_id: str) -> Any:
    """Read names, mobiles and areas from a photo of a register (Bedrock); nothing is added."""
    repo = config.repository()
    _village(repo, village_id)
    body = json_body(app)
    try:
        image = base64.b64decode(str(body.get("image_base64") or ""), validate=True)
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "image_base64 is not valid base64") from exc
    try:
        rows, model_id = read_register(image, str(body.get("media_type") or "image/jpeg"))
    except ValueError as exc:
        raise ApiError(400, "invalid_request", str(exc)) from exc
    except ReaderError as exc:
        raise ApiError(502, "unreadable", "Could not read the photo. Try a sharper photo.") from exc
    return json_response(
        200,
        {
            "rows": [r.model_dump() for r in rows],
            "model_id": model_id,
            "note": "Read by AI from the photo. Check every number before adding.",
        },
    )


@app.post("/api/villages/<village_id>/settings")
def village_settings(village_id: str) -> Any:
    """Call languages (first = default) and the daily call time of a village."""
    repo = config.repository()
    village = _village(repo, village_id)
    body = json_body(app)
    update: dict[str, Any] = {}
    if "languages" in body:
        languages = [str(code).lower() for code in body.get("languages") or []]
        bad = [code for code in languages if code not in CALL_LANGUAGES]
        if not languages or bad:
            raise ApiError(400, "invalid_request", f"unknown call language: {bad or 'none'}")
        update["languages"] = list(dict.fromkeys(languages))
    if body.get("checkin_local_time"):
        update["checkin_local_time"] = str(body["checkin_local_time"])
    updated = Village.model_validate({**village.model_dump(), **update})
    repo.put_village(updated)
    if "checkin_local_time" in update:
        later.schedule_daily_checkin(updated.id, updated.checkin_local_time)
    return json_response(200, _dump(updated))


@app.get("/api/languages")
def languages() -> Any:
    """Call languages: which have a prompt set ready on this stage."""
    ready = set(available_languages())
    return json_response(
        200,
        [
            {"code": code, "name": name, "ready": code in ready}
            for code, (name, _) in CALL_LANGUAGES.items()
        ],
    )


@app.post("/api/admin/panchayats")
def create_panchayat() -> Any:
    """Team only: create a Panchayat login, its village, call languages and team in one go."""
    if not is_admin():
        raise ApiError(403, "forbidden", "only the JalSakshi team can set up a Panchayat")
    body = json_body(app)
    username = str(body.get("username") or "").strip().lower()
    if not _USERNAME.match(username):
        raise ApiError(400, "invalid_request", "username: 3-30 letters, digits, . _ or -")
    password = str(body.get("temporary_password") or "") or _temporary_password()
    repo = config.repository()
    village = _new_village(repo, body.get("village") or {})
    languages = [
        str(c).lower() for c in body.get("languages") or ["hi"] if str(c).lower() in CALL_LANGUAGES
    ]
    village = village.model_copy(update={"languages": languages or ["hi"]})
    existing = repo.get_village(village.id)
    if existing is None:
        if not any(v.inbound for v in repo.list_villages()):
            village = village.model_copy(update={"inbound": True})
        repo.put_village(village)
    else:
        village = existing.model_copy(update={"languages": village.languages})
        repo.put_village(village)
    sub = _create_login(username, password)
    repo.bind_user_village(sub, village.id)
    for key in ("operator", "sarpanch", "secretary"):
        person = body.get(key)
        if isinstance(person, dict) and person.get("phone"):
            _put_team_member(repo, village, key, person)
    try:
        later.schedule_daily_checkin(village.id, village.checkin_local_time)
    except Exception as exc:  # the console can retry from Settings
        logger.warning("daily schedule not created", extra={"error": str(exc)[:200]})
    return json_response(
        201,
        {
            "username": username,
            "temporary_password": password,
            "village": _dump(village),
            "note": "Share the password privately; it must be changed at first sign-in.",
        },
    )


def _create_login(username: str, password: str) -> str:
    pool = config.settings().user_pool_id
    if not pool:
        raise ApiError(503, "not_configured", "user pool is not configured on this stage")
    cognito = config.client("cognito-idp")
    try:
        response = cognito.admin_create_user(
            UserPoolId=pool,
            Username=username,
            TemporaryPassword=password,
            MessageAction="SUPPRESS",
        )
    except cognito.exceptions.UsernameExistsException as exc:
        raise ApiError(409, "username_taken", "that username already exists") from exc
    cognito.admin_add_user_to_group(
        UserPoolId=pool, Username=username, GroupName=OperatorRole.PANCHAYAT_SECRETARY.value
    )
    attributes = {a["Name"]: a["Value"] for a in response["User"].get("Attributes", [])}
    return attributes.get("sub", username)


def _temporary_password() -> str:
    return "Jal" + secrets.token_hex(4) + "9"
