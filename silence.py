"""Shorten long silences in audio while keeping short, natural pauses."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np

from voice import SpeakResult, export_voiceover, unique_path, wav_duration

FRAME_MS = 0.02
HOP_MS = 0.01
MIN_SPEECH = 0.05
PAD_SPEECH = 0.03
EDGE_KEEP = 0.02
# Only gaps longer than this are treated as dead air. Shorter dips are
# word spacing; cutting those makes a second pass sound sped up.
MIN_SILENCE_TO_CUT = 0.22
DEFAULT_MAX_PAUSE = 0.0
MIN_MAX_PAUSE = 0.0
MAX_MAX_PAUSE = 0.45
FADE_MS = 0.004
SKIP_IF_REMOVED_UNDER = 0.06


@dataclass
class SilenceStats:
    original_duration: float
    duration: float
    removed: float
    pauses_shortened: int
    sample_rate: int


def clamp_max_pause(value: float) -> float:
    return min(MAX_MAX_PAUSE, max(MIN_MAX_PAUSE, float(value)))


def _as_2d(audio: np.ndarray, channels: int | None = None) -> np.ndarray:
    data = np.asarray(audio, dtype=np.float32)
    if data.ndim == 1:
        return data.reshape(-1, 1)
    if channels is not None:
        if data.shape[1] == channels:
            return np.ascontiguousarray(data)
        if data.shape[0] == channels:
            return np.ascontiguousarray(data.T)
    if data.shape[0] <= 8 and data.shape[0] < data.shape[1]:
        return np.ascontiguousarray(data.T)
    return np.ascontiguousarray(data)


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    import wave

    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        width = wav_file.getsampwidth()
        rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    if width == 1:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {width} bytes")

    if channels > 1:
        data = data.reshape(-1, channels)
    else:
        data = data.reshape(-1, 1)
    return data, rate


def write_wav(path: Path, audio: np.ndarray, rate: int) -> None:
    import wave

    data = _as_2d(audio)
    pcm = np.clip(data, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(int(data.shape[1]))
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(rate))
        wav_file.writeframes(pcm.tobytes())


def _frame_to_float(frame, channels: int) -> np.ndarray:
    arr = np.asarray(frame.to_ndarray())
    if np.issubdtype(arr.dtype, np.floating):
        data = arr.astype(np.float32, copy=False)
    else:
        data = arr.astype(np.float32) / 32768.0
    if data.ndim == 1:
        return data.reshape(-1, 1) if channels == 1 else data.reshape(-1, channels)
    if data.shape[0] == channels:
        return np.ascontiguousarray(data.T)
    if data.shape[1] == channels:
        return np.ascontiguousarray(data)
    return data.reshape(-1, channels)


def load_media_audio(path: Path) -> tuple[np.ndarray, int]:
    source = Path(path)
    if source.suffix.lower() == ".wav":
        return read_wav(source)

    container = av.open(str(source))
    try:
        stream = next((item for item in container.streams if item.type == "audio"), None)
        if stream is None:
            raise ValueError("That file has no audio to clean.")
        rate = int(stream.rate or 24000)
        channels = 2 if (stream.channels or 1) >= 2 else 1
        layout = "stereo" if channels == 2 else "mono"
        resampler = av.AudioResampler(format="s16p", layout=layout, rate=rate)
        chunks: list[np.ndarray] = []

        def consume(result) -> None:
            frames = result if isinstance(result, list) else [result]
            for frame in frames:
                if frame is None:
                    continue
                chunks.append(_frame_to_float(frame, channels))

        for frame in container.decode(stream):
            consume(resampler.resample(frame))
        consume(resampler.resample(None))
    finally:
        container.close()

    if not chunks:
        raise ValueError("No audio samples were decoded.")
    return np.concatenate(chunks, axis=0), rate


def _rms_frames(mono: np.ndarray, rate: int) -> tuple[np.ndarray, int, int]:
    frame = max(1, int(rate * FRAME_MS))
    hop = max(1, int(rate * HOP_MS))
    if mono.size < frame:
        rms = np.sqrt(np.mean(mono * mono, dtype=np.float64)).astype(np.float32)
        return np.array([rms], dtype=np.float32), frame, hop
    window = np.ones(frame, dtype=np.float64) / float(frame)
    energy = np.convolve(mono.astype(np.float64) ** 2, window, mode="valid")
    rms = np.sqrt(energy[::hop]).astype(np.float32)
    return rms, frame, hop


def _speech_mask(rms: np.ndarray) -> np.ndarray:
    if rms.size == 0:
        return np.zeros(0, dtype=bool)
    peak = float(np.percentile(rms, 98))
    quiet = float(np.percentile(rms, 5))
    # Packed/already-cleaned speech has little true silence, so the quiet
    # percentile sits inside the voice. Only cut near-digital zeros then.
    spread = peak / max(quiet, 1e-6)
    if spread < 10.0:
        threshold = float(np.clip(max(peak * 0.07, 0.01), 0.008, 0.08))
    else:
        threshold = float(np.clip(max(quiet * 3.5, peak * 0.04, 0.004), 0.003, 0.05))
    high = threshold * 1.6
    mask = np.zeros(rms.shape[0], dtype=bool)
    speaking = False
    for i, value in enumerate(rms):
        if speaking:
            speaking = value >= threshold
        else:
            speaking = value >= high
        mask[i] = speaking
    if rms.size >= 3:
        padded = np.pad(mask.astype(np.int8), 1, mode="edge")
        mask = ((padded[:-2] + padded[1:-1] + padded[2:]) >= 2)
    return _fill_short_gaps(mask.astype(bool), max(1, int(MIN_SILENCE_TO_CUT / HOP_MS)))


def _fill_short_gaps(mask: np.ndarray, max_gap_frames: int) -> np.ndarray:
    """Treat brief dips between words as speech so they are not deleted."""
    if mask.size == 0 or max_gap_frames <= 0:
        return mask
    filled = mask.copy()
    for start, end in _runs(~mask):
        if start == 0 or end >= mask.size:
            continue
        if end - start <= max_gap_frames:
            filled[start:end] = True
    return filled


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    if mask.size == 0:
        return []
    padded = np.concatenate([[False], mask.astype(bool), [False]])
    delta = np.diff(padded.astype(np.int8))
    starts = np.where(delta == 1)[0]
    ends = np.where(delta == -1)[0]
    return [(int(start), int(end)) for start, end in zip(starts, ends)]


def _merge_ranges(ranges: list[tuple[int, int]], limit: int) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ordered = sorted((max(0, start), min(limit, end)) for start, end in ranges if end > start)
    if not ordered:
        return []
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _fade_piece_edges(piece: np.ndarray, fade: int, *, fade_in: bool, fade_out: bool) -> np.ndarray:
    if piece.size == 0 or fade <= 0:
        return piece
    fade = min(int(fade), max(1, piece.shape[0] // 8))
    if fade <= 1:
        return piece
    out = piece.copy()
    weight = np.linspace(0.0, 1.0, fade, dtype=np.float32).reshape(-1, 1)
    if fade_in:
        out[:fade] *= weight
    if fade_out:
        out[-fade:] *= weight[::-1]
    return out


def detect_speech_ranges(
    audio: np.ndarray,
    rate: int,
    pad_seconds: float = 0.0,
) -> list[tuple[int, int]]:
    data = _as_2d(audio)
    rate = int(rate)
    if data.size == 0 or rate <= 0:
        return []
    mono = data.mean(axis=1)
    rms, frame, hop = _rms_frames(mono, rate)
    mask = _speech_mask(rms)
    min_speech_frames = max(1, int(MIN_SPEECH / HOP_MS))
    speech_runs = [(start, end) for start, end in _runs(mask) if end - start >= min_speech_frames]
    if not speech_runs:
        return []

    def frame_to_sample(index: int, trailing: bool = False) -> int:
        sample = index * hop
        if trailing:
            sample += frame
        return int(min(data.shape[0], max(0, sample)))

    pad = int(rate * max(0.0, pad_seconds if pad_seconds is not None else PAD_SPEECH))
    return _merge_ranges(
        [
            (frame_to_sample(start) - pad, frame_to_sample(end, trailing=True) + pad)
            for start, end in speech_runs
        ],
        data.shape[0],
    )


def speech_windows(path: Path) -> tuple[list[tuple[float, float]], float]:
    audio, rate = load_media_audio(path)
    duration = audio.shape[0] / float(rate) if rate else 0.0
    ranges = detect_speech_ranges(audio, rate, pad_seconds=0.02)
    windows = [(start / float(rate), end / float(rate)) for start, end in ranges]
    return windows, duration


def compress_silence(
    audio: np.ndarray,
    rate: int,
    max_pause: float = DEFAULT_MAX_PAUSE,
) -> tuple[np.ndarray, SilenceStats]:
    data = _as_2d(audio)
    rate = int(rate)
    original = data.shape[0] / float(rate) if rate else 0.0
    if data.size == 0 or rate <= 0:
        raise ValueError("Audio is empty.")

    max_pause = clamp_max_pause(max_pause)
    speech_ranges = detect_speech_ranges(data, rate, pad_seconds=PAD_SPEECH)
    if not speech_ranges:
        raise ValueError("No speech found to keep. Try a clip with clearer voice.")

    keep: list[tuple[int, int]] = []
    pauses_shortened = 0
    max_pause_samples = int(rate * max_pause)
    min_cut = int(rate * MIN_SILENCE_TO_CUT)
    edge = int(rate * EDGE_KEEP)

    first_start = speech_ranges[0][0]
    if first_start > min_cut:
        lead = min(edge, first_start)
        keep.append((first_start - lead, first_start))
        pauses_shortened += 1
    elif first_start > 0:
        keep.append((0, first_start))

    for index, (start, end) in enumerate(speech_ranges):
        keep.append((start, end))
        if index + 1 >= len(speech_ranges):
            continue
        next_start = speech_ranges[index + 1][0]
        gap = next_start - end
        if gap <= 0:
            continue
        if gap <= min_cut:
            keep.append((end, next_start))
            continue
        pauses_shortened += 1
        head = int(max_pause_samples * 0.55) if max_pause_samples > 0 else 0
        tail = max(0, max_pause_samples - head)
        if head:
            keep.append((end, end + head))
        if tail:
            keep.append((next_start - tail, next_start))

    last_end = speech_ranges[-1][1]
    if data.shape[0] - last_end > min_cut:
        trail = min(edge, data.shape[0] - last_end)
        keep.append((last_end, last_end + trail))
        pauses_shortened += 1
    elif last_end < data.shape[0]:
        keep.append((last_end, data.shape[0]))

    keep = _merge_ranges(keep, data.shape[0])
    kept_samples = sum(end - start for start, end in keep)
    if pauses_shortened == 0 or kept_samples >= data.shape[0] * 0.995:
        return data, SilenceStats(
            original_duration=original,
            duration=original,
            removed=0.0,
            pauses_shortened=0,
            sample_rate=rate,
        )

    fade = max(1, int(rate * FADE_MS))
    pieces: list[np.ndarray] = []
    for index, (start, end) in enumerate(keep):
        if end <= start:
            continue
        piece = data[start:end]
        fade_in = index > 0
        fade_out = index + 1 < len(keep)
        if fade_in or fade_out:
            piece = _fade_piece_edges(piece, fade, fade_in=fade_in, fade_out=fade_out)
        pieces.append(piece)
    if not pieces:
        raise ValueError("Silence removal left no audio.")

    combined = np.clip(np.concatenate(pieces, axis=0), -1.0, 1.0)
    duration = combined.shape[0] / float(rate)
    if original - duration < SKIP_IF_REMOVED_UNDER:
        return data, SilenceStats(
            original_duration=original,
            duration=original,
            removed=0.0,
            pauses_shortened=0,
            sample_rate=rate,
        )
    return combined, SilenceStats(
        original_duration=original,
        duration=duration,
        removed=max(0.0, original - duration),
        pauses_shortened=pauses_shortened,
        sample_rate=rate,
    )


def apply_to_wav(path: Path, max_pause: float = DEFAULT_MAX_PAUSE) -> SilenceStats:
    source = Path(path)
    audio, rate = read_wav(source)
    processed, stats = compress_silence(audio, rate, max_pause=max_pause)
    if stats.removed > 0:
        write_wav(source, processed, rate)
    return stats


def remove_silence_file(
    source: str | Path,
    out_dir: Path,
    max_pause: float = DEFAULT_MAX_PAUSE,
    name: str | None = None,
) -> tuple[SpeakResult, SilenceStats]:
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"File not found: {source_path}")

    audio, rate = load_media_audio(source_path)
    processed, stats = compress_silence(audio, rate, max_pause=max_pause)

    dest_dir = Path(out_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = name or f"{source_path.stem}-silence"

    if stats.removed <= 0 and source_path.suffix.lower() == ".mp3":
        dest = unique_path(dest_dir / f"{stem}.mp3")
        shutil.copy2(source_path, dest)
        return SpeakResult(
            path=dest,
            voice="silence",
            duration=stats.original_duration,
            sample_rate=rate,
            speed=1.0,
            original_duration=stats.original_duration,
            silence_removed=0.0,
        ), stats

    dest = unique_path(dest_dir / f"{stem}.wav")
    write_wav(dest, processed, rate)
    duration, sample_rate = wav_duration(dest)
    result = SpeakResult(
        path=export_voiceover(dest),
        voice="silence",
        duration=duration,
        sample_rate=sample_rate,
        speed=1.0,
        original_duration=stats.original_duration,
        silence_removed=stats.removed,
    )
    return result, stats
