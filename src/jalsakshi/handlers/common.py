"""Shared glue for every Lambda: Powertools logger, metrics and tracer, errors, masking, feed.

Metric names follow ARCHITECTURE.md §12 (namespace ``JalSakshi``, dimension ``service``). Every
helper that only reports (metrics, the activity feed) swallows its own failures, so reporting
can never break a call or a ticket transition.
"""

from __future__ import annotations

import functools
import importlib.util
import json
import warnings
from collections.abc import Callable, Mapping
from typing import Any, Final

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response
from aws_lambda_powertools.metrics import MetricUnit, single_metric
from pydantic import ValidationError

from jalsakshi.handlers import config
from jalsakshi.policy import Decision
from jalsakshi.store import ConflictError, NotFoundError

SERVICE: Final = "jalsakshi"
NAMESPACE: Final = "JalSakshi"
JSON_TYPE: Final = "application/json"

logger = Logger(service=SERVICE)
metrics = Metrics(namespace=NAMESPACE, service=SERVICE)
# Many invocations (webhook replays, reads) emit no metric; that is normal, not a warning.
warnings.filterwarnings("ignore", message="No application metrics to publish", category=UserWarning)


class _NoopTracer:
    """Stand-in when aws-xray-sdk is missing (local tests); decorators pass through."""

    def capture_lambda_handler(self, lambda_handler: Any = None, **_: Any) -> Any:
        return lambda_handler if lambda_handler is not None else (lambda fn: fn)

    def capture_method(self, method: Any = None, **_: Any) -> Any:
        return method if method is not None else (lambda fn: fn)

    def put_annotation(self, key: str, value: Any) -> None:
        """Ignored."""


def _make_tracer() -> Tracer | _NoopTracer:
    if importlib.util.find_spec("aws_xray_sdk") is None:
        logger.warning("aws-xray-sdk is not installed; X-Ray tracing is off")
        return _NoopTracer()
    return Tracer(service=SERVICE)


tracer = _make_tracer()

type LambdaHandler = Callable[[Any, Any], Any]


def entrypoint(fn: LambdaHandler) -> LambdaHandler:
    """Wrap a Lambda handler with Powertools logging context, tracing and metric flushing."""

    @logger.inject_lambda_context(clear_state=True)
    @tracer.capture_lambda_handler(capture_response=False)
    @metrics.log_metrics
    @functools.wraps(fn)
    def wrapper(event: Any, context: Any) -> Any:
        return fn(event, context)

    return wrapper


# --- metrics and the activity feed ------------------------------------------------------------


def count(name: str, value: float = 1, **dimensions: str) -> None:
    """Emit a Count metric; with dimensions it is flushed on its own (EMF single metric)."""
    try:
        if not dimensions:
            metrics.add_metric(name=name, unit=MetricUnit.Count, value=value)
            return
        with single_metric(
            name=name,
            unit=MetricUnit.Count,
            value=value,
            namespace=NAMESPACE,
            default_dimensions={"service": SERVICE},
        ) as metric:
            for key, dim in dimensions.items():
                metric.add_dimension(name=key, value=str(dim))
    except Exception:
        logger.exception("metric emit failed", extra={"metric": name})


def activity(kind: str, village_id: str | None, text_en: str, text_hi: str) -> None:
    """Append one line to the console's live feed (best effort)."""
    try:
        config.repository().put_activity(kind, village_id, text_en, text_hi, at=config.now())
    except Exception:
        logger.exception("activity write failed", extra={"kind": kind})


def record_denial(decision: Decision, village_id: str | None, subject: str) -> None:
    """Metric and feed entry for a Cedar deny (``PolicyDenied{policy_id}``)."""
    for policy_id in decision.policy_ids:
        count("PolicyDenied", policy_id=policy_id)
    if decision.policy_ids:
        activity(
            "policy_denied",
            village_id,
            f"Policy {decision.policy_ids[0]} blocked {subject}: {decision.reasons_en[0]}",
            f"नियम {decision.policy_ids[0]} ने रोका ({subject}): {decision.reasons_hi[0]}",
        )


# --- privacy --------------------------------------------------------------------------------------


def mask_phone(phone: str | None) -> str | None:
    """``+919876543210`` -> ``+91XXXXXX3210`` (country code and last four digits only)."""
    if not phone:
        return None
    if len(phone) <= 7:
        return "X" * len(phone)
    return f"{phone[:3]}{'X' * (len(phone) - 7)}{phone[-4:]}"


# --- HTTP (API Gateway HTTP API) ------------------------------------------------------------------


class ApiError(Exception):
    """An HTTP error with the §13 envelope ``{error: {code, message}}``."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class PolicyDeniedError(Exception):
    """A Cedar deny, answered as ``403 {denied, policy_id, reason_hi, reason_en}``."""

    def __init__(self, decision: Decision) -> None:
        super().__init__(", ".join(decision.policy_ids))
        self.decision = decision


def dumps(body: Any) -> str:
    """Compact JSON with Devanagari kept readable."""
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str)


def json_response(status: int, body: Any) -> Response:
    """A JSON response."""
    return Response(status_code=status, content_type=JSON_TYPE, body=dumps(body))


def error_response(status: int, code: str, message: str) -> Response:
    """The §13 error envelope."""
    return json_response(status, {"error": {"code": code, "message": message}})


def json_body(app: APIGatewayHttpResolver) -> dict[str, Any]:
    """The request's JSON object body ({} when empty); 400 when it is not a JSON object."""
    raw = app.current_event.decoded_body
    if raw is None or not str(raw).strip():
        return {}
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(400, "bad_json", "request body is not valid JSON") from exc
    if not isinstance(body, Mapping):
        raise ApiError(400, "bad_json", "request body must be a JSON object")
    return dict(body)


def install_error_handlers(app: APIGatewayHttpResolver) -> None:
    """Map domain and validation errors onto HTTP responses for a resolver."""

    @app.exception_handler(ApiError)
    def _api_error(exc: ApiError) -> Response:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(PolicyDeniedError)
    def _denied(exc: PolicyDeniedError) -> Response:
        return json_response(403, exc.decision.denial_payload())

    @app.exception_handler(ValidationError)
    def _invalid(exc: ValidationError) -> Response:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(part) for part in first.get("loc", ())) or "body"
        return error_response(400, "invalid_request", f"{where}: {first.get('msg', 'invalid')}")

    @app.exception_handler(NotFoundError)
    def _missing(exc: NotFoundError) -> Response:
        return error_response(404, "not_found", str(exc))

    @app.exception_handler(ConflictError)
    def _conflict(exc: ConflictError) -> Response:
        return error_response(409, "conflict", "the record changed meanwhile; reload and retry")

    @app.not_found
    def _no_route(_: Exception) -> Response:
        return error_response(404, "no_route", "no such route")

    @app.exception_handler(Exception)
    def _crash(exc: Exception) -> Response:
        logger.exception("unhandled error", extra={"error_type": type(exc).__name__})
        return error_response(500, "internal", "internal error")
