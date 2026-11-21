"""Local text-to-sound-effects using AudioLDM small."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

from cues import extract_sfx_cues
from music import _fade, _match_channels, _resample
from silence import load_media_audio, write_wav
from voice import SpeakResult, export_voiceover, make_audio_stem, unique_path

ROOT = Path(__file__).resolve().parent
MODEL_ID = "cvssp/audioldm-s-full-v2"
MIN_SECONDS = 2
MAX_SECONDS = 8
DEFAULT_SECONDS = 4
MAX_SCRIPT_CHARS = 8_000
SFX_GAIN = 0.42
NEGATIVE_PROMPT = "music, singing, speech, vocals, low quality, noise"

SFX_STYLES: list[tuple[str, str]] = [
    ("auto", "Auto from the text"),
    ("impact", "Impact / hit"),
    ("whoosh", "Whoosh / motion"),
    ("nature", "Nature"),
    ("crowd", "Crowd"),
    ("mechanical", "Mechanical"),
    ("scifi", "Sci-fi"),
    ("explosion", "Explosion"),
]


def clamp_sfx_seconds(value: float) -> int:
    return int(min(MAX_SECONDS, max(MIN_SECONDS, round(float(value)))))


def sfx_prompt_from_text(text: str, style: str = "auto") -> str:
    return str(extract_sfx_cues(text, style)["prompt"])


def mix_over_voice(voice_path: str | Path, sfx_path: str | Path, gain: float = SFX_GAIN) -> Path:
    voice_file = Path(voice_path)
    sfx_file = Path(sfx_path)
    if not voice_file.exists():
        raise FileNotFoundError(f"Voiceover not found: {voice_file}")
    voice, voice_rate = load_media_audio(voice_file)
    sfx, sfx_rate = load_media_audio(sfx_file)
    voice = np.asarray(voice, dtype=np.float32)
    sfx = np.asarray(sfx, dtype=np.float32)
    if voice.ndim == 1:
        voice = voice.reshape(-1, 1)
    if sfx.ndim == 1:
        sfx = sfx.reshape(-1, 1)
    sfx = _resample(sfx, sfx_rate, voice_rate)
    sfx = _match_channels(sfx, voice.shape[1])
    needed = voice.shape[0]
    if sfx.shape[0] < needed:
        pad = np.zeros((needed - sfx.shape[0], sfx.shape[1]), dtype=np.float32)
        sfx = np.concatenate([sfx, pad], axis=0)
    else:
        sfx = sfx[:needed]
    sfx = _fade(sfx, voice_rate, 0.04)
    mixed = np.clip(voice + sfx * float(gain), -1.0, 1.0)
    dest = unique_path(voice_file.with_name(f"{voice_file.stem}-sfx.wav"))
    write_wav(dest, mixed, voice_rate)
    return export_voiceover(dest)


def mix_clips_over_voice(
    voice_path: str | Path,
    sfx_paths: list[str | Path],
    gain: float = SFX_GAIN,
) -> Path:
    files = [Path(path) for path in sfx_paths if path]
    if not files:
        raise ValueError("No sound effects to mix over the voiceover.")
    if len(files) == 1:
        return mix_over_voice(voice_path, files[0], gain)
    voice_file = Path(voice_path)
    if not voice_file.exists():
        raise FileNotFoundError(f"Voiceover not found: {voice_file}")
    voice, voice_rate = load_media_audio(voice_file)
    voice = np.asarray(voice, dtype=np.float32)
    if voice.ndim == 1:
        voice = voice.reshape(-1, 1)
    mixed = voice.copy()
    needed = mixed.shape[0]
    count = len(files)
    for index, sfx_file in enumerate(files):
        sfx, sfx_rate = load_media_audio(sfx_file)
        sfx = np.asarray(sfx, dtype=np.float32)
        if sfx.ndim == 1:
            sfx = sfx.reshape(-1, 1)
        sfx = _resample(sfx, sfx_rate, voice_rate)
        sfx = _match_channels(sfx, mixed.shape[1])
        sfx = _fade(sfx, voice_rate, 0.04)
        leftover = max(0, needed - sfx.shape[0])
        start = 0 if leftover == 0 else int(index * leftover / max(1, count - 1))
        end = min(needed, start + sfx.shape[0])
        length = end - start
        if length <= 0:
            continue
        mixed[start:end] += sfx[:length] * float(gain)
    mixed = np.clip(mixed, -1.0, 1.0)
    dest = unique_path(voice_file.with_name(f"{voice_file.stem}-sfx.wav"))
    write_wav(dest, mixed, voice_rate)
    return export_voiceover(dest)


class SfxGenerator:
    def __init__(self) -> None:
        cache = ROOT / "models" / "audioldm"
        cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(cache))
        os.environ.setdefault("TRANSFORMERS_CACHE", str(cache))
        self.cache_dir = cache
        self._lock = threading.Lock()
        self._pipe = None
        self._device = "cpu"
        self._rate = 16000

    def _load(self) -> None:
        if self._pipe is not None:
            return
        try:
            import torch
            from diffusers import AudioLDMPipeline
        except ImportError as exc:
            raise RuntimeError(
                "Sound effects need the diffusers package. Run: pip install diffusers accelerate"
            ) from exc

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if self._device == "cuda" else torch.float32
        self._pipe = AudioLDMPipeline.from_pretrained(
            MODEL_ID,
            cache_dir=str(self.cache_dir),
            torch_dtype=dtype,
        )
        self._pipe = self._pipe.to(self._device)
        vocoder = getattr(self._pipe, "vocoder", None)
        config = getattr(vocoder, "config", None) if vocoder is not None else None
        self._rate = int(getattr(config, "sampling_rate", None) or 16000)

    def _render_clip(self, prompt: str, duration: int, dest_dir: Path, label: str) -> SpeakResult:
        stem = make_audio_stem(label or "sfx", "sfx")
        wav_path = unique_path(dest_dir / f"{stem}.wav")
        with self._lock:
            self._load()
            result = self._pipe(
                prompt,
                audio_length_in_s=float(duration),
                num_inference_steps=12,
                guidance_scale=2.5,
                negative_prompt=NEGATIVE_PROMPT,
            )
            wave = np.asarray(result.audios[0], dtype=np.float32)
            write_wav(wav_path, wave, self._rate)
        mp3_path = export_voiceover(wav_path)
        frames = int(np.asarray(wave).shape[0])
        return SpeakResult(
            path=mp3_path,
            voice="audioldm-sfx",
            duration=frames / float(self._rate) if self._rate else float(duration),
            sample_rate=self._rate,
            speed=1.0,
        )

    def generate(
        self,
        text: str,
        style: str = "auto",
        seconds: float = DEFAULT_SECONDS,
        out_dir: Path | None = None,
        mix_voice: str | Path | None = None,
    ) -> dict[str, object]:
        script = " ".join((text or "").split())
        if not script:
            raise ValueError("Enter a sound, like 'glass shatter' or paste a script scene.")
        if len(script) > MAX_SCRIPT_CHARS:
            raise ValueError(f"Text is too long (max {MAX_SCRIPT_CHARS} characters).")
        duration = clamp_sfx_seconds(seconds)
        cues = extract_sfx_cues(script, style)
        events = list(cues.get("events") or [])
        if not events:
            raise ValueError("No sound-effect words were found in that script.")
        dest_dir = Path(out_dir) if out_dir else ROOT / "outputs"
        dest_dir.mkdir(parents=True, exist_ok=True)
        clips: list[dict[str, object]] = []
        for event in events:
            word = str(event.get("word") or "sfx")
            generated = self._render_clip(str(event["prompt"]), duration, dest_dir, word)
            clips.append(
                {
                    "id": str(event.get("id") or "scene"),
                    "word": word,
                    "prompt": str(event.get("prompt") or ""),
                    "result": generated,
                }
            )
        primary: SpeakResult = clips[0]["result"]  # type: ignore[assignment]
        mixed = False
        if mix_voice:
            clip_paths = []
            for item in clips:
                clip = item.get("result")
                if isinstance(clip, SpeakResult):
                    clip_paths.append(clip.path)
            mixed_path = mix_clips_over_voice(mix_voice, clip_paths)
            audio, mix_rate = load_media_audio(mixed_path)
            primary = SpeakResult(
                path=mixed_path,
                voice="audioldm-sfx-mix",
                duration=audio.shape[0] / float(mix_rate) if mix_rate else primary.duration,
                sample_rate=mix_rate,
                speed=1.0,
            )
            mixed = True
        return {
            "primary": primary,
            "clips": clips,
            "cues": cues,
            "mixed": mixed,
        }
