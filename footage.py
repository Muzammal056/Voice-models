"""Search free stock video APIs and mux clips under a voiceover."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cues import extract_footage_queries
from shot_utils import clamp_shot_seconds, sanitize_shot_query
from voice import make_audio_stem, unique_path

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "models" / "footage" / "cache"
SEARCH_CACHE_DIR = ROOT / "models" / "footage" / "search-cache"
KEYS_PATH = ROOT / "models" / "footage" / "keys.json"
USER_AGENT = "LocalShortsEditor/1.0 (desktop stock footage for personal videos)"
SEARCH_CACHE_SECONDS = 24 * 60 * 60
CLIP_SECONDS = 2.4
MIN_CLIP_SECONDS = 1.2
MAX_CLIP_SECONDS = 4.0
MAX_CLIPS = 28
ASPECTS = {
    "vertical": (1080, 1920),
    "wide": (1920, 1080),
}


def _ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception as exc:
        raise RuntimeError(
            "Video merge needs ffmpeg. Install it, or run: pip install imageio-ffmpeg"
        ) from exc


def load_keys() -> dict[str, str]:
    env = {
        "pixabay": os.environ.get("PIXABAY_API_KEY", "").strip(),
        "pexels": os.environ.get("PEXELS_API_KEY", "").strip(),
    }
    if KEYS_PATH.exists():
        try:
            stored = json.loads(KEYS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stored = {}
        if isinstance(stored, dict):
            for name in ("pixabay", "pexels"):
                value = str(stored.get(name) or "").strip()
                if value and not env[name]:
                    env[name] = value
    return env


def save_keys(pixabay: str | None = None, pexels: str | None = None) -> dict[str, str]:
    current = {}
    if KEYS_PATH.exists():
        try:
            loaded = json.loads(KEYS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        except (OSError, json.JSONDecodeError):
            current = {}
    if pixabay is not None:
        current["pixabay"] = pixabay.strip()
    if pexels is not None:
        current["pexels"] = pexels.strip()
    KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEYS_PATH.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return load_keys()


def keys_status() -> dict[str, object]:
    keys = load_keys()
    return {
        "pixabay": bool(keys.get("pixabay")),
        "pexels": bool(keys.get("pexels")),
        "ready": bool(keys.get("pixabay") or keys.get("pexels")),
    }


def _get_json(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Stock API error {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach the stock API: {exc.reason}") from exc


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 50_000:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response, tmp.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    tmp.replace(dest)
    return dest


def _search_pixabay(query: str, key: str, limit: int = 5) -> list[dict[str, str]]:
    params = urllib.parse.urlencode(
        {
            "key": key,
            "q": query,
            "per_page": max(3, min(20, max(limit, 12))),
            "safesearch": "true",
            "video_type": "all",
            "order": "popular",
        }
    )
    data = _get_json(f"https://pixabay.com/api/videos/?{params}")
    clips: list[dict[str, str]] = []
    for hit in data.get("hits") or []:
        videos = hit.get("videos") or {}
        file_url = ""
        for size in ("large", "medium", "small", "tiny"):
            item = videos.get(size) or {}
            url = str(item.get("url") or "").strip()
            if url:
                file_url = url
                break
        if not file_url:
            continue
        clips.append(
            {
                "id": str(hit.get("id") or ""),
                "source": "pixabay",
                "query": query,
                "url": file_url,
                "page": str(hit.get("pageURL") or ""),
                "user": str(hit.get("user") or "Pixabay"),
                "tags": str(hit.get("tags") or ""),
            }
        )
        if len(clips) >= limit:
            break
    return clips


def _search_pexels(query: str, key: str, limit: int = 5) -> list[dict[str, str]]:
    params = urllib.parse.urlencode({"query": query, "per_page": max(3, min(15, limit * 2))})
    data = _get_json(
        f"https://api.pexels.com/videos/search?{params}",
        headers={"Authorization": key},
    )
    clips: list[dict[str, str]] = []
    for hit in data.get("videos") or []:
        files = list(hit.get("video_files") or [])
        files.sort(key=lambda item: int(item.get("width") or 0))
        chosen = None
        for item in files:
            if str(item.get("file_type") or "").startswith("video/mp4") and int(item.get("width") or 0) >= 640:
                chosen = item
                if int(item.get("width") or 0) >= 1280:
                    break
        if chosen is None and files:
            chosen = files[-1]
        if not chosen or not chosen.get("link"):
            continue
        user = hit.get("user") or {}
        clips.append(
            {
                "id": str(hit.get("id") or ""),
                "source": "pexels",
                "query": query,
                "url": str(chosen["link"]),
                "page": str(hit.get("url") or ""),
                "user": str(user.get("name") or "Pexels"),
                "tags": query,
            }
        )
        if len(clips) >= limit:
            break
    return clips


def _search_cache_path(source: str, query: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", (query or "").lower()).strip("-")[:48] or "query"
    return SEARCH_CACHE_DIR / f"{source}-{slug}-v3.json"


def _load_search_cache(source: str, query: str) -> list[dict[str, str]] | None:
    path = _search_cache_path(source, query)
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > SEARCH_CACHE_SECONDS:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, list):
        return data
    return None


def _save_search_cache(source: str, query: str, clips: list[dict[str, str]]) -> None:
    SEARCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _search_cache_path(source, query)
    path.write_text(json.dumps(clips), encoding="utf-8")


def _clean_queries(items: list[object] | None, limit: int = 28) -> list[str]:
    out: list[str] = []
    for item in items or []:
        query = sanitize_shot_query(str(item))
        if query and query not in out:
            out.append(query)
        if len(out) >= limit:
            break
    return out


def _shots_from_plan(
    queries: list[str],
    shots: list[object] | None = None,
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    seen: set[str] = set()
    raw_items: list[object] = list(shots or []) or list(queries)
    for item in raw_items:
        if isinstance(item, dict):
            query = sanitize_shot_query(str(item.get("query") or item.get("primary") or ""))
            alts = _clean_queries(item.get("alternatives") or item.get("alts") or [], limit=4)
            beat = str(item.get("beat") or "setup")
            duration = clamp_shot_seconds(item.get("duration"), beat)
            note = str(item.get("note") or "")
            shot_type = str(item.get("shot_type") or "medium")
        else:
            query = sanitize_shot_query(str(item))
            alts = []
            beat = "setup"
            duration = CLIP_SECONDS
            note = ""
            shot_type = "medium"
        if not query or query in seen:
            continue
        seen.add(query)
        out.append(
            {
                "query": query,
                "alternatives": [alt for alt in alts if alt != query],
                "beat": beat,
                "duration": duration,
                "shot_type": shot_type,
                "note": note,
            }
        )
    return out


def _clip_score(clip: dict[str, str], query: str, tone: str = "") -> float:
    hay = f"{clip.get('tags') or ''} {clip.get('query') or ''}".lower()
    hay = re.sub(r"[^a-z0-9]+", " ", hay)
    tokens = set(hay.split())
    score = 0.0
    for word in query.lower().split():
        if len(word) < 3:
            continue
        if word in tokens:
            score += 4.0
        elif any(word in token or token in word for token in tokens if len(token) >= 4):
            score += 1.5
    for word in re.findall(r"[a-z]{3,}", (tone or "").lower()):
        if word in tokens:
            score += 1.0
    return score


def _collect_candidates(query: str, seen: set[str], tone: str) -> list[tuple[float, str, dict[str, str]]]:
    found: list[tuple[float, str, dict[str, str]]] = []
    for clip in search_clips(query, limit=15):
        key = f"{clip['source']}-{clip['id']}"
        if key in seen:
            continue
        found.append((_clip_score(clip, query, tone), query, clip))
    found.sort(key=lambda item: item[0], reverse=True)
    return found


def _pick_clips(
    queries: list[str],
    needed: int,
    tone: str = "",
    shots: list[object] | None = None,
) -> list[dict[str, str]]:
    plan = _shots_from_plan(queries, shots)
    if not plan:
        plan = [{"query": query, "alternatives": [], "beat": "setup", "duration": CLIP_SECONDS, "shot_type": "medium", "note": ""} for query in queries]
    picked: list[dict[str, str]] = []
    seen: set[str] = set()
    leftovers: list[tuple[float, str, dict[str, str]]] = []
    for shot in plan:
        searches = [str(shot["query"])] + [str(item) for item in shot.get("alternatives") or []]
        chosen: tuple[float, str, dict[str, str]] | None = None
        for query in searches:
            ranked = _collect_candidates(query, seen, tone)
            leftovers.extend(ranked)
            if not ranked:
                continue
            if chosen is None or ranked[0][0] > chosen[0]:
                chosen = ranked[0]
            if ranked[0][0] >= 4.0:
                break
        if chosen is None:
            continue
        score, query, clip = chosen
        key = f"{clip['source']}-{clip['id']}"
        if key in seen:
            continue
        seen.add(key)
        selected = dict(clip)
        selected["query"] = query
        selected["duration"] = f"{float(shot.get('duration') or CLIP_SECONDS):.2f}"
        selected["beat"] = str(shot.get("beat") or "")
        selected["shot_type"] = str(shot.get("shot_type") or "")
        selected["note"] = str(shot.get("note") or "")
        picked.append(selected)
        if len(picked) >= needed:
            return picked[:needed]
    leftovers.sort(key=lambda item: item[0], reverse=True)
    for score, query, clip in leftovers:
        key = f"{clip['source']}-{clip['id']}"
        if key in seen:
            continue
        seen.add(key)
        selected = dict(clip)
        selected["query"] = query
        selected["duration"] = f"{CLIP_SECONDS:.2f}"
        selected["beat"] = "broll"
        picked.append(selected)
        if len(picked) >= needed:
            break
    return picked[:needed]


def search_clips(query: str, limit: int = 4) -> list[dict[str, str]]:
    keys = load_keys()
    clips: list[dict[str, str]] = []
    errors: list[str] = []
    if keys.get("pixabay"):
        cached = _load_search_cache("pixabay", query)
        if cached is not None:
            clips.extend(cached)
        else:
            try:
                found = _search_pixabay(query, keys["pixabay"], limit)
                _save_search_cache("pixabay", query, found)
                clips.extend(found)
            except RuntimeError as exc:
                errors.append(str(exc))
    if len(clips) < limit and keys.get("pexels"):
        cached = _load_search_cache("pexels", query)
        if cached is not None:
            clips.extend(cached)
        else:
            try:
                found = _search_pexels(query, keys["pexels"], limit)
                _save_search_cache("pexels", query, found)
                clips.extend(found)
            except RuntimeError as exc:
                errors.append(str(exc))
    if clips:
        return clips[:limit]
    if errors:
        raise RuntimeError(errors[0])
    return []


def _audio_seconds(path: Path) -> float:
    import av

    container = av.open(str(path))
    try:
        if container.duration and container.duration > 0:
            return float(container.duration) / 1_000_000.0
        stream = next((item for item in container.streams if item.type == "audio"), None)
        if stream and stream.duration and stream.time_base:
            return float(stream.duration * stream.time_base)
    finally:
        container.close()
    raise ValueError(f"Could not read duration from {path.name}")


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "ffmpeg failed").strip()
        raise RuntimeError(detail[-1600:] or "ffmpeg failed")


def _normalize_clip(
    source: Path,
    dest: Path,
    width: int,
    height: int,
    seconds: float,
    zoom: bool = False,
) -> Path:
    scale_w, scale_h = width, height
    if zoom:
        scale_w = int(width * 1.18)
        scale_h = int(height * 1.18)
    vf = (
        f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps=30,format=yuv420p"
    )
    cut = max(MIN_CLIP_SECONDS, min(MAX_CLIP_SECONDS, float(seconds)))
    _run_ffmpeg(
        [
            "-y",
            "-i",
            str(source),
            "-t",
            f"{cut:.2f}",
            "-an",
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            str(dest),
        ]
    )
    return dest


def assemble_video(
    text: str,
    voice_path: str | Path,
    aspect: str = "vertical",
    out_dir: Path | None = None,
    planner=None,
    planned_queries: list[str] | None = None,
    planned_tone: str = "",
    planned_shots: list[object] | None = None,
) -> dict[str, object]:
    script = " ".join((text or "").split())
    if not script:
        raise ValueError("Paste the narration so the app can search matching footage.")
    voice = Path(voice_path)
    if not voice.exists():
        raise FileNotFoundError("Generate a voiceover first, then build the video.")
    keys = load_keys()
    if not (keys.get("pixabay") or keys.get("pexels")):
        raise ValueError(
            "Add a free Pixabay or Pexels API key. Those sites license the stock clips. "
            "Pictory and Freepik are not free public footage APIs."
        )
    width, height = ASPECTS.get((aspect or "vertical").strip().lower(), ASPECTS["vertical"])
    audio_len = max(2.0, _audio_seconds(voice))
    needed = min(MAX_CLIPS, max(8, int(math.ceil(audio_len / CLIP_SECONDS))))
    tone = str(planned_tone or "").strip()
    queries = _clean_queries(planned_queries, limit=max(needed, 12))
    shots: list[object] | None = planned_shots if isinstance(planned_shots, list) and planned_shots else None
    planner_source = "planned" if len(queries) >= 2 else ""
    if len(queries) < 2 and planner is not None:
        try:
            plan = planner(script, needed)
        except Exception as exc:
            logging.getLogger(__name__).warning("Shot plan failed: %s", exc)
            plan = None
        if isinstance(plan, dict):
            queries = _clean_queries(plan.get("queries"), limit=max(needed, 12))
            tone = str(plan.get("tone") or tone or "").strip()
            planner_source = str(plan.get("source") or "planner")
            if isinstance(plan.get("shots"), list) and plan["shots"]:
                shots = plan["shots"]
    if len(queries) < 2:
        cues = extract_footage_queries(script, limit=max(needed, 10))
        queries = [str(item) for item in (cues.get("queries") or []) if str(item).strip()]
        planner_source = "keywords"
        shots = None
        if not tone:
            tone = str(cues.get("label") or "")
    picked = _pick_clips(queries, needed, tone, shots=shots)
    if not picked:
        raise RuntimeError(
            "No stock clips matched those shots. Try a simpler script, or add the other API key."
        )

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    work = CACHE_DIR / "edit"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    prepared: list[Path] = []
    credits: list[str] = []
    covered = 0.0
    tight_beats = {"hook", "reveal", "confrontation", "reaction", "payoff"}
    for index, clip in enumerate(picked, start=1):
        raw = CACHE_DIR / f"{clip['source']}-{clip['id']}.mp4"
        _download(clip["url"], raw)
        seconds = clamp_shot_seconds(clip.get("duration"), str(clip.get("beat") or ""))
        zoom = str(clip.get("beat") or "").lower() in tight_beats
        cut = work / f"clip-{index:02d}.mp4"
        _normalize_clip(raw, cut, width, height, seconds, zoom=zoom)
        prepared.append(cut)
        covered += seconds
        clip["duration"] = f"{seconds:.2f}"
        credit = f"{clip['source']} / {clip['user']} / {clip['query']}"
        if clip.get("page"):
            credit += f" / {clip['page']}"
        credits.append(credit)

    repeats = 1
    if covered < audio_len - 0.3:
        repeats = max(1, int(math.ceil(audio_len / max(0.1, covered))))
    playlist = prepared * repeats
    concat_file = work / "concat.txt"
    lines = [f"file '{path.resolve().as_posix()}'" for path in playlist]
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    dest_dir = Path(out_dir) if out_dir else ROOT / "outputs"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = make_audio_stem(script, "video")
    output = unique_path(dest_dir / f"{stem}.mp4")
    _run_ffmpeg(
        [
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-i",
            str(voice),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    credits_path = output.with_suffix(".credits.txt")
    credits_path.write_text(
        "Stock footage used in this video:\n" + "\n".join(credits) + "\n",
        encoding="utf-8",
    )
    return {
        "path": output,
        "name": output.name,
        "duration": audio_len,
        "queries": queries,
        "clips": picked,
        "credits": credits,
        "credits_path": credits_path,
        "aspect": f"{width}x{height}",
        "tone": tone,
        "planner": planner_source or "keywords",
        "clip_count": len(picked),
    }
