"""The Cedar policy file parses, validates against its schema and names every rule."""

from __future__ import annotations

import json

import cedarpy

from jalsakshi.policy.engine import POLICY_FILE, SCHEMA_FILE, read_policy_file
from jalsakshi.policy.reasons import ALLOW_BY_DEFAULT_ID, REASONS, PolicyId


def _annotated_policies() -> list[tuple[str, str | None]]:
    """(effect, @id) for every static policy in the file, in file order."""
    est = json.loads(cedarpy.policies_to_json_str(read_policy_file(POLICY_FILE)))
    return [
        (policy["effect"], policy.get("annotations", {}).get("id"))
        for policy in est["staticPolicies"].values()
    ]


def test_policy_file_parses() -> None:
    policy_set = cedarpy.PolicySet.from_str(read_policy_file(POLICY_FILE))
    assert len(policy_set) == 1 + len(PolicyId)


def test_policies_validate_against_schema() -> None:
    schema = cedarpy.Schema.from_str(read_policy_file(SCHEMA_FILE))
    result = cedarpy.validate_policies(read_policy_file(POLICY_FILE), schema)
    assert result.validation_passed, [str(error) for error in result.errors]


def test_single_permit_is_the_default_allow() -> None:
    permits = [pid for effect, pid in _annotated_policies() if effect == "permit"]
    assert permits == [ALLOW_BY_DEFAULT_ID]


def test_every_forbid_is_a_known_policy_id_in_order() -> None:
    forbids = [pid for effect, pid in _annotated_policies() if effect == "forbid"]
    assert forbids == [pid.value for pid in PolicyId]


def test_every_forbid_has_a_reason() -> None:
    for effect, pid in _annotated_policies():
        if effect == "forbid":
            assert pid in REASONS
