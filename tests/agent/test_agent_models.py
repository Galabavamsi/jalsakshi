"""Model factory and fallback chain (no network: BedrockModel only builds a boto3 client)."""

from __future__ import annotations

import pytest
from agent_fakes import ScriptedFactory

from jalsakshi.agent import models as agent_models
from jalsakshi.agent.models import (
    MODEL_CHAIN,
    AllModelsFailed,
    agent_region,
    make_model,
    model_chain,
    new_agent,
    run_with_fallback,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JALSAKSHI_REGION", raising=False)
    monkeypatch.delenv("JALSAKSHI_MODEL_CHAIN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)  # a missing profile would fail Session()
    monkeypatch.delenv("AWS_DEFAULT_PROFILE", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-east-1")  # the shell default we must ignore


def test_model_chain_is_haiku_then_nova() -> None:
    assert MODEL_CHAIN == (
        "in.anthropic.claude-haiku-4-5-20251001-v1:0",
        "global.amazon.nova-2-lite-v1:0",
    )
    assert model_chain() == MODEL_CHAIN


def test_model_chain_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JALSAKSHI_MODEL_CHAIN", " a , b ,")
    assert model_chain() == ("a", "b")


def test_region_defaults_to_mumbai_not_aws_region(monkeypatch: pytest.MonkeyPatch) -> None:
    assert agent_region() == "ap-south-1"
    monkeypatch.setenv("JALSAKSHI_REGION", "ap-south-2")
    assert agent_region() == "ap-south-2"


def test_make_model_is_explicit_and_deterministic() -> None:
    model = make_model(MODEL_CHAIN[0], max_tokens=777)
    config = model.get_config()
    assert config["model_id"] == MODEL_CHAIN[0]
    assert config["temperature"] == 0
    assert config["max_tokens"] == 777
    assert model.client.meta.region_name == "ap-south-1"
    assert model.client.meta.config.read_timeout == agent_models.READ_TIMEOUT_S
    assert model.client.meta.config.connect_timeout == agent_models.CONNECT_TIMEOUT_S


def test_make_model_uses_given_region() -> None:
    model = make_model(MODEL_CHAIN[1], "ap-south-1", read_timeout_s=12)
    assert model.client.meta.region_name == "ap-south-1"
    assert model.client.meta.config.read_timeout == 12


def test_new_agent_is_quiet_and_has_only_given_tools() -> None:
    factory = ScriptedFactory(["hello"])
    agent = new_agent(factory("m", "ap-south-1"), name="t", system_prompt="be brief")
    assert agent.tool_names == []
    assert str(agent("hi")).strip() == "hello"


def _echo_call(agent: object) -> str:
    return str(agent("go")).strip()  # type: ignore[operator]


def test_first_model_wins() -> None:
    factory = ScriptedFactory(["first"])
    result = run_with_fallback(
        lambda m: new_agent(m, name="t", system_prompt="s"), _echo_call, model_factory=factory
    )
    assert result == ("first", MODEL_CHAIN[0])
    assert factory.calls == [(MODEL_CHAIN[0], "ap-south-1")]


def test_falls_back_to_next_model_on_error() -> None:
    factory = ScriptedFactory([RuntimeError("throttled")], ["second"])
    result = run_with_fallback(
        lambda m: new_agent(m, name="t", system_prompt="s"), _echo_call, model_factory=factory
    )
    assert result == ("second", MODEL_CHAIN[1])
    assert [mid for mid, _ in factory.calls] == list(MODEL_CHAIN)


def test_call_can_reject_an_answer_to_move_on() -> None:
    def picky(agent: object) -> str:
        text = _echo_call(agent)
        if text == "bad":
            raise ValueError("rejected")
        return text

    factory = ScriptedFactory(["bad"], ["good"])
    result = run_with_fallback(
        lambda m: new_agent(m, name="t", system_prompt="s"), picky, model_factory=factory
    )
    assert result == ("good", MODEL_CHAIN[1])


def test_all_models_failed_lists_every_error() -> None:
    factory = ScriptedFactory([RuntimeError("a")], [TimeoutError("b")])
    with pytest.raises(AllModelsFailed) as info:
        run_with_fallback(
            lambda m: new_agent(m, name="t", system_prompt="s"), _echo_call, model_factory=factory
        )
    assert [(mid, type(exc)) for mid, exc in info.value.errors] == [
        (MODEL_CHAIN[0], RuntimeError),
        (MODEL_CHAIN[1], TimeoutError),
    ]


def test_factory_and_build_errors_also_fall_back() -> None:
    def broken_factory(model_id: str, region: str) -> object:
        raise PermissionError(f"no access to {model_id} in {region}")

    with pytest.raises(AllModelsFailed):
        run_with_fallback(lambda m: m, _echo_call, model_factory=broken_factory)  # type: ignore[arg-type]


def test_explicit_model_ids_and_region() -> None:
    factory = ScriptedFactory(["ok"])
    _, model_id = run_with_fallback(
        lambda m: new_agent(m, name="t", system_prompt="s"),
        _echo_call,
        model_ids=["only-this"],
        region="ap-south-1",
        model_factory=factory,
    )
    assert model_id == "only-this"
    assert factory.calls == [("only-this", "ap-south-1")]
