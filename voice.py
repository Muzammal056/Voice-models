"""Shared audio results and exports for Kokoro and cloned speech."""
from __future__ import annotations
import re,wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import av
DEFAULT_VOICE='kokoro:am_michael'
MAX_SCRIPT_CHARS=20_000
_UNSAFE=re.compile(r"[^\w\s-]",re.UNICODE)

@dataclass
class SpeakResult:
    path: Path
    voice: str
    duration: float
    sample_rate: int
    speed: float
    original_duration: float | None = None
    silence_removed: float = 0.0


def make_audio_stem(text: str, voice_id: str) -> str:
    cleaned = _UNSAFE.sub("", text).strip()
    cleaned = re.sub(r"\s+", "-", cleaned)
    if not cleaned:
        cleaned = "voiceover"
    parts = voice_id.split("-")
    voice_short = parts[1] if len(parts) > 1 else voice_id
    return f"{cleaned[:48].strip('-')}-{voice_short}"


def wav_duration(path: Path) -> tuple[float, int]:
    with wave.open(str(path), "rb") as wav_file:
        rate = wav_file.getframerate()
        frames = wav_file.getnframes()
        return (frames / float(rate) if rate else 0.0), rate


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return path.with_name(f"{path.stem}-{stamp}{path.suffix}")


def wav_to_mp3(wav_path: Path, bitrate: int = 192_000) -> Path:
    source = Path(wav_path)
    dest = unique_path(source.with_suffix(".mp3"))
    incoming = av.open(str(source))
    try:
        in_stream = next((stream for stream in incoming.streams if stream.type == "audio"), None)
        if in_stream is None:
            raise ValueError("No audio found to convert to MP3.")
        outgoing = av.open(str(dest), mode="w", format="mp3")
        try:
            rate = int(in_stream.rate or 24000)
            layout = in_stream.layout or "mono"
            out_stream = outgoing.add_stream("libmp3lame", rate=rate)
            out_stream.bit_rate = bitrate
            resampler = av.AudioResampler(format="s16p", layout=layout, rate=rate)
            for frame in incoming.decode(in_stream):
                converted = resampler.resample(frame)
                frames = converted if isinstance(converted, list) else [converted]
                for item in frames:
                    if item is None:
                        continue
                    item.pts = None
                    for packet in out_stream.encode(item):
                        outgoing.mux(packet)
            flushed = resampler.resample(None)
            frames = flushed if isinstance(flushed, list) else [flushed]
            for item in frames:
                if item is None:
                    continue
                item.pts = None
                for packet in out_stream.encode(item):
                    outgoing.mux(packet)
            for packet in out_stream.encode(None):
                outgoing.mux(packet)
        finally:
            outgoing.close()
    finally:
        incoming.close()
    if not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError("MP3 export failed.")
    return dest


def export_voiceover(wav_path: Path) -> Path:
    mp3_path = wav_to_mp3(wav_path)
    # Retain the lossless source for optional enhancement and comparison.
    return mp3_path
