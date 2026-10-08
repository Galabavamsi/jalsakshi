from pathlib import Path

import yaml

import jalsakshi


def test_package_imports():
    assert jalsakshi.__version__


def test_prompt_catalog_has_required_keys():
    catalog = yaml.safe_load((Path(__file__).parents[1] / "prompts" / "hi.yaml").read_text("utf-8"))
    for key in ("greet", "q_water", "q_hours", "q_clean", "bye"):
        assert catalog["household"][key]
    assert "{households}" in catalog["operator"]["summary_no_supply"]
