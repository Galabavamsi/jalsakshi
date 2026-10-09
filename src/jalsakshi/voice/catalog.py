"""Hindi prompt catalog: loads ``prompts/hi.yaml``, formats prompts and names their audio clips.

Keys are dotted paths into the YAML, such as ``household.q_water``. A prompt with one placeholder
(``{households}``) is pre-rendered for the values 1 to 9 under variant keys such as
``operator.summary_no_supply.n3``. Any other value still gets text, but no audio clip, so a phone
adapter has to fall back to text-to-speech for it.

Small whole numbers are spoken as Hindi words ("teen", not "3"), matching the rest of the catalog.
"""

from __future__ import annotations

import os
import re
import string
from collections.abc import Iterator, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROMPTS_PATH_ENV = "JALSAKSHI_PROMPTS_PATH"
DEFAULT_PROMPTS_PATH = Path(__file__).resolve().parents[3] / "prompts" / "hi.yaml"
VARIANT_VALUES = range(1, 10)
HINDI_NUMBER_WORDS = (
    "shunya",
    "ek",
    "do",
    "teen",
    "chaar",
    "paanch",
    "chhah",
    "saat",
    "aath",
    "nau",
)

_META_KEYS = frozenset({"version", "language", "numbers"})
_VARIANT_KEY = re.compile(r"^(?P<base>[a-z0-9_.]+)\.n(?P<n>[1-9])$")
_SAFE_KEY = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")


class PromptCatalog:
    """Prompt texts by dotted key, with the rules for naming pre-rendered audio clips."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        self.version = int(data.get("version", 0))
        self.language = str(data.get("language", "hi-IN"))
        numbers = data.get("numbers")
        self.number_words: tuple[str, ...] = (
            tuple(str(n) for n in numbers)
            if isinstance(numbers, list) and len(numbers) == 10
            else HINDI_NUMBER_WORDS
        )
        self._templates: dict[str, str] = dict(_flatten(data, prefix="", top=True))
        if not self._templates:
            raise ValueError("prompt catalog has no prompts")

    @classmethod
    def from_file(cls, path: Path | str) -> PromptCatalog:
        """Load a catalog from a YAML file."""
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, Mapping):
            raise ValueError(f"{path}: expected a mapping at the top level")
        return cls(data)

    def template_keys(self) -> list[str]:
        """All template keys, in file order (no variants)."""
        return list(self._templates)

    def template(self, key_path: str) -> str:
        """Raw template text for a key; raises KeyError for an unknown key."""
        try:
            return self._templates[key_path]
        except KeyError:
            raise KeyError(f"unknown prompt key: {key_path!r}") from None

    def placeholders(self, key_path: str) -> tuple[str, ...]:
        """Names of the ``{placeholders}`` in a template, in order."""
        return _placeholders(self.template(key_path))

    def text(self, key_path: str, **variables: object) -> str:
        """Formatted prompt text. Accepts template keys and variant keys (``....n3``)."""
        base, variables = self._resolve(key_path, variables)
        names = set(self.placeholders(base))
        missing = names - variables.keys()
        if missing:
            raise KeyError(f"prompt {base!r} needs {sorted(missing)}")
        extra = variables.keys() - names
        if extra:
            raise ValueError(f"prompt {base!r} does not take {sorted(extra)}")
        spoken = {name: spoken_value(value, self.number_words) for name, value in variables.items()}
        return self.template(base).format(**spoken)

    def audio_key(self, key_path: str, **variables: object) -> str | None:
        """Key of the pre-rendered clip for this prompt and these values, or None."""
        if key_path not in self._templates:
            return key_path if not variables and self.has_audio(key_path) else None
        names = self.placeholders(key_path)
        if not names:
            return key_path
        if len(names) != 1:
            return None
        value = variables.get(names[0])
        if isinstance(value, int) and not isinstance(value, bool) and value in VARIANT_VALUES:
            return f"{key_path}.n{value}"
        return None

    def has_audio(self, key: str) -> bool:
        """True if ``key`` names a clip that ``audio_keys()`` would render."""
        match = _VARIANT_KEY.match(key)
        if key in self._templates:
            return not self.placeholders(key)
        if match and match["base"] in self._templates:
            return len(self.placeholders(match["base"])) == 1
        return False

    def audio_keys(self) -> list[str]:
        """Every clip to pre-render: plain prompts plus n1..n9 variants of one-variable ones."""
        keys: list[str] = []
        for key in self._templates:
            names = self.placeholders(key)
            if not names:
                keys.append(key)
            elif len(names) == 1:
                keys.extend(f"{key}.n{n}" for n in VARIANT_VALUES)
        return keys

    def render_items(self) -> list[tuple[str, str]]:
        """``(audio_key, text)`` for every clip to pre-render."""
        return [(key, self.text(key)) for key in self.audio_keys()]

    def _resolve(
        self, key_path: str, variables: dict[str, object]
    ) -> tuple[str, dict[str, object]]:
        """Map a variant key to its template key and fill in the variant's value."""
        if key_path in self._templates:
            return key_path, variables
        match = _VARIANT_KEY.match(key_path)
        if not match or match["base"] not in self._templates:
            raise KeyError(f"unknown prompt key: {key_path!r}")
        base = match["base"]
        names = self.placeholders(base)
        if len(names) != 1:
            raise KeyError(f"prompt {base!r} has no numbered variants")
        return base, {**variables, names[0]: int(match["n"])}


def spoken_value(value: object, words: tuple[str, ...] = HINDI_NUMBER_WORDS) -> str:
    """How a value is read out: 0..9 as number words of the catalog, everything else as text."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 9:
        return words[value]
    return str(value)


def audio_url(key: str, base_url: str) -> str:
    """Public URL of a pre-rendered clip: ``{base_url}/{key}.mp3``."""
    if not _SAFE_KEY.match(key):
        raise ValueError(f"not a prompt key: {key!r}")
    return f"{base_url.rstrip('/')}/{key}.mp3"


def prompts_path() -> Path:
    """Catalog location: ``$JALSAKSHI_PROMPTS_PATH`` or ``prompts/hi.yaml`` in the repo."""
    return Path(os.environ.get(PROMPTS_PATH_ENV) or DEFAULT_PROMPTS_PATH)


@lru_cache(maxsize=1)
def default_catalog() -> PromptCatalog:
    """The process-wide catalog, loaded once (call ``default_catalog.cache_clear()`` to reload)."""
    return PromptCatalog.from_file(prompts_path())


CALL_LANGUAGES: dict[str, tuple[str, str]] = {
    "hi": ("Hindi", "hi-IN"),
    "hne": ("Chhattisgarhi", "hi-IN"),
    "te": ("Telugu", "te-IN"),
    "mr": ("Marathi", "mr-IN"),
    "or": ("Odia", "od-IN"),
    "bn": ("Bengali", "bn-IN"),
    "gu": ("Gujarati", "gu-IN"),
    "kn": ("Kannada", "kn-IN"),
    "ml": ("Malayalam", "ml-IN"),
    "pa": ("Punjabi", "pa-IN"),
    "ta": ("Tamil", "ta-IN"),
}
"""Call languages: code -> (English name, Sarvam voice language). Chhattisgarhi is read by the
Hindi voice (same script); a language works on calls once ``prompts/{code}.yaml`` exists."""

DEFAULT_LANGUAGE = "hi"


def available_languages() -> list[str]:
    """Call languages that have a prompt file next to the default catalog."""
    folder = prompts_path().parent
    return [code for code in CALL_LANGUAGES if (folder / f"{code}.yaml").is_file()]


@lru_cache(maxsize=16)
def catalog_for(language: str | None) -> PromptCatalog:
    """The prompt catalog of a call language (the default Hindi catalog when it has none)."""
    code = (language or DEFAULT_LANGUAGE).strip().lower()
    if code == DEFAULT_LANGUAGE:
        return default_catalog()
    path = prompts_path().parent / f"{code}.yaml"
    return PromptCatalog.from_file(path) if path.is_file() else default_catalog()


def audio_base_for(base_url: str | None, language: str | None) -> str | None:
    """Clip base URL of a language: ``…/prompts/hi`` becomes ``…/prompts/{code}``."""
    code = (language or DEFAULT_LANGUAGE).strip().lower()
    if not base_url or code == DEFAULT_LANGUAGE or catalog_for(code) is default_catalog():
        return base_url
    root, _, last = base_url.rstrip("/").rpartition("/")
    return f"{root}/{code}" if last == DEFAULT_LANGUAGE else base_url


def sarvam_language(language: str | None) -> str:
    """Sarvam voice language for a call language (Hindi for unknown codes)."""
    return CALL_LANGUAGES.get((language or DEFAULT_LANGUAGE).lower(), ("", "hi-IN"))[1]


def prompt(key_path: str, **variables: object) -> str:
    """Formatted text of a prompt from the default catalog."""
    return default_catalog().text(key_path, **variables)


def _placeholders(template: str) -> tuple[str, ...]:
    names = [name for _, name, _, _ in string.Formatter().parse(template) if name]
    return tuple(dict.fromkeys(names))


def _flatten(node: Mapping[str, Any], prefix: str, top: bool) -> Iterator[tuple[str, str]]:
    for raw_key, value in node.items():
        key = str(raw_key)
        if top and key in _META_KEYS:
            continue
        path = f"{prefix}{key}"
        if not _SAFE_KEY.match(path):
            raise ValueError(f"prompt key must be lowercase a-z, 0-9 or _: {path!r}")
        if isinstance(value, Mapping):
            yield from _flatten(value, prefix=f"{path}.", top=False)
        elif isinstance(value, str):
            yield path, value
        else:
            raise ValueError(f"prompt {path!r} must be text, got {type(value).__name__}")
