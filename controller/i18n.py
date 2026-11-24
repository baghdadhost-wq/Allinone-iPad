"""Two-language messages (Arabic / English).

Every user-facing string is written as tr("English", "العربية") right where it
is used, so the code stays readable and adding a translation never needs a
separate key table.
"""

from __future__ import annotations

_LANG = "ar"
SUPPORTED = ("ar", "en")


def set_language(lang: str) -> None:
    global _LANG
    if lang in SUPPORTED:
        _LANG = lang


def language() -> str:
    return _LANG


def tr(en: str, ar: str, **kwargs) -> str:
    text = ar if _LANG == "ar" else en
    return text.format(**kwargs) if kwargs else text
