"""Pure helpers for stock-footage search queries and clip durations."""
import re

_ABSTRACT_SHOT_WORDS = {
    "paradox",
    "cruelty",
    "hides",
    "meaning",
    "truth",
    "story",
    "stories",
    "video",
    "clip",
    "clips",
    "tone",
    "mystery",
    "secret",
    "secrets",
    "power",
    "idea",
    "concept",
    "theme",
    "narration",
    "script",
    "documentary",
    "viral",
    "hook",
    "reveal",
    "message",
    "fact",
    "facts",
    "information",
}

def sanitize_shot_query(text: str) -> str:
    raw = re.split(r"\s+[—\-–]\s+", str(text or "").strip(), maxsplit=1)[0]
    words = re.findall(r"[A-Za-z][A-Za-z\-']{1,}", raw)
    kept: list[str] = []
    skip = {"the", "and", "of", "a", "an", "for", "with", "from"}
    for word in words:
        low = word.lower().strip("-'")
        if not low or low in skip or low in _ABSTRACT_SHOT_WORDS:
            continue
        if low not in kept:
            kept.append(low)
        if len(kept) >= 5:
            break
    if len(kept) < 2:
        return ""
    return " ".join(kept)

_BEAT_SECONDS = {
    "hook": 1.8,
    "reaction": 1.6,
    "reveal": 2.0,
    "payoff": 1.8,
    "confrontation": 2.2,
    "tension": 2.4,
    "curiosity": 2.6,
    "setup": 2.8,
}

def clamp_shot_seconds(value: object, beat: str = "") -> float:
    try:
        seconds = float(str(value).replace("s", "").strip())
    except (TypeError, ValueError):
        seconds = _BEAT_SECONDS.get((beat or "").strip().lower(), 2.4)
    return max(1.2, min(4.0, seconds))
