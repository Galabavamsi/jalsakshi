"""Start a stage fresh: delete village data, keep the audit trail (ARCHITECTURE.md §16).

Deleted: villages, families, team, water sources, check-ins, day statuses, complaints and their
events, call sessions, phone lookups, accounts' village links, the activity feed, check-in and
call-back schedules; running workflows are stopped. Kept: every consent-ledger entry
(``VILLAGE#…/CONSENT#…``) and the missed-call log (``MISSED#…``), which are the proof of what
people agreed to and asked for. The call allowlist is reset to the team's TEST_NUMBERS.

    uv run --no-sync python scripts/reset_stage.py --stage dev-<name> [--yes]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

REPO: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from seed_demo import REGION, load_env, parse_numbers, write_allowlist  # noqa: E402

KEEP_SK_PREFIXES: Final = ("CONSENT#",)
KEEP_PK_PREFIXES: Final = ("MISSED#",)


def keep(item: dict[str, Any]) -> bool:
    pk, sk = item["PK"]["S"], item["SK"]["S"]
    return pk.startswith(KEEP_PK_PREFIXES) or (
        pk.startswith("VILLAGE#") and sk.startswith(KEEP_SK_PREFIXES)
    )


def main(argv: Sequence[str] | None = None) -> int:
    env = load_env()
    parser = argparse.ArgumentParser(description="Reset a JalSakshi stage (keeps consent logs).")
    parser.add_argument("--stage", default=env.get("STAGE"))
    parser.add_argument("--profile", default=env.get("AWS_PROFILE"))
    parser.add_argument("--yes", action="store_true", help="actually delete (default: dry run)")
    args = parser.parse_args(argv)
    import boto3

    session = boto3.Session(profile_name=args.profile, region_name=REGION)
    ddb = session.client("dynamodb", region_name=REGION)
    table = f"jalsakshi-{args.stage}"
    doomed: list[dict[str, Any]] = []
    kept = 0
    for page in ddb.get_paginator("scan").paginate(TableName=table, ProjectionExpression="PK, SK"):
        for item in page["Items"]:
            if keep(item):
                kept += 1
            else:
                doomed.append({"PK": item["PK"], "SK": item["SK"]})
    print(f"{table}: delete {len(doomed)} items, keep {kept} audit items")
    if not args.yes:
        print("dry run: pass --yes to delete")
        return 0
    for offset in range(0, len(doomed), 25):
        chunk = [{"DeleteRequest": {"Key": key}} for key in doomed[offset : offset + 25]]
        pending: dict[str, Any] = {table: chunk}
        while pending:
            pending = ddb.batch_write_item(RequestItems=pending).get("UnprocessedItems") or {}
    sfn = session.client("stepfunctions", region_name=REGION)
    account = session.client("sts").get_caller_identity()["Account"]
    stopped = 0
    for slug in ("checkin-run", "ticket-flow"):
        arn = f"arn:aws:states:{REGION}:{account}:stateMachine:jalsakshi-{args.stage}-{slug}"
        for page in sfn.get_paginator("list_executions").paginate(
            stateMachineArn=arn, statusFilter="RUNNING"
        ):
            for execution in page["executions"]:
                sfn.stop_execution(executionArn=execution["executionArn"], cause="stage reset")
                stopped += 1
    scheduler = session.client("scheduler", region_name=REGION)
    removed = 0
    for group in (f"jalsakshi-{args.stage}-checkins", f"jalsakshi-{args.stage}-callbacks"):
        for page in scheduler.get_paginator("list_schedules").paginate(GroupName=group):
            for schedule in page["Schedules"]:
                scheduler.delete_schedule(Name=schedule["Name"], GroupName=group)
                removed += 1
    numbers = parse_numbers(env.get("TEST_NUMBERS"))
    write_allowlist(session.client("ssm", region_name=REGION), args.stage, numbers)
    print(f"deleted {len(doomed)} items, stopped {stopped} workflows, removed {removed} schedules")
    print(f"allowlist reset to {len(set(numbers))} team test phones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
