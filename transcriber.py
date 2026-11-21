"""Local video-to-transcript engine using SYSTRAN/faster-whisper."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from faster_whisper import WhisperModel

SUPPORTED_MEDIA = {
    ".mp4",
    ".mkv",
    ".mov",
    ".webm",
    ".avi",
    ".m4v",
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",
    ".ogg",
    ".aac",
}

MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v3")


def format_timestamp(seconds: float, *, vtt: bool = False) -> str:
    if seconds < 0:
        seconds = 0.0
    millis = int(round(seconds * 1000.0))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    sep = "." if vtt else ","
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{millis:03d}"


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class TranscriptResult:
    language: str
    language_probability: float
    duration: float
    segments: list[TranscriptSegment]

    @property
    def plain_text(self) -> str:
        return " ".join(seg.text.strip() for seg in self.segments if seg.text.strip()).strip()

    def to_srt(self) -> str:
        blocks = []
        for i, seg in enumerate(self.segments, start=1):
            text = seg.text.strip()
            if not text:
                continue
            blocks.append(
                f"{i}\n{format_timestamp(seg.start)} --> {format_timestamp(seg.end)}\n{text}\n"
            )
        return "\n".join(blocks).strip() + ("\n" if blocks else "")

    def to_vtt(self) -> str:
        lines = ["WEBVTT", ""]
        for seg in self.segments:
            text = seg.text.strip()
            if not text:
                continue
            lines.append(
                f"{format_timestamp(seg.start, vtt=True)} --> {format_timestamp(seg.end, vtt=True)}"
            )
            lines.append(text)
            lines.append("")
        return "\n".join(lines)

    def to_json(self) -> str:
        payload = {
            "language": self.language,
            "language_probability": self.language_probability,
            "duration": self.duration,
            "text": self.plain_text,
            "segments": [
                {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
                for seg in self.segments
            ],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)


class LocalTranscriber:
    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        download_root: str | Path | None = None,
    ) -> None:
        if model_size not in MODEL_SIZES:
            raise ValueError(f"model_size must be one of {MODEL_SIZES}")
        root = Path(download_root) if download_root else Path(__file__).resolve().parent / "models"
        root.mkdir(parents=True, exist_ok=True)
        self.model_size = model_size
        self.model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=str(root),
        )

    def transcribe(
        self,
        media_path: str | Path,
        language: str | None = None,
        beam_size: int = 5,
        vad_filter: bool = False,
    ) -> TranscriptResult:
        path = Path(media_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if path.suffix.lower() not in SUPPORTED_MEDIA:
            raise ValueError(
                f"Unsupported file type '{path.suffix}'. Use one of: {', '.join(sorted(SUPPORTED_MEDIA))}"
            )

        segments_iter, info = self.model.transcribe(
            str(path),
            language=language or None,
            beam_size=beam_size,
            vad_filter=vad_filter,
            word_timestamps=False,
        )

        segments = [
            TranscriptSegment(start=seg.start, end=seg.end, text=seg.text)
            for seg in segments_iter
        ]
        return TranscriptResult(
            language=info.language,
            language_probability=float(info.language_probability),
            duration=float(info.duration or 0.0),
            segments=segments,
        )


def write_outputs(result: TranscriptResult, source: Path, out_dir: Path, formats: list[str]) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = source.stem
    written: list[Path] = []
    writers = {
        "txt": lambda: result.plain_text + ("\n" if result.plain_text else ""),
        "srt": result.to_srt,
        "vtt": result.to_vtt,
        "json": lambda: result.to_json() + "\n",
    }
    for fmt in formats:
        if fmt not in writers:
            raise ValueError(f"Unknown format '{fmt}'. Choose from: {', '.join(writers)}")
        dest = out_dir / f"{stem}.{fmt}"
        dest.write_text(writers[fmt](), encoding="utf-8")
        written.append(dest)
    return written
