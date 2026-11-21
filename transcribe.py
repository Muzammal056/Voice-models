"""CLI: transcribe a local video or audio file to text/subtitles."""

from __future__ import annotations

import argparse
from pathlib import Path

from transcriber import MODEL_SIZES, LocalTranscriber, write_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe a local video or audio file with Whisper (runs fully offline after the first model download)."
    )
    parser.add_argument("input", help="Path to a video or audio file")
    parser.add_argument(
        "--model",
        default="small",
        choices=MODEL_SIZES,
        help="Whisper model size. 'small' is a good CPU default. Larger = more accurate, slower.",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Language code like en, es, fr. Omit to auto-detect.",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=["txt", "srt"],
        choices=["txt", "srt", "vtt", "json"],
        help="Output formats to write.",
    )
    parser.add_argument(
        "--out",
        default="outputs",
        help="Directory for transcript files (default: outputs).",
    )
    parser.add_argument(
        "--vad",
        action="store_true",
        help="Filter out long silences. Off by default because it can drop speech.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = Path(args.input).expanduser().resolve()
    print(f"Loading Whisper '{args.model}' on CPU (int8)...")
    engine = LocalTranscriber(model_size=args.model)
    print(f"Transcribing {source.name}...")
    result = engine.transcribe(source, language=args.language, vad_filter=args.vad)
    written = write_outputs(result, source, Path(args.out).resolve(), args.formats)
    print(
        f"Detected language: {result.language} "
        f"({result.language_probability:.0%} confidence)"
    )
    print(f"Duration: {result.duration:.1f}s | Segments: {len(result.segments)}")
    print()
    print(result.plain_text or "(no speech detected)")
    print()
    for path in written:
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
