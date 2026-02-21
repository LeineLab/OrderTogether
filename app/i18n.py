import json
from pathlib import Path
from typing import Callable

SUPPORTED_LANGUAGES = ["de", "en"]
DEFAULT_LANGUAGE = "en"
_LOCALES_DIR = Path(__file__).parent / "locales"

_translations: dict[str, dict[str, str]] = {}


def _load() -> None:
    for lang in SUPPORTED_LANGUAGES:
        with open(_LOCALES_DIR / f"{lang}.json", encoding="utf-8") as f:
            _translations[lang] = json.load(f)


_load()


def detect_language(accept_language: str) -> str:
    """Pick the best supported language from an Accept-Language header value."""
    if not accept_language:
        return DEFAULT_LANGUAGE
    langs: list[tuple[str, float]] = []
    for part in accept_language.split(","):
        part = part.strip()
        if ";q=" in part:
            tag, q = part.split(";q=", 1)
            try:
                langs.append((tag.strip(), float(q)))
            except ValueError:
                langs.append((tag.strip(), 0.0))
        else:
            langs.append((part, 1.0))
    langs.sort(key=lambda x: x[1], reverse=True)
    for tag, _ in langs:
        tag = tag.lower()
        if tag in SUPPORTED_LANGUAGES:
            return tag
        prefix = tag.split("-")[0]
        if prefix in SUPPORTED_LANGUAGES:
            return prefix
    return DEFAULT_LANGUAGE


def get_translator(lang: str) -> Callable[..., str]:
    """Return a translation callable ``_(key, **fmt)`` for the given language."""
    table = _translations.get(lang, {})
    fallback = _translations.get(DEFAULT_LANGUAGE, {})

    def _(key: str, **fmt) -> str:
        text = table.get(key) or fallback.get(key, key)
        return text.format(**fmt) if fmt else text

    return _
