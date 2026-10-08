"""CDK app synthesizes, and its key resources match the contract (skipped without aws-cdk-lib)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

cdk = pytest.importorskip("aws_cdk")
from aws_cdk.assertions import Match, Template  # noqa: E402

INFRA = Path(__file__).resolve().parents[2] / "infra"


@pytest.fixture(scope="module")
def stacks() -> dict[str, Any]:
    sys.path.insert(0, str(INFRA))
    spec = importlib.util.spec_from_file_location("jalsakshi_cdk_app", INFRA / "app.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = cdk.App(context={"stage": "dev-test", "voice_provider": "vobiz"})
    built = module.build(app)
    return {stack.stack_name.rsplit("-", 1)[1]: stack for stack in built}


def template(stacks: dict[str, Any], name: str) -> Template:
    return Template.from_stack(stacks[name])


def test_stack_names_and_region(stacks: dict[str, Any]) -> None:
    assert set(stacks) == {"Data", "Web", "App", "Obs"}
    assert all(stack.region == "ap-south-1" for stack in stacks.values())


def test_table_matches_store_spec(stacks: dict[str, Any]) -> None:
    t = template(stacks, "Data")
    t.has_resource_properties(
        "AWS::DynamoDB::GlobalTable",
        {
            "TableName": "jalsakshi-dev-test",
            "KeySchema": [
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
            "TimeToLiveSpecification": {"AttributeName": "ttl", "Enabled": True},
            "GlobalSecondaryIndexes": [Match.object_like({"IndexName": "GSI1"})],
            "Replicas": [
                Match.object_like(
                    {"PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True}}
                )
            ],
        },
    )
    t.has_resource_properties("AWS::SSM::Parameter", {"Name": "/jalsakshi/dev-test/prompts_bucket"})


def test_http_api_routes_and_auth(stacks: dict[str, Any]) -> None:
    t = template(stacks, "App")
    routes = t.find_resources("AWS::ApiGatewayV2::Route")
    keys = {r["Properties"]["RouteKey"]: r["Properties"] for r in routes.values()}
    assert set(keys) == {
        "GET /api/{proxy+}",
        "POST /api/{proxy+}",
        "POST /sim/{proxy+}",
        "POST /ivr/vobiz/{token}/{action}",
    }
    assert keys["GET /api/{proxy+}"]["AuthorizationType"] == "JWT"
    assert keys["POST /sim/{proxy+}"]["AuthorizationType"] == "JWT"
    assert keys["POST /ivr/vobiz/{token}/{action}"].get("AuthorizationType", "NONE") == "NONE"


def test_lambdas_are_python312_traced_with_stage_env(stacks: dict[str, Any]) -> None:
    t = template(stacks, "App")
    functions = t.find_resources("AWS::Lambda::Function")
    ours = [f["Properties"] for f in functions.values() if "Handler" in f["Properties"]]
    handlers = {p["Handler"] for p in ours if p["Handler"].startswith("jalsakshi.")}
    assert "jalsakshi.handlers.sfn_tasks.place_call" in handlers
    assert "jalsakshi.handlers.api.handler" in handlers
    assert len(handlers) == 14
    for props in ours:
        if not props["Handler"].startswith("jalsakshi."):
            continue
        assert props["Runtime"] == "python3.12"
        assert props["TracingConfig"] == {"Mode": "Active"}
        env = props["Environment"]["Variables"]
        assert env["JALSAKSHI_REGION"] == "ap-south-1" and env["VOICE_PROVIDER"] == "vobiz"
        assert env["JALSAKSHI_PROMPTS_PATH"] == "/var/task/prompts/hi.yaml"


def test_state_machines_wait_for_tokens_with_heartbeat(stacks: dict[str, Any]) -> None:
    t = template(stacks, "App")
    machines = t.find_resources("AWS::StepFunctions::StateMachine")
    assert len(machines) == 2
    rendered = json.dumps(t.to_json())
    assert "lambda:invoke.waitForTaskToken" in rendered
    assert '\\"HeartbeatSeconds\\":172800' in rendered
    assert '\\"TimeoutSeconds\\":600' in rendered
    assert '\\"JitterStrategy\\":\\"FULL\\"' in rendered
    assert "States.MathAdd($.attempt, 1)" in rendered


def test_bedrock_scoped_to_the_model_chain(stacks: dict[str, Any]) -> None:
    rendered = json.dumps(template(stacks, "App").to_json())
    assert "inference-profile/in.anthropic.claude-haiku-4-5-20251001-v1:0" in rendered
    assert "foundation-model/amazon.nova-2-lite-v1:0" in rendered


def test_cognito_client_is_public_pkce(stacks: dict[str, Any]) -> None:
    t = template(stacks, "Web")
    t.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {
            "GenerateSecret": False,
            "AllowedOAuthFlows": ["code"],
            "EnableTokenRevocation": True,
        },
    )
    t.resource_count_is("AWS::Cognito::UserPoolGroup", 5)


def test_dashboard_and_dlq_alarms(stacks: dict[str, Any]) -> None:
    t = template(stacks, "Obs")
    t.has_resource_properties("AWS::CloudWatch::Dashboard", {"DashboardName": "JalSakshi-dev-test"})
    t.resource_count_is("AWS::CloudWatch::Alarm", 4)
