"""JalSakshi CDK app. Usage (from infra/):

    uv run --no-sync python ../scripts/build_lambda.py     # build the Lambda asset first
    npx aws-cdk@2 synth -c stage=dev-<name>
    npx aws-cdk@2 deploy --all -c stage=dev-<name>

Everything deploys to ap-south-1; the account comes from the CLI profile (CDK_DEFAULT_ACCOUNT).
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "src")]

import aws_cdk as cdk  # noqa: E402
from jalsakshi_infra.app_stack import AppStack  # noqa: E402
from jalsakshi_infra.data_stack import DataStack  # noqa: E402
from jalsakshi_infra.obs_stack import ObsStack  # noqa: E402
from jalsakshi_infra.settings import REGION, StageSettings  # noqa: E402
from jalsakshi_infra.web_stack import WebStack  # noqa: E402


def build(app: cdk.App) -> list[cdk.Stack]:
    """Create the four stacks of one stage."""
    cfg = StageSettings.from_app(app)
    env = cdk.Environment(account=cfg.account, region=REGION)
    data = DataStack(app, cfg.stack_id("Data"), cfg=cfg, env=env)
    web = WebStack(app, cfg.stack_id("Web"), cfg=cfg, env=env)
    main = AppStack(app, cfg.stack_id("App"), cfg=cfg, data=data, web=web, env=env)
    obs = ObsStack(app, cfg.stack_id("Obs"), cfg=cfg, app=main, env=env)
    for key, value in cfg.tags.items():
        cdk.Tags.of(app).add(key, value)
    return [data, web, main, obs]


if __name__ == "__main__":
    application = cdk.App()
    build(application)
    application.synth()
