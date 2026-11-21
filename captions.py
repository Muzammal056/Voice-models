"""Build SRT captions for a generated or cleaned voiceover."""

from __future__ import annotations

import re
from pathlib import Path

from transcriber import TranscriptResult, TranscriptSegment

WORDS_PER_CUE = 5
MIN_WORDS_BREAK = 4
MAX_CUE_SECONDS = 2.0
_PUNCT_BREAK = re.compile(r"[,;:]$")
_SENTENCE_END = re.compile(r"[.!?]$")


def cue_texts(script: str) -> list[str]:
    words = (script or "").split()
    if not words:
        return []
    groups: list[list[str]] = []
    buf: list[str] = []
    for word in words:
        buf.append(word)
        count = len(buf)
        stop = bool(_SENTENCE_END.search(word))
        pause = bool(_PUNCT_BREAK.search(word))
        if count >= WORDS_PER_CUE or (count >= MIN_WORDS_BREAK and (stop or pause)):
            groups.append(buf)
            buf = []
    if buf:
        if groups and len(buf) <= 2:
            prev = groups[-1]
            if len(prev) + len(buf) <= WORDS_PER_CUE:
                groups[-1].extend(buf)
            elif len(prev) >= MIN_WORDS_BREAK:
                take = 2 if len(buf) == 1 and len(prev) >= 5 else 1
                extra = prev[-take:]
                groups[-1] = prev[:-take]
                groups.append(extra + buf)
            else:
                groups.append(buf)
        elif len(buf) >= 6:
            mid = (len(buf) + 1) // 2
            groups.append(buf[:mid])
            groups.append(buf[mid:])
        else:
            groups.append(buf)
    return [" ".join(group) for group in groups if group]


def _time_at(windows: list[tuple[float, float]], position: float) -> float:
    remain = max(0.0, position)
    for start, end in windows:
        length = end - start
        if remain <= length:
            return start + remain
        remain -= length
    return windows[-1][1]


def _split_overlong(segments: list[TranscriptSegment], limit: float = MAX_CUE_SECONDS) -> list[TranscriptSegment]:
    out: list[TranscriptSegment] = []
    for seg in segments:
        words = seg.text.split()
        span = max(0.0, seg.end - seg.start)
        if span <= limit + 0.12 or len(words) <= 2:
            out.append(seg)
            continue
        needed = max(2, int(round(span / 1.5)))
        n = min(len(words), needed)
        sizes = [len(words) // n] * n
        for i in range(len(words) % n):
            sizes[i] += 1
        cursor = seg.start
        index = 0
        for i, size in enumerate(sizes):
            if size <= 0:
                continue
            chunk = words[index : index + size]
            index += size
            piece = span * (size / float(len(words)))
            end = seg.end if i == len(sizes) - 1 else min(seg.end, cursor + piece)
            if end <= cursor:
                end = min(seg.end, cursor + 0.4)
            out.append(TranscriptSegment(start=cursor, end=end, text=" ".join(chunk)))
            cursor = end
    return out


def rechunk_transcript(result: TranscriptResult) -> TranscriptResult:
    segments: list[TranscriptSegment] = []
    for seg in result.segments:
        cues = cue_texts(seg.text)
        if not cues:
            continue
        span = max(0.05, float(seg.end) - float(seg.start))
        weights = [max(1, len(cue.split())) for cue in cues]
        total = float(sum(weights))
        cursor = float(seg.start)
        built: list[TranscriptSegment] = []
        for i, (cue, weight) in enumerate(zip(cues, weights)):
            piece = span * (weight / total)
            end = float(seg.end) if i == len(cues) - 1 else cursor + piece
            if end <= cursor:
                end = min(float(seg.end), cursor + 0.4)
            built.append(TranscriptSegment(start=cursor, end=end, text=cue))
            cursor = end
        if built:
            built[-1].end = float(seg.end)
        segments.extend(built)
    segments = _split_overlong(segments)
    return TranscriptResult(
        language=result.language,
        language_probability=result.language_probability,
        duration=result.duration,
        segments=segments,
    )


def captions_from_script(
    script: str,
    media_path: str | Path,
    duration: float | None = None,
) -> TranscriptResult:
    from silence import speech_windows

    cues = cue_texts(script)
    if not cues:
        raise ValueError("No script text to caption.")

    windows, audio_duration = speech_windows(Path(media_path))
    duration = float(duration if duration is not None else audio_duration)
    if duration <= 0:
        duration = audio_duration
    speech = [(max(0.0, start), min(duration, end)) for start, end in windows if end > start]
    if not speech:
        speech = [(0.0, duration or 0.01)]
    total_speech = sum(end - start for start, end in speech) or duration or 0.01

    weights = [max(1, len(cue.split())) for cue in cues]
    total_weight = float(sum(weights))
    segments: list[TranscriptSegment] = []
    cursor = 0.0
    for cue, weight in zip(cues, weights):
        span = total_speech * (weight / total_weight)
        start = _time_at(speech, cursor)
        cursor += span
        end = _time_at(speech, cursor)
        if end <= start:
            end = min(duration, start + 0.4)
        segments.append(TranscriptSegment(start=start, end=end, text=cue))
    if segments:
        segments[-1].end = min(duration, max(segments[-1].end, speech[-1][1]))
    segments = _split_overlong(segments)
    return TranscriptResult(
        language="en",
        language_probability=1.0,
        duration=duration,
        segments=segments,
    )


def save_srt(result: TranscriptResult, media_path: str | Path) -> Path:
    dest = Path(media_path).with_suffix(".srt")
    dest.write_text(result.to_srt(), encoding="utf-8")
    return dest
