"""CLI: generate a local voiceover MP3 from a script."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from voice import DEFAULT_VOICE
from kokoro_voice import KokoroSpeaker, list_kokoro_voices


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a voiceover MP3 locally (Kokoro voices, or clone a voice you own)."
    )
    parser.add_argument("text", nargs="?", help="Script to speak. Omit if using --file.")
    parser.add_argument(
        "--file",
        help="Read script text from a file (UTF-8).",
    )
    parser.add_argument(
        "--voice",
        default=DEFAULT_VOICE,
        help="Voice id from --list-voices (Kokoro voice or a saved clone).",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speaking speed. 1.0 is normal, 1.2 is faster, 0.85 is slower.",
    )
    parser.add_argument(
        "--out",
        default="outputs",
        help="Directory for the MP3 file (default: outputs).",
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="Print available Kokoro voices and exit.",
    )
    parser.add_argument(
        "--clone",
        help="Path to a reference clip of a voice you have the right to clone.",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="Language code for cloned speech (default: en).",
    )
    parser.add_argument(
        "--keep-silence",
        action="store_true",
        help="Keep long pauses in the generated voiceover.",
    )
    parser.add_argument("--remove-silence", action="store_true", help="Opt in to shortening pauses; natural speech is kept by default.")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    if args.list_voices:
        from clone import list_cloned_voices

        cloned = list_cloned_voices()
        if cloned:
            print("Cloned")
            for item in cloned:
                print(f"  {item['id']:30}  {item['label']}")
            print("Preset")
        for item in list_kokoro_voices():
            prefix = "  " if cloned else ""
            print(f"{prefix}{item['id']:30}  {item['label']}")
        return

    if args.file:
        script = Path(args.file).expanduser().resolve().read_text(encoding="utf-8")
    elif args.text:
        script = args.text
    else:
        raise SystemExit("Pass script text, or --file path, or --list-voices.")

    keep_silence = bool(args.keep_silence) or not args.remove_silence

    if args.clone:
        from clone import VoiceCloner, save_cloned_voice

        ref = Path(args.clone).expanduser().resolve()
        saved = save_cloned_voice(ref, ref.stem, args.language)
        print(f"Saved '{saved['label']}' to the voice library as {saved['id']} ({saved.get('samples', 1)} samples).")
        print(f"Cloning from {ref.name} with XTTS (first run downloads a large model)...")
        refs = [Path(path) for path in (saved.get("paths") or [saved["path"]])]
        result = VoiceCloner().speak(
            script,
            speaker_wav=refs if len(refs) > 1 else refs[0],
            language=args.language,
            speed=args.speed,
            out_dir=Path(args.out).resolve(),
            voice_id=str(saved["id"]),
            remove_silence=not keep_silence,
        )
    else:
        from clone import get_cloned_voice

        cloned = get_cloned_voice(args.voice)
        if cloned:
            from clone import VoiceCloner

            print(f"Using cloned library voice '{cloned['label']}' ({len(cloned.get('paths') or [cloned['path']])} samples)...")
            refs = [Path(path) for path in (cloned.get("paths") or [cloned["path"]])]
            result = VoiceCloner().speak(
                script,
                speaker_wav=refs if len(refs) > 1 else refs[0],
                language=str(cloned.get("lang") or "en"),
                speed=args.speed,
                out_dir=Path(args.out).resolve(),
                voice_id=str(cloned["id"]),
                remove_silence=not keep_silence,
            )
        else:
            engine = KokoroSpeaker()
            print(f"Loading Kokoro voice '{args.voice}' (downloads once, then stays local)...")
            result = engine.speak(
                script,
                voice_id=args.voice,
                speed=args.speed,
                out_dir=Path(args.out).resolve(),
                remove_silence=not keep_silence,
            )
    extra = ""
    if result.silence_removed > 0.05:
        extra = f" | Removed {result.silence_removed:.1f}s silence"
    print(f"Voice: {result.voice} | Duration: {result.duration:.1f}s | {result.sample_rate} Hz{extra}")
    print(f"Wrote {result.path}")


if __name__ == "__main__":
    main()
