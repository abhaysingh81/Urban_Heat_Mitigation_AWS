"""
Guard against invented figures: every number in an LLM-written brief must
appear in the facts the tools returned (or the vetted guidance text).
"""

from __future__ import annotations

import re
import unicodedata



def _ascii_digits(text: str) -> str:
    """Digits of any script (Devanagari, Bengali, Tamil, Telugu, Gujarati, Kannada …) as 0-9."""
    return "".join(str(unicodedata.decimal(ch)) if not ch.isascii() and unicodedata.decimal(ch, None) is not None
                   else ch for ch in text)

_LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+", re.M)
_NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)")


def _norm(token: str) -> str:
    t = token.replace(",", "")
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t.lstrip("0") or "0"


def numbers_in(text: str) -> set[str]:
    text = _LIST_MARKER.sub("", _ascii_digits(text))
    return {_norm(m) for m in _NUMBER.findall(text)}


def collect_allowed(*sources) -> set[str]:
    """Numbers from facts (any nested JSON-ish structure) and plain-text sources."""
    allowed: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(k); walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
        elif isinstance(x, bool) or x is None:
            return
        elif isinstance(x, (int, float)):
            allowed.update(_variants(x))
        else:
            allowed.update(numbers_in(str(x)))

    for s in sources:
        walk(s)
    return allowed


def _variants(x) -> set[str]:
    out = {_norm(repr(x)), _norm(f"{x}")}
    if isinstance(x, float):
        for nd in (0, 1, 2):
            out.add(_norm(f"{x:.{nd}f}"))
        out.add(_norm(str(int(abs(x)))))       # truncated magnitude
        out.add(_norm(f"{abs(x):.1f}"))        # sign-stripped (e.g. -1.2 -> 1.2)
        out.add(_norm(f"{abs(x):.2f}"))
    else:
        out.add(_norm(str(abs(int(x)))))
    return out


def find_unsupported(text: str, allowed: set[str]) -> list[str]:
    return sorted(n for n in numbers_in(text) if n not in allowed)
