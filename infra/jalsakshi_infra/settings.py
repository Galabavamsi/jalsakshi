"""Per-stage settings read from CDK context (``-c stage=dev-x``) with safe defaults."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import aws_cdk as cdk

REGION: Final = "ap-south-1"
REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_LAMBDA_ASSET: Final = REPO_ROOT / "build" / "lambda"
DEFAULT_WEB_DIST: Final = REPO_ROOT / "web" / "dist"
BUILD_MARKER: Final = ".jalsakshi-build.json"
_STAGE = re.compile(r"^[a-z][a-z0-9-]{1,23}$")


@dataclass(frozen=True, slots=True)
class StageSettings:
    """Everything that differs between stages (``dev-vamsi``, ``dev-varun``, ``demo``)."""

    stage: str
    account: str | None = None
    voice_provider: str = "simulator"
    escalation_hours: float = 48.0
    retry_wait_minutes: int = 30
    call_timeout_minutes: int = 10
    fix_timeout_days: int = 14
    max_verify_rounds: int = 2
    map_concurrency: int = 5
    brief_use_agent: bool = True
    alarm_email: str | None = None
    auth_domain_prefix: str | None = None
    ivr_allowed_cidrs: str = ""
    local_origins: tuple[str, ...] = ("http://localhost:5173",)
    lambda_asset: Path = DEFAULT_LAMBDA_ASSET
    web_dist: Path = DEFAULT_WEB_DIST
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def is_dev(self) -> bool:
        """Developer stages are disposable: tables and buckets are destroyed with the stack."""
        return self.stage.startswith("dev")

    @property
    def removal_policy(self) -> cdk.RemovalPolicy:
        """DESTROY on dev stages, RETAIN elsewhere."""
        return cdk.RemovalPolicy.DESTROY if self.is_dev else cdk.RemovalPolicy.RETAIN

    @property
    def table_name(self) -> str:
        """DynamoDB single table (ARCHITECTURE.md §8)."""
        return f"jalsakshi-{self.stage}"

    def name(self, suffix: str) -> str:
        """Physical name for a stage resource, e.g. ``jalsakshi-dev-x-ticket-flow``."""
        return f"jalsakshi-{self.stage}-{suffix}"

    def stack_id(self, suffix: str) -> str:
        """CloudFormation stack name, e.g. ``JalSakshi-dev-x-App``."""
        return f"JalSakshi-{self.stage}-{suffix}"

    @property
    def ssm_prefix(self) -> str:
        """Parameter Store path for this stage's secrets."""
        return f"/jalsakshi/{self.stage}/"

    @property
    def lambda_asset_built(self) -> bool:
        """True when scripts/build_lambda.py has produced the Lambda asset."""
        return (self.lambda_asset / BUILD_MARKER).is_file()

    @classmethod
    def from_app(cls, app: cdk.App) -> StageSettings:
        """Read ``-c key=value`` context; the stage falls back to $STAGE, then ``dev``."""

        def ctx(key: str, default: Any = None) -> Any:
            value = app.node.try_get_context(key)
            return default if value is None or value == "" else value

        stage = str(ctx("stage", os.environ.get("STAGE", "dev")))
        if not _STAGE.match(stage):
            raise ValueError(f"stage must match {_STAGE.pattern}, got {stage!r}")
        provider = str(ctx("voice_provider", "simulator")).lower()
        if provider not in {"simulator", "vobiz"}:
            raise ValueError("voice_provider must be simulator or vobiz")
        origins = str(ctx("local_origins", "http://localhost:5173"))
        return cls(
            stage=stage,
            account=os.environ.get("CDK_DEFAULT_ACCOUNT") or None,
            voice_provider=provider,
            escalation_hours=float(ctx("escalation_hours", 48)),
            retry_wait_minutes=int(ctx("retry_wait_minutes", 30)),
            call_timeout_minutes=int(ctx("call_timeout_minutes", 10)),
            brief_use_agent=str(ctx("brief_use_agent", "true")).lower() == "true",
            alarm_email=ctx("alarm_email"),
            auth_domain_prefix=ctx("auth_domain_prefix"),
            ivr_allowed_cidrs=str(ctx("ivr_allowed_cidrs", "")),
            local_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
            lambda_asset=Path(ctx("lambda_asset", str(DEFAULT_LAMBDA_ASSET))),
            web_dist=Path(ctx("web_dist", str(DEFAULT_WEB_DIST))),
            tags={"project": "jalsakshi", "stage": stage},
        )
