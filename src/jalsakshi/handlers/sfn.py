"""Step Functions glue: resume a waiting task (SendTaskSuccess) and start executions.

A task token can be used once and expires with its task, so a failed resume (already used,
timed out, execution stopped) is logged and reported as False instead of raised: the workflow's
own timeout path (mark the call unreachable, escalate) takes over.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from botocore.exceptions import ClientError

from jalsakshi.handlers import config
from jalsakshi.handlers.common import dumps, logger

STALE_TOKEN_ERRORS: Final = frozenset({"TaskTimedOut", "InvalidToken", "TaskDoesNotExist"})


def send_task_success(token: str | None, output: Mapping[str, Any]) -> bool:
    """Resume the task waiting on ``token`` with ``output``; False if it is no longer waiting."""
    if not token:
        return False
    try:
        config.client("stepfunctions").send_task_success(taskToken=token, output=dumps(output))
    except ClientError as err:
        code = str(err.response.get("Error", {}).get("Code", ""))
        if code in STALE_TOKEN_ERRORS:
            logger.warning("task token no longer waiting", extra={"error_code": code})
            return False
        raise
    return True


def start_execution(state_machine_arn: str, payload: Mapping[str, Any]) -> str:
    """Start a state machine execution and return its ARN."""
    response = config.client("stepfunctions").start_execution(
        stateMachineArn=state_machine_arn, input=dumps(payload)
    )
    return str(response["executionArn"])
