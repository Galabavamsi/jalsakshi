"""Run an outbound job later: one-off EventBridge Scheduler entries that delete themselves.

Also creates each village's daily check-in schedule.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Final

from jalsakshi.core.clock import IST
from jalsakshi.handlers import config
from jalsakshi.handlers.common import logger

_SAFE: Final = re.compile(r"[^A-Za-z0-9_.-]")


def schedule_outbound(job: dict[str, Any], at: datetime, name: str) -> bool:
    """Queue ``job`` for the outbound Lambda at ``at``; False when not configured or a repeat."""
    cfg = config.settings()
    if not (cfg.scheduler_group and cfg.scheduler_role_arn and cfg.outbound_fn_arn):
        logger.warning("outbound scheduler not configured")
        return False
    local = at.astimezone(IST)
    schedule_name = (_SAFE.sub("-", name) + local.strftime("-%Y%m%d%H%M"))[:64]
    scheduler = config.client("scheduler")
    try:
        scheduler.create_schedule(
            Name=schedule_name,
            GroupName=cfg.scheduler_group,
            ScheduleExpression=f"at({local:%Y-%m-%dT%H:%M:%S})",
            ScheduleExpressionTimezone="Asia/Kolkata",
            FlexibleTimeWindow={"Mode": "OFF"},
            ActionAfterCompletion="DELETE",
            Target={
                "Arn": cfg.outbound_fn_arn,
                "RoleArn": cfg.scheduler_role_arn,
                "Input": json.dumps(job),
            },
        )
    except scheduler.exceptions.ConflictException:
        logger.info("job already scheduled", extra={"schedule_name": schedule_name})
        return False
    return True


def schedule_daily_checkin(village_id: str, local_time: str) -> bool:
    """Create or update the village's daily check-in schedule (Asia/Kolkata); False if unset."""
    cfg = config.settings()
    if not (cfg.checkin_group and cfg.checkin_role_arn and cfg.checkin_sfn_arn):
        logger.warning("daily check-in scheduling not configured")
        return False
    hour, minute = (int(part) for part in local_time.split(":"))
    request = {
        "Name": f"checkin-{village_id}"[:64],
        "GroupName": cfg.checkin_group,
        "ScheduleExpression": f"cron({minute} {hour} * * ? *)",
        "ScheduleExpressionTimezone": "Asia/Kolkata",
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "State": "ENABLED",
        "Description": f"JalSakshi daily check-in for {village_id}",
        "Target": {
            "Arn": cfg.checkin_sfn_arn,
            "RoleArn": cfg.checkin_role_arn,
            "Input": json.dumps(
                {"village_id": village_id, "purpose": "DAILY", "trigger": "schedule"}
            ),
        },
    }
    scheduler = config.client("scheduler")
    try:
        scheduler.update_schedule(**request)
    except scheduler.exceptions.ResourceNotFoundException:
        scheduler.create_schedule(**request)
    return True
