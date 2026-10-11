"""
Regional-language text (Feature H: Amazon Translate).

Machine translation of the short advisory and the officer brief into six Indian languages.
Off unless TRANSLATE_ENABLED=true (set by the AWS deployment); every caller treats None as
"show the original". Results are cached for the life of the process: the advisory is one of
four fixed sentences, so a warm Lambda rarely calls the service twice for the same text.

Amazon Polly has no voice for these six languages, so audio stays Hindi and Indian English.
"""

from __future__ import annotations

import os

from api import aws

LANGUAGES = {"mr": "मराठी", "bn": "বাংলা", "ta": "தமிழ்", "te": "తెలుగు", "gu": "ગુજરાતી", "kn": "ಕನ್ನಡ"}
ENGLISH_NAMES = {"mr": "Marathi", "bn": "Bengali", "ta": "Tamil", "te": "Telugu", "gu": "Gujarati", "kn": "Kannada"}
# the main regional language of each real-data city (Delhi and Jaipur are served by Hindi)
CITY_LANGUAGE = {"mumbai": "mr", "bengaluru": "kn"}
MAX_CHARS = 5000  # well under the service limit (10,000 bytes per request)

_cache: dict[tuple[str, str], str] = {}


def enabled() -> bool:
    return os.environ.get("TRANSLATE_ENABLED", "").lower() == "true"


def languages() -> list[dict]:
    return [{"code": c, "name": n, "english_name": ENGLISH_NAMES[c]} for c, n in LANGUAGES.items()] \
        if enabled() else []


def translate(text: str, target: str, source: str = "en") -> str | None:
    """`text` in the target language, or None when translation is off, unsupported or fails."""
    if not enabled() or target not in LANGUAGES or not text or len(text) > MAX_CHARS:
        return None
    key = (target, text)
    if key not in _cache:
        try:
            res = aws.client("translate").translate_text(
                Text=text, SourceLanguageCode=source, TargetLanguageCode=target)
            if len(_cache) > 500:
                _cache.clear()
            _cache[key] = res["TranslatedText"]
        except Exception as e:
            print(f"translate failed ({target}): {type(e).__name__}")
            return None
    return _cache[key]
