"""Prompt catalog: loading, formatting, numbered variants and audio naming."""

from pathlib import Path

import pytest

from jalsakshi.voice import catalog as catalog_module
from jalsakshi.voice.catalog import (
    PromptCatalog,
    audio_url,
    default_catalog,
    prompt,
    spoken_value,
)

REPO_CATALOG = Path(__file__).resolve().parents[2] / "prompts" / "hi.yaml"


@pytest.fixture
def cat() -> PromptCatalog:
    return PromptCatalog.from_file(REPO_CATALOG)


def test_loads_repo_catalog(cat: PromptCatalog) -> None:
    assert cat.version == 1
    assert cat.language == "hi-IN"
    assert "household.q_water" in cat.template_keys()
    assert "version" not in cat.template_keys()


def test_plain_prompt_text(cat: PromptCatalog) -> None:
    assert cat.text("household.q_water").startswith("Aaj nal mein paani aaya?")


def test_variable_prompt_uses_hindi_number_words(cat: PromptCatalog) -> None:
    text = cat.text("operator.summary_no_supply", households=3)
    assert text == "Aaj gaon ke teen gharon ne bataya ki nal mein paani nahi aaya."


def test_large_counts_stay_digits(cat: PromptCatalog) -> None:
    assert "12 gharon" in cat.text("operator.summary_dirty", households=12)


def test_variant_key_text_matches_formatted_template(cat: PromptCatalog) -> None:
    variant = cat.text("operator.summary_no_supply.n3")
    assert variant == cat.text("operator.summary_no_supply", households=3)


@pytest.mark.parametrize("n", range(1, 10))
def test_audio_key_for_counts_one_to_nine(cat: PromptCatalog, n: int) -> None:
    key = cat.audio_key("operator.summary_dirty", households=n)
    assert key == f"operator.summary_dirty.n{n}"
    assert cat.has_audio(key)


@pytest.mark.parametrize("value", [0, 10, 12, True, "3", None])
def test_no_audio_key_outside_one_to_nine(cat: PromptCatalog, value: object) -> None:
    assert cat.audio_key("operator.summary_no_supply", households=value) is None


def test_audio_key_of_plain_prompt_is_itself(cat: PromptCatalog) -> None:
    assert cat.audio_key("household.bye") == "household.bye"
    assert cat.audio_key("operator.summary_no_supply.n4") == "operator.summary_no_supply.n4"


def test_audio_keys_cover_plain_prompts_and_variants(cat: PromptCatalog) -> None:
    keys = cat.audio_keys()
    templated = [k for k in cat.template_keys() if cat.placeholders(k)]
    plain = [k for k in cat.template_keys() if not cat.placeholders(k)]
    assert templated == ["operator.summary_no_supply", "operator.summary_dirty"]
    assert len(keys) == len(plain) + 9 * len(templated)
    assert "operator.summary_no_supply" not in keys
    assert {f"operator.summary_no_supply.n{n}" for n in range(1, 10)} <= set(keys)
    assert len(set(keys)) == len(keys)


def test_has_audio(cat: PromptCatalog) -> None:
    assert cat.has_audio("household.greet")
    assert not cat.has_audio("operator.summary_no_supply")
    assert not cat.has_audio("household.greet.n3")
    assert not cat.has_audio("nope.key")


def test_render_items_are_formatted(cat: PromptCatalog) -> None:
    items = dict(cat.render_items())
    assert items["operator.summary_dirty.n9"].startswith("Aaj gaon ke nau gharon")
    assert all("{" not in text for text in items.values())


def test_missing_variable_raises(cat: PromptCatalog) -> None:
    with pytest.raises(KeyError, match="households"):
        cat.text("operator.summary_no_supply")


def test_unexpected_variable_raises(cat: PromptCatalog) -> None:
    with pytest.raises(ValueError, match="does not take"):
        cat.text("household.bye", households=2)


@pytest.mark.parametrize("key", ["household.nope", "operator.summary_no_supply.n0", "x.n3"])
def test_unknown_key_raises(cat: PromptCatalog, key: str) -> None:
    with pytest.raises(KeyError):
        cat.text(key)


def test_two_placeholder_prompt_gets_no_variants() -> None:
    cat = PromptCatalog({"a": {"pair": "{x} and {y}", "one": "only {x}"}})
    assert cat.audio_keys() == [f"a.one.n{n}" for n in range(1, 10)]
    assert cat.audio_key("a.pair", x=1, y=2) is None
    with pytest.raises(KeyError, match="no numbered variants"):
        cat.text("a.pair.n2")


@pytest.mark.parametrize(
    "data",
    [{"a": {"b": 3}}, {"A": "text"}, {"a b": "text"}, {}, {"version": 1}],
)
def test_invalid_catalogs_rejected(data: dict) -> None:
    with pytest.raises(ValueError):
        PromptCatalog(data)


def test_from_file_rejects_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        PromptCatalog.from_file(path)


def test_spoken_value() -> None:
    assert spoken_value(0) == "shunya"
    assert spoken_value(9) == "nau"
    assert spoken_value(10) == "10"
    assert spoken_value(True) == "True"
    assert spoken_value("x") == "x"


def test_audio_url() -> None:
    assert audio_url("household.q_water", "https://cdn.example/prompts/hi/") == (
        "https://cdn.example/prompts/hi/household.q_water.mp3"
    )
    assert audio_url("operator.summary_dirty.n2", "s3x").endswith("summary_dirty.n2.mp3")


@pytest.mark.parametrize("key", ["../etc/passwd", "a/b", "Upper.key", "", "a..b"])
def test_audio_url_rejects_unsafe_keys(key: str) -> None:
    with pytest.raises(ValueError):
        audio_url(key, "https://cdn.example")


def test_default_catalog_and_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "custom.yaml"
    custom.write_text('version: 7\nlanguage: hi-IN\nx:\n  hello: "Namaste"\n', encoding="utf-8")
    monkeypatch.setenv(catalog_module.PROMPTS_PATH_ENV, str(custom))
    default_catalog.cache_clear()
    try:
        assert default_catalog().version == 7
        assert prompt("x.hello") == "Namaste"
    finally:
        monkeypatch.delenv(catalog_module.PROMPTS_PATH_ENV)
        default_catalog.cache_clear()
    assert default_catalog().version == 1
