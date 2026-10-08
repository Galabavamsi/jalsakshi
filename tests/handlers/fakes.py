"""Test doubles for the handler tests: clock, Step Functions client, Lambda context, events."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from botocore.exceptions import ClientError

from jalsakshi.core.models import (
    CallOutcome,
    CheckIn,
    CleanAnswer,
    Consent,
    Household,
    Operator,
    OperatorRole,
    Purpose,
    Village,
    WaterAnswer,
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
