"""Pull music mood words and foley events from a narration script."""

from __future__ import annotations

import re
from collections import Counter

_WORD = re.compile(r"[a-z0-9']+", re.IGNORECASE)

# word -> music mood
_MUSIC_MOOD = {
    "spy": "tense",
    "secret": "tense",
    "thief": "tense",
    "steal": "tense",
    "ninja": "tense",
    "hidden": "tense",
    "hide": "tense",
    "undercover": "tense",
    "cia": "tense",
    "agent": "tense",
    "prison": "tense",
    "escape": "tense",
    "hunt": "tense",
    "stalk": "tense",
    "trap": "tense",
    "danger": "tense",
    "deadly": "tense",
    "surgery": "curious",
    "doctor": "curious",
    "hospital": "curious",
    "medical": "curious",
    "body": "curious",
    "skin": "curious",
    "tongue": "curious",
    "tooth": "curious",
    "virus": "curious",
    "science": "curious",
    "explain": "curious",
    "how": "curious",
    "works": "curious",
    "brain": "curious",
    "muscle": "curious",
    "organ": "curious",
    "war": "epic",
    "battle": "epic",
    "soldier": "epic",
    "army": "epic",
    "bomb": "epic",
    "bullet": "epic",
    "survive": "epic",
    "hero": "epic",
    "fight": "epic",
    "lion": "epic",
    "tiger": "epic",
    "funny": "playful",
    "joke": "playful",
    "prank": "playful",
    "silly": "playful",
    "weird": "playful",
    "laugh": "playful",
    "ocean": "calm",
    "sleep": "calm",
    "quiet": "calm",
    "peace": "calm",
    "gentle": "calm",
    "slow": "calm",
    "night": "calm",
    "death": "dark",
    "blood": "dark",
    "kill": "dark",
    "horror": "dark",
    "fear": "dark",
    "evil": "dark",
    "jungle": "nature",
    "forest": "nature",
    "snake": "nature",
    "mountain": "nature",
    "river": "nature",
    "animal": "nature",
}

_MUSIC_SETTING = {
    "city",
    "street",
    "school",
    "house",
    "desert",
    "space",
    "underwater",
    "cave",
    "roof",
    "log",
    "bag",
    "camera",
    "vest",
    "armor",
    "lab",
    "church",
    "temple",
    "ship",
    "plane",
    "train",
}

_MUSIC_BEDS = {
    "cinematic": "cinematic documentary underscore, soft strings and a low pulse, instrumental, no vocals",
    "tense": "dark tense spy thriller underscore, low drones and subtle percussion, instrumental, no vocals",
    "curious": "curious science explainer background, light pizzicato and soft synth, instrumental, no vocals",
    "playful": "quirky playful short-form background, light bounce, instrumental, no vocals",
    "calm": "calm ambient pad background, gentle and unobtrusive, instrumental, no vocals",
    "epic": "epic cinematic drums and brass, trailer energy, instrumental, no vocals",
    "dark": "dark ominous drone and distant hits, instrumental, no vocals",
    "nature": "earthy documentary bed, soft percussion and airy tones, instrumental, no vocals",
}

_SFX_EVENTS: tuple[tuple[str, str, str], ...] = (
    (r"\b(rain|raining|storm|thunder|downpour)\b", "rain", "heavy rain and distant thunder, nature sound effect"),
    (r"\b(gunshot|gun\s*shot|gunfire|rifle)\b", "gunshot", "loud gunshot impact, foley"),
    (r"\b(bullet|bullets)\b", "bullet", "bullet fly-by and impact, foley"),
    (r"\b(explosion|explode|bomb|blast)\b", "explosion", "explosion boom and debris, cinematic foley"),
    (r"\b(footsteps?|foot\s*steps?|walking|running|sprinting)\b", "footsteps", "footsteps on hard ground, foley"),
    (r"\b(whoosh|swoosh|fly(?:ing)?|spin(?:ning)?)\b", "whoosh", "fast air whoosh, motion pass-by, foley"),
    (r"\b(wind|gust)\b", "wind", "strong wind, outdoor ambience"),
    (r"\b(crowd|cheer(?:ing|s)?|audience|applause|clap(?:ping)?)\b", "crowd", "crowd reaction, realistic"),
    (r"\b(splash|ocean|wave|waves|water)\b", "water", "water splash, foley"),
    (r"\b(fire|burning|flame|flames|crackl)\b", "fire", "fire crackling, foley"),
    (r"\b(car|engine|crash|brakes?|skid)\b", "vehicle", "vehicle impact and tires, foley"),
    (r"\b(punch|punched|slap|slapped|hit|impact)\b", "impact", "heavy impact hit, punchy foley"),
    (r"\b(door|doors|creak|creaking)\b", "door", "wooden door creak, foley"),
    (r"\b(beep|alarm|phone|ringtone)\b", "beep", "electronic beep, foley"),
    (r"\b(scream|screaming|yell|shout)\b", "scream", "human shout, no music"),
    (r"\b(glass|shatter|shattering)\b", "glass", "glass shattering, foley"),
    (r"\b(click|button|switch)\b", "click", "button click foley"),
    (r"\b(snake|hiss|hissing)\b", "snake", "snake hiss, animal sound effect"),
    (r"\b(lion|tiger|growl|roar)\b", "roar", "big cat roar, animal sound effect"),
    (r"\b(bite|bites|bitten)\b", "bite", "sharp bite impact, foley"),
    (r"\b(fall(?:ing|s)?|dropped|crash(?:ed|ing)? through)\b", "fall", "body fall and thud, foley"),
    (r"\b(camera|shutter|flash)\b", "camera", "camera shutter click, foley"),
    (r"\b(scissors?|cut(?:ting|s)?|slice|scrap(?:e|ing))\b", "cut", "scissors cut and scrape, foley"),
    (r"\b(heartbeat|heart\s*beat|pulse)\b", "heartbeat", "deep heartbeat, foley"),
    (r"\b(clock|ticking|tick)\b", "clock", "clock ticking, foley"),
    (r"\b(whisper|whispers|breath|breathing)\b", "breath", "close breath and whisper air, foley"),
    (r"\b(metal|clang|chain|chains)\b", "metal", "metal clang, foley"),
    (r"\b(wood|splinter|crack)\b", "wood", "wood crack and splinter, foley"),
)

_SFX_TAIL = "realistic foley sound effect, no music, no speech"

_SFX_STYLE_PROMPTS = {
    "impact": "heavy impact hit, punchy foley, realistic, no music, no speech",
    "whoosh": "fast air whoosh, motion pass-by, foley, no music, no speech",
    "nature": "natural outdoor ambience and wildlife, field recording, no music, no speech",
    "crowd": "crowd reaction and room tone, realistic, no music, no speech",
    "mechanical": "mechanical gears, motors and metal, industrial foley, no music, no speech",
    "scifi": "sci-fi interface blips and energy, designed sound, no music, no speech",
    "explosion": "distant explosion boom and debris, cinematic foley, no music, no speech",
}


def _tokens(text: str) -> list[str]:
    return [match.group(0).lower() for match in _WORD.finditer(text or "")]


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def extract_music_cues(text: str, style: str = "auto") -> dict[str, object]:
    script = " ".join((text or "").split())
    tokens = _tokens(script)
    scores: Counter[str] = Counter()
    words: list[str] = []
    for token in tokens:
        mood = _MUSIC_MOOD.get(token)
        if mood:
            scores[mood] += 1
            words.append(token)
        elif token in _MUSIC_SETTING:
            words.append(token)
    chosen = (style or "auto").strip().lower()
    if chosen == "auto" or chosen not in _MUSIC_BEDS:
        chosen = scores.most_common(1)[0][0] if scores else "cinematic"
    words = _unique(words)[:8]
    bed = _MUSIC_BEDS.get(chosen, _MUSIC_BEDS["cinematic"])
    if words:
        prompt = f"{bed}. Keywords: {', '.join(words)}"
    else:
        prompt = bed
    return {
        "mood": chosen,
        "words": words,
        "prompt": prompt,
        "label": ", ".join(words) if words else chosen,
    }


def extract_sfx_cues(text: str, style: str = "auto", limit: int = 3) -> dict[str, object]:
    script = " ".join((text or "").split())
    chosen = (style or "auto").strip().lower()
    found: list[tuple[int, dict[str, str]]] = []
    if script:
        lowered = script.lower()
        for pattern, event_id, prompt in _SFX_EVENTS:
            match = re.search(pattern, lowered, flags=re.IGNORECASE)
            if not match:
                continue
            found.append(
                (
                    match.start(),
                    {
                        "id": event_id,
                        "word": match.group(0),
                        "prompt": f"{prompt}, {_SFX_TAIL}",
                    },
                )
            )
    found.sort(key=lambda item: item[0])
    events = [item[1] for item in found][: max(1, limit)]
    if chosen not in {"", "auto"}:
        base = _SFX_STYLE_PROMPTS.get(chosen, "")
        if base:
            extra = ", ".join(item["word"] for item in events[:3])
            prompt = f"{base}. Keywords: {extra}" if extra else base
            events = [{"id": chosen, "word": extra or chosen, "prompt": prompt}]
    if not events and script:
        short = script if len(script) < 80 else "cinematic foley for a short documentary scene"
        events = [
            {
                "id": "scene",
                "word": "scene",
                "prompt": f"{short}, {_SFX_TAIL}",
            }
        ]
    words = _unique([str(item.get("word") or "") for item in events])
    return {
        "events": events,
        "words": words,
        "prompt": str(events[0]["prompt"]) if events else _SFX_TAIL,
        "label": ", ".join(words) if words else "",
    }


def analyze_script(text: str, music_style: str = "auto", sfx_style: str = "auto") -> dict[str, object]:
    return {"music": extract_music_cues(text, music_style), "sfx": extract_sfx_cues(text, sfx_style)}
