"""Test doubles for the handler tests: clock, Step Functions client, Lambda context, events."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from botocore.exceptions import ClientError

from jalsakshi.core.models import (
    AccessKind,
    CallOutcome,
    CheckIn,
    CleanAnswer,
    Consent,
    ConsentStatus,
    Household,
    Operator,
    OperatorRole,
    Purpose,
    Village,
    WaterAnswer,
    WaterPoint,
    WaterPointKind,
)

TABLE = "jalsakshi-handlers-test"
BUCKET = "jalsakshi-handlers-evidence"
STAGE = "test"
IVR_TOKEN = "s3cret-path-token"
NOW = datetime(2026, 10, 8, 5, 0, tzinfo=UTC)  # 10:30 IST
NIGHT = datetime(2026, 10, 8, 17, 0, tzinfo=UTC)  # 22:30 IST
DAY = date(2026, 10, 8)
VID = "v-test"
PHONES = ("+919800000001", "+919800000002", "+919800000003", "+919800000009")
CHECKIN_ARN = "arn:aws:states:ap-south-1:123456789012:stateMachine:jalsakshi-test-checkin-run"
DOMAIN = "abc123.execute-api.ap-south-1.amazonaws.com"


class Clock:
    """Settable, advancing clock installed with ``config.set_clock``."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        self.now += timedelta(milliseconds=1)
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


class FakeSfn:
    """Records SendTaskSuccess / StartExecution calls; tokens in ``stale`` are expired."""

    def __init__(self) -> None:
        self.successes: list[tuple[str, dict[str, Any]]] = []
        self.executions: list[tuple[str, dict[str, Any]]] = []
        self.stale: set[str] = set()

    def send_task_success(self, *, taskToken: str, output: str) -> dict[str, Any]:
        if taskToken in self.stale:
            raise ClientError({"Error": {"Code": "TaskTimedOut"}}, "SendTaskSuccess")
        self.successes.append((taskToken, json.loads(output)))
        return {}

    def start_execution(self, *, stateMachineArn: str, input: str) -> dict[str, Any]:
        self.executions.append((stateMachineArn, json.loads(input)))
        return {"executionArn": f"{stateMachineArn.replace('stateMachine', 'execution')}:run-1"}

    def outputs_for(self, token: str) -> list[dict[str, Any]]:
        return [output for t, output in self.successes if t == token]


@dataclass
class LambdaContext:
    function_name: str = "jalsakshi-test"
    memory_limit_in_mb: int = 256
    invoked_function_arn: str = "arn:aws:lambda:ap-south-1:123456789012:function:jalsakshi-test"
    aws_request_id: str = "req-1"
    log_group_name: str = "/aws/lambda/jalsakshi-test"
    log_stream_name: str = "stream"
    function_version: str = "$LATEST"


@dataclass
class HttpEvent:
    """Builder for an API Gateway HTTP API (payload v2) event."""

    method: str
    path: str
    body: Any = None
    query: dict[str, str] = field(default_factory=dict)
    claims: dict[str, Any] | None = None
    form: dict[str, str] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    source_ip: str = "203.0.113.7"

    def build(self) -> dict[str, Any]:
        if self.form is not None:
            body: str | None = urlencode(self.form)
            content_type = "application/x-www-form-urlencoded"
        else:
            body = None if self.body is None else json.dumps(self.body)
            content_type = "application/json"
        context: dict[str, Any] = {
            "accountId": "123456789012",
            "apiId": "abc123",
            "domainName": DOMAIN,
            "domainPrefix": "abc123",
            "http": {
                "method": self.method,
                "path": self.path,
                "protocol": "HTTP/1.1",
                "sourceIp": self.source_ip,
                "userAgent": "pytest",
            },
            "requestId": "req-1",
            "routeKey": "$default",
            "stage": "$default",
            "time": "08/Oct/2026:05:00:00 +0000",
            "timeEpoch": 0,
        }
        if self.claims is not None:
            context["authorizer"] = {"jwt": {"claims": self.claims, "scopes": None}}
        return {
            "version": "2.0",
            "routeKey": "$default",
            "rawPath": self.path,
            "rawQueryString": urlencode(self.query),
            "queryStringParameters": self.query or None,
            "headers": {"content-type": content_type, **self.headers},
            "requestContext": context,
            "body": body,
            "isBase64Encoded": False,
        }


def call(handler: Any, event: HttpEvent) -> tuple[int, Any, dict[str, str]]:
    """Invoke an HTTP handler; returns (status, parsed body, headers)."""
    response = handler(event.build(), LambdaContext())
    raw = response.get("body") or ""
    headers = response.get("headers") or {}
    content_type = headers.get("Content-Type", "")
    body = json.loads(raw) if raw and "json" in content_type else raw
    return response["statusCode"], body, headers


# --- domain builders ------------------------------------------------------------------------------


def village(vid: str = VID, *, quorum: int = 2) -> Village:
    return Village(
        id=vid, name="Testgaon", block="Patan", district="Durg", quorum=quorum, active=True
    )


def household(hid: str, phone: str, *, consent: bool = True, vid: str = VID) -> Household:
    given = Consent(given_at=NOW - timedelta(days=3), channel="in_person") if consent else None
    return Household(id=hid, village_id=vid, phone_e164=phone, consent=given)


def operator(oid: str = "op-1", *, vid: str = VID, phone: str = PHONES[2]) -> Operator:
    return Operator(id=oid, role=OperatorRole.NAL_JAL_MITRA, phone_e164=phone, village_ids=[vid])


def checkin(
    hid: str,
    *,
    water: WaterAnswer | None = WaterAnswer.YES,
    clean: CleanAnswer | None = None,
    purpose: Purpose = Purpose.DAILY,
    day: date = DAY,
    attempt: int = 1,
    at: datetime = NOW,
    vid: str = VID,
) -> CheckIn:
    outcome = CallOutcome.ANSWERED if water is not None else CallOutcome.UNREACHABLE
    return CheckIn(
        village_id=vid,
        date=day,
        household_id=hid,
        attempt=attempt,
        call_id=f"c-{hid}-{purpose}-{attempt}",
        purpose=purpose,
        outcome=outcome,
        water=water,
        clean=clean,
        captured_at=at,
    )


# --- v2 helpers: async Lambda, Scheduler, named executions, water points, Vobiz webhooks ---------

TICKET_ARN = "arn:aws:states:ap-south-1:123456789012:stateMachine:jalsakshi-test-ticket-flow"
OUTBOUND_FN = "jalsakshi-test-outbound"
OUTBOUND_FN_ARN = "arn:aws:lambda:ap-south-1:123456789012:function:jalsakshi-test-outbound"
NOTES_FN = "jalsakshi-test-notes"
SCHEDULER_GROUP = "jalsakshi-test-callbacks"
SCHEDULER_ROLE_ARN = "arn:aws:iam::123456789012:role/jalsakshi-test-callbacks"
MORNING = datetime(2026, 10, 8, 5, 30, tzinfo=UTC)  # 11:00 IST
IVR_BASE = f"/ivr/vobiz/{IVR_TOKEN}"


class FakeLambda:
    """Records ``Invoke`` calls; ``events(kind)`` gives the async payloads of one job kind."""

    def __init__(self) -> None:
        self.invocations: list[tuple[str, str, dict[str, Any]]] = []

    def invoke(
        self, *, FunctionName: str, InvocationType: str = "RequestResponse", Payload: bytes = b""
    ) -> dict[str, Any]:
        self.invocations.append((FunctionName, InvocationType, json.loads(Payload or b"{}")))
        return {"StatusCode": 202 if InvocationType == "Event" else 200}

    def events(self, kind: str | None = None, *, function: str | None = None) -> list[dict]:
        return [
            payload
            for name, how, payload in self.invocations
            if how == "Event"
            and (function is None or name == function)
            and (kind is None or payload.get("kind") == kind)
        ]


class _SchedulerConflict(ClientError):
    def __init__(self, name: str) -> None:
        super().__init__(
            {"Error": {"Code": "ConflictException", "Message": name}}, "CreateSchedule"
        )


class _SchedulerExceptions:
    ConflictException = _SchedulerConflict


class FakeScheduler:
    """EventBridge Scheduler double: ``create_schedule`` by name; a repeated name conflicts."""

    exceptions = _SchedulerExceptions

    def __init__(self) -> None:
        self.schedules: dict[str, dict[str, Any]] = {}

    def create_schedule(self, *, Name: str, **kwargs: Any) -> dict[str, Any]:
        if Name in self.schedules:
            raise _SchedulerConflict(Name)
        self.schedules[Name] = {"Name": Name, **kwargs}
        return {"ScheduleArn": f"arn:aws:scheduler:ap-south-1:123456789012:schedule/{Name}"}


class NamedFakeSfn(FakeSfn):
    """FakeSfn that also takes an execution ``name`` (a repeated name already exists)."""

    def __init__(self) -> None:
        super().__init__()
        self.names: list[str | None] = []

    def start_execution(  # type: ignore[override]
        self, *, stateMachineArn: str, input: str, name: str | None = None
    ) -> dict[str, Any]:
        if name is not None and name in self.names:
            raise ClientError(
                {"Error": {"Code": "ExecutionAlreadyExists", "Message": name}}, "StartExecution"
            )
        self.names.append(name)
        return super().start_execution(stateMachineArn=stateMachineArn, input=input)


@dataclass
class V2Fakes:
    """What ``v2_fakes`` installed: the Lambda, Scheduler and Step Functions doubles."""

    lambdas: FakeLambda
    scheduler: FakeScheduler
    sfn: NamedFakeSfn


def v2_fakes(monkeypatch: Any) -> Iterator[V2Fakes]:
    """v2 settings (outbound and notes functions, scheduler, TicketFlow) and their fakes.

    Use in a fixture that runs after ``aws``: ``yield from v2_fakes(monkeypatch)``.
    """
    from jalsakshi.handlers import config, speech

    env = {
        "JALSAKSHI_OUTBOUND_FN": OUTBOUND_FN,
        "JALSAKSHI_OUTBOUND_FN_ARN": OUTBOUND_FN_ARN,
        "JALSAKSHI_NOTES_FN": NOTES_FN,
        "JALSAKSHI_SCHEDULER_GROUP": SCHEDULER_GROUP,
        "JALSAKSHI_SCHEDULER_ROLE_ARN": SCHEDULER_ROLE_ARN,
        "JALSAKSHI_TICKET_SFN_ARN": TICKET_ARN,
        "JALSAKSHI_CALLBACK_DELAY_S": "0",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("JALSAKSHI_PROMPTS_BUCKET", raising=False)
    config.settings.cache_clear()
    fakes = V2Fakes(FakeLambda(), FakeScheduler(), NamedFakeSfn())
    config.use_client("lambda", fakes.lambdas)
    config.use_client("scheduler", fakes.scheduler)
    config.use_client("stepfunctions", fakes.sfn)
    speech.use_tts(None)
    yield fakes
    speech.use_tts(None)


def water_point(
    wpid: str,
    kind: WaterPointKind = WaterPointKind.PIPED,
    *,
    vid: str = VID,
    operator_ids: tuple[str, ...] = (),
    quorum: int | None = None,
    name: str | None = None,
    active: bool = True,
) -> WaterPoint:
    return WaterPoint(
        id=wpid,
        village_id=vid,
        kind=kind,
        name=name or f"Testgaon {wpid}",
        name_hi=f"टेस्टगाँव {wpid}",
        operator_ids=list(operator_ids),
        quorum=quorum,
        active=active,
    )


def resident(
    hid: str,
    phone: str,
    *,
    wpid: str | None = None,
    access: AccessKind | None = None,
    vid: str = VID,
    status: ConsentStatus = ConsentStatus.GRANTED,
) -> Household:
    """A household with a v2 consent status (and optionally a water point)."""
    given = (
        Consent(given_at=NOW - timedelta(days=3), channel="ivr_keypad")
        if status is ConsentStatus.GRANTED
        else None
    )
    return Household(
        id=hid,
        village_id=vid,
        phone_e164=phone,
        consent=given,
        consent_status=status,
        access=access,
        water_point_id=wpid,
        registered_via="ivr",
    )


def vobiz_post(
    action: str, query: dict[str, str] | None = None, form: dict[str, str] | None = None
) -> tuple[int, str]:
    """POST one Vobiz webhook to the IVR handler; returns (status, XML body)."""
    from jalsakshi.handlers import ivr_vobiz

    fields = {"CallUUID": "vobiz-call-1", **(form or {})}
    event = HttpEvent("POST", f"{IVR_BASE}/{action}", query=query or {}, form=fields)
    status, body, _ = call(ivr_vobiz.handler, event)
    return status, body


def xml_root(xml: str) -> ET.Element:
    """The ``<Response>`` element of a VobizXML reply."""
    return ET.fromstring(xml.split("\n", 1)[1])


def next_turn(xml: str) -> int | None:
    """The ``turn`` in the reply's Redirect URL (None when the reply hangs up)."""
    redirect = xml_root(xml).find("Redirect")
    if redirect is None or redirect.text is None:
        return None
    return int(parse_qs(urlsplit(redirect.text).query)["turn"][0])


def run_call(call_id: str, keys: list[str | None]) -> list[str]:
    """Answer a stored call and press ``keys`` (None = timeout) through the webhooks."""
    status, xml = vobiz_post("answer", {"call_id": call_id})
    assert status == 200
    replies = [xml]
    for key in keys:
        turn = next_turn(xml)
        assert turn is not None, f"call {call_id} already hung up"
        form = {"Digits": key} if key is not None else {}
        status, xml = vobiz_post("digits", {"call_id": call_id, "turn": str(turn)}, form)
        assert status == 200
        replies.append(xml)
    return replies
