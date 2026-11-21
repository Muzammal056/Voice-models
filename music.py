"""Local text-to-background-music using Meta MusicGen small."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

from cues import extract_music_cues
from silence import load_media_audio, write_wav
from voice import SpeakResult, export_voiceover, make_audio_stem, unique_path

ROOT = Path(__file__).resolve().parent
MODEL_ID = "facebook/musicgen-small"
TOKENS_PER_SECOND = 50
MIN_SECONDS = 6
MAX_SECONDS = 15
DEFAULT_SECONDS = 8
MAX_SCRIPT_CHARS = 8_000
MUSIC_GAIN = 0.16

MUSIC_STYLES: list[tuple[str, str]] = [
    ("auto", "Auto from the text"),
    ("cinematic", "Cinematic documentary"),
    ("tense", "Tense / spy"),
    ("curious", "Curious science"),
    ("playful", "Playful"),
    ("calm", "Calm ambient"),
    ("epic", "Epic trailer"),
]


def clamp_seconds(value: float) -> int:
    return int(min(MAX_SECONDS, max(MIN_SECONDS, round(float(value)))))


def prompt_from_text(text: str, style: str = "auto") -> str:
    return str(extract_music_cues(text, style)["prompt"])


def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    data = np.asarray(audio, dtype=np.float32)
    if src_rate == dst_rate or data.size == 0:
        return data
    n_src = data.shape[0]
    n_dst = max(1, int(round(n_src * dst_rate / src_rate)))
    x_old = np.linspace(0.0, 1.0, n_src, endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_dst, endpoint=False)
    if data.ndim == 1:
        return np.interp(x_new, x_old, data).astype(np.float32)
    cols = [np.interp(x_new, x_old, data[:, idx]) for idx in range(data.shape[1])]
    return np.stack(cols, axis=1).astype(np.float32)


def _match_channels(audio: np.ndarray, channels: int) -> np.ndarray:
    data = np.asarray(audio, dtype=np.float32)
    if data.ndim == 1:
        data = data.reshape(-1, 1)
    if data.shape[1] == channels:
        return data
    if channels == 1:
        return data.mean(axis=1, keepdims=True)
    if data.shape[1] == 1:
        return np.repeat(data, channels, axis=1)
    return data[:, :channels]


def _fade(audio: np.ndarray, rate: int, seconds: float = 0.08) -> np.ndarray:
    data = np.asarray(audio, dtype=np.float32)
    n = max(1, int(rate * seconds))
    n = min(n, data.shape[0] // 2 or 1)
    fade_in = np.linspace(0.0, 1.0, n, dtype=np.float32)
    fade_out = fade_in[::-1]
    data = data.copy()
    data[:n] *= fade_in.reshape(-1, 1)
    data[-n:] *= fade_out.reshape(-1, 1)
    return data


def mix_under_voice(voice_path: str | Path, music_path: str | Path, gain: float = MUSIC_GAIN) -> Path:
    voice_file = Path(voice_path)
    music_file = Path(music_path)
    if not voice_file.exists():
        raise FileNotFoundError(f"Voiceover not found: {voice_file}")
    voice, voice_rate = load_media_audio(voice_file)
    music, music_rate = load_media_audio(music_file)
    voice = np.asarray(voice, dtype=np.float32)
    music = np.asarray(music, dtype=np.float32)
    if voice.ndim == 1:
        voice = voice.reshape(-1, 1)
    if music.ndim == 1:
        music = music.reshape(-1, 1)
    music = _resample(music, music_rate, voice_rate)
    music = _match_channels(music, voice.shape[1])
    needed = voice.shape[0]
    if music.shape[0] < needed:
        repeats = int(np.ceil(needed / max(1, music.shape[0])))
        music = np.tile(music, (repeats, 1))
    music = _fade(music[:needed], voice_rate)
    mixed = np.clip(voice + music * float(gain), -1.0, 1.0)
    dest = unique_path(voice_file.with_name(f"{voice_file.stem}-bgm.wav"))
    write_wav(dest, mixed, voice_rate)
    return export_voiceover(dest)


class MusicGenerator:
    def __init__(self) -> None:
        cache = ROOT / "models" / "musicgen"
        cache.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(cache))
        os.environ.setdefault("TRANSFORMERS_CACHE", str(cache))
        self.cache_dir = cache
        self._lock = threading.Lock()
        self._model = None
        self._processor = None
        self._device = "cpu"

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoProcessor, MusicgenForConditionalGeneration

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._processor = AutoProcessor.from_pretrained(MODEL_ID, cache_dir=str(self.cache_dir))
        self._model = MusicgenForConditionalGeneration.from_pretrained(
            MODEL_ID,
            cache_dir=str(self.cache_dir),
        )
        self._model.to(self._device)
        self._model.eval()

    def generate(
        self,
        text: str,
        style: str = "auto",
        seconds: float = DEFAULT_SECONDS,
        out_dir: Path | None = None,
        mix_voice: str | Path | None = None,
    ) -> SpeakResult:
        script = " ".join((text or "").split())
        if not script:
            raise ValueError("Enter a script or topic so the music can follow the text.")
        if len(script) > MAX_SCRIPT_CHARS:
            raise ValueError(f"Text is too long (max {MAX_SCRIPT_CHARS} characters).")
        duration = clamp_seconds(seconds)
        cues = extract_music_cues(script, style)
        prompt = str(cues["prompt"])
        dest_dir = Path(out_dir) if out_dir else ROOT / "outputs"
        dest_dir.mkdir(parents=True, exist_ok=True)
        cue_words = " ".join(str(word) for word in (cues.get("words") or [])[:4]) or script
        stem = make_audio_stem(cue_words, "bgm")
        wav_path = unique_path(dest_dir / f"{stem}.wav")

        with self._lock:
            self._load()
            import torch

            inputs = self._processor(
                text=[prompt],
                padding=True,
                return_tensors="pt",
            )
            inputs = {key: value.to(self._device) for key, value in inputs.items()}
            tokens = max(64, int(duration * TOKENS_PER_SECOND))
            with torch.inference_mode():
                audio_values = self._model.generate(
                    **inputs,
                    max_new_tokens=tokens,
                    do_sample=True,
                    guidance_scale=3.0,
                )
            rate = int(self._model.config.audio_encoder.sampling_rate)
            wave = audio_values[0].detach().cpu().numpy()
            if wave.ndim == 2:
                wave = wave.T if wave.shape[0] < wave.shape[1] else wave
            write_wav(wav_path, wave, rate)

        mp3_path = export_voiceover(wav_path)
        frames = int(np.asarray(wave).shape[0])
        generated = SpeakResult(
            path=mp3_path,
            voice="musicgen-small",
            duration=frames / float(rate) if rate else float(duration),
            sample_rate=rate,
            speed=1.0,
        )
        if mix_voice:
            mixed = mix_under_voice(mix_voice, mp3_path)
            audio, mix_rate = load_media_audio(mixed)
            generated = SpeakResult(
                path=mixed,
                voice="musicgen-small-mix",
                duration=audio.shape[0] / float(mix_rate) if mix_rate else generated.duration,
                sample_rate=mix_rate,
                speed=1.0,
            )
        return generated
