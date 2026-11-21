"""Clone a speaker from a short reference clip with XTTS v2."""

from __future__ import annotations

import json
import os
import re
import threading
import wave
from datetime import datetime
from pathlib import Path

import av
import numpy as np

from voice import SpeakResult, export_voiceover, make_audio_stem, unique_path, wav_duration

ROOT = Path(__file__).resolve().parent
CLONE_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
LIBRARY_DIR_NAME = "cloned"
LIBRARY_INDEX = "voices.json"
REF_RATE = 22050
MIN_REF_SECONDS = 3.0
MAX_REF_SECONDS = 12.0
SCAN_SECONDS = 40.0
MAX_SCRIPT_CHARS = 8_000
_UNSAFE_ID = re.compile(r"[^\w\s-]", re.UNICODE)

CLONE_LANGUAGES = [
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("hi", "Hindi"),
    ("ar", "Arabic"),
    ("zh-cn", "Chinese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("ru", "Russian"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
]


def _configure_model_home() -> Path:
    home = ROOT / "models" / "coqui"
    home.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("TTS_HOME", str(home))
    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    return home


def _load_audio_without_torchcodec(audiopath, sampling_rate):
    """Load WAV with the stdlib so XTTS does not need torchcodec/FFmpeg."""
    import torch

    with wave.open(str(audiopath), "rb") as wav_file:
        channels = wav_file.getnchannels()
        width = wav_file.getsampwidth()
        native_rate = wav_file.getframerate()
        frames = wav_file.readframes(wav_file.getnframes())

    if width == 2:
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {width} bytes")

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)

    audio = torch.from_numpy(np.ascontiguousarray(data)).unsqueeze(0)
    if native_rate != sampling_rate:
        import torchaudio

        audio = torchaudio.functional.resample(audio, native_rate, sampling_rate)
    audio.clip_(-1, 1)
    return audio


def _patch_xtts_audio_loader() -> None:
    import TTS.tts.models.xtts as xtts_mod

    if getattr(xtts_mod, "_local_wav_loader", False):
        return
    xtts_mod.load_audio = _load_audio_without_torchcodec
    xtts_mod._local_wav_loader = True


def cloned_dir() -> Path:
    path = ROOT / "models" / LIBRARY_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _voice_id_from_label(label: str) -> str:
    cleaned = _UNSAFE_ID.sub("", label).strip().lower()
    cleaned = re.sub(r"[\s_]+", "-", cleaned).strip("-")
    return (cleaned[:40] or "cloned")


def _read_library() -> list[dict]:
    index = cloned_dir() / LIBRARY_INDEX
    if not index.exists():
        return []
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return list(data.get("voices") or [])


def _write_library(voices: list[dict]) -> None:
    (cloned_dir() / LIBRARY_INDEX).write_text(
        json.dumps({"voices": voices}, indent=2),
        encoding="utf-8",
    )


def list_cloned_voices() -> list[dict[str, object]]:
    listed: list[dict[str, object]] = []
    folder = cloned_dir()
    for item in _read_library():
        voice_id = str(item.get("id") or "")
        paths = _library_wavs(item, folder)
        if not voice_id or not paths:
            continue
        listed.append(
            {
                "id": voice_id,
                "label": str(item.get("label") or voice_id),
                "lang": str(item.get("language") or "en"),
                "kind": "clone",
                "downloaded": True,
                "path": str(paths[0]),
                "paths": [str(path) for path in paths],
                "samples": len(paths),
            }
        )
    return listed


def _library_wavs(item: dict, folder: Path) -> list[Path]:
    names: list[str] = []
    raw_files = item.get("files")
    if isinstance(raw_files, list) and raw_files:
        names = [str(name) for name in raw_files if name]
    elif item.get("file"):
        names = [str(item["file"])]
    else:
        voice_id = str(item.get("id") or "")
        if voice_id:
            names = [f"{voice_id}.wav"]
    paths: list[Path] = []
    for name in names:
        wav = folder / Path(name).name
        if wav.exists() and wav.stat().st_size > 0:
            paths.append(wav)
    return paths


def get_cloned_voice(voice_id: str) -> dict[str, object] | None:
    for item in list_cloned_voices():
        if item["id"] == voice_id:
            return item
    return None


def _cloned_payload(item: dict, folder: Path) -> dict[str, object]:
    paths = _library_wavs(item, folder)
    return {
        "id": str(item.get("id") or ""),
        "label": str(item.get("label") or item.get("id") or ""),
        "lang": str(item.get("language") or "en"),
        "kind": "clone",
        "downloaded": True,
        "path": str(paths[0]) if paths else "",
        "paths": [str(path) for path in paths],
        "samples": len(paths),
    }


def save_cloned_voice(
    source: str | Path,
    label: str,
    language: str = "en",
) -> dict[str, object]:
    name = " ".join(str(label).split())
    if not name:
        raise ValueError("Give the cloned voice a name to save it in the library.")
    lang = (language or "en").strip().lower()
    if lang not in {code for code, _ in CLONE_LANGUAGES}:
        raise ValueError(f"Unsupported clone language '{language}'.")
    voice_id = _voice_id_from_label(name)
    folder = cloned_dir()
    voices = _read_library()
    existing = next((item for item in voices if item.get("id") == voice_id), None)
    current_files: list[str] = []
    if existing:
        if isinstance(existing.get("files"), list) and existing["files"]:
            current_files = [str(item) for item in existing["files"] if item]
        elif existing.get("file"):
            current_files = [str(existing["file"])]
    if current_files:
        dest = folder / f"{voice_id}-{len(current_files) + 1}.wav"
    else:
        dest = folder / f"{voice_id}.wav"
    duration = prepare_reference(source, dest)
    files = current_files + [dest.name]
    total = float(existing.get("duration") or 0) + duration if existing else duration
    record = {
        "id": voice_id,
        "label": name,
        "file": files[0],
        "files": files,
        "language": lang,
        "duration": round(total, 2),
        "samples": len(files),
    }
    voices = [item for item in voices if item.get("id") != voice_id]
    voices.insert(0, record)
    _write_library(voices)
    return _cloned_payload(record, folder)


def _audio_to_s16_mono(array: np.ndarray) -> bytes:
    data = np.asarray(array)
    if data.ndim > 1:
        data = data[0] if data.shape[0] <= data.shape[-1] else data[:, 0]
    if np.issubdtype(data.dtype, np.floating):
        data = np.clip(data, -1.0, 1.0)
        data = (data * 32767.0).astype(np.int16)
    else:
        data = data.astype(np.int16, copy=False)
    return data.tobytes()


def _pcm_from_audio(source_path: Path, max_seconds: float | None) -> bytes:
    container = av.open(str(source_path))
    try:
        audio_streams = [stream for stream in container.streams if stream.type == "audio"]
        if not audio_streams:
            raise ValueError("That file has no audio to clone from.")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=REF_RATE)
        chunks: list[bytes] = []
        max_bytes = 0 if not max_seconds or max_seconds <= 0 else int(REF_RATE * 2 * max_seconds)
        collected = 0

        def consume(result) -> None:
            nonlocal collected
            frames = result if isinstance(result, list) else [result]
            for frame in frames:
                if frame is None:
                    continue
                raw = _audio_to_s16_mono(frame.to_ndarray())
                if max_bytes:
                    remain = max_bytes - collected
                    if remain <= 0:
                        return
                    raw = raw[:remain]
                chunks.append(raw)
                collected += len(raw)

        for frame in container.decode(audio_streams[0]):
            consume(resampler.resample(frame))
            if max_bytes and collected >= max_bytes:
                break
        consume(resampler.resample(None))
    finally:
        container.close()
    audio = b"".join(chunks)
    if len(audio) % 2:
        audio = audio[:-1]
    return audio


def _loudest_windows(pcm: bytes, window_seconds: float, count: int) -> list[bytes]:
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return []
    frame = max(int(REF_RATE * 0.05), 1)
    n_frames = samples.size // frame
    window = int(REF_RATE * window_seconds)
    if n_frames < 8 or samples.size <= window:
        return [_normalize_pcm(np.frombuffer(pcm, dtype=np.int16).tobytes())]

    frames = samples[: n_frames * frame].reshape(n_frames, frame)
    rms = np.sqrt(np.mean(frames * frames, axis=1) + 1e-8)
    win_frames = max(int(round(window_seconds / 0.05)), 2)
    if n_frames <= win_frames:
        return [_normalize_pcm(samples[:window].astype(np.int16).tobytes())]

    csum = np.concatenate([[0.0], np.cumsum(rms)])
    csum2 = np.concatenate([[0.0], np.cumsum(rms * rms)])
    total = csum[win_frames:] - csum[:-win_frames]
    mean = total / win_frames
    var = np.maximum((csum2[win_frames:] - csum2[:-win_frames]) / win_frames - mean * mean, 0.0)
    std = np.sqrt(var)
    cv = std / np.maximum(mean, 1e-6)
    quiet_thresh = max(float(np.percentile(rms, 30)), 300.0)
    quiet = (rms < quiet_thresh).astype(np.float64)
    qsum = np.concatenate([[0.0], np.cumsum(quiet)])
    pause = (qsum[win_frames:] - qsum[:-win_frames]) / win_frames
    score = mean * (0.3 + cv) * (0.35 + np.clip(pause, 0.06, 0.42))
    score = np.where((mean < 500) | (pause > 0.72), -1.0, score)

    order = np.argsort(score)[::-1]
    chosen: list[int] = []
    min_gap = int(win_frames * 0.9)
    for idx in order:
        if score[idx] < 0:
            break
        start_frame = int(idx)
        if all(abs(start_frame - other) >= min_gap for other in chosen):
            chosen.append(start_frame)
        if len(chosen) >= count:
            break

    out: list[bytes] = []
    for start_frame in chosen:
        start = start_frame * frame
        chunk = samples[start : start + win_frames * frame]
        out.append(_normalize_pcm(chunk.astype(np.int16).tobytes()))
    return out


def _normalize_pcm(pcm: bytes, peak: float = 0.89) -> bytes:
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    max_abs = float(np.max(np.abs(samples))) if samples.size else 0.0
    if max_abs < 1:
        return pcm
    scaled = np.clip(samples * (peak * 32767.0 / max_abs), -32768, 32767).astype(np.int16)
    return scaled.tobytes()


def _write_mono_wav(dest_path: Path, pcm: bytes) -> float:
    if len(pcm) % 2:
        pcm = pcm[:-1]
    duration = (len(pcm) // 2) / float(REF_RATE)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(REF_RATE)
        wav_file.writeframes(pcm)
    return duration


def prepare_reference(source: str | Path, dest: str | Path, max_seconds: float = MAX_REF_SECONDS) -> float:
    source_path = Path(source)
    dest_path = Path(dest)
    if not source_path.exists():
        raise FileNotFoundError(f"Reference voice file not found: {source_path}")
    pcm = _pcm_from_audio(source_path, SCAN_SECONDS)
    windows = _loudest_windows(pcm, max_seconds, 1)
    if not windows:
        raise ValueError(
            "Need at least 3 seconds of speech. A 10-12 second clip of one person, "
            "no music, clones best."
        )
    duration = _write_mono_wav(dest_path, windows[0])
    if duration < MIN_REF_SECONDS:
        raise ValueError(
            "Need at least 3 seconds of speech. A 10-12 second clip of one person, "
            "no music, clones best."
        )
    return duration


def prepare_reference_windows(
    source: str | Path,
    dests: list[Path],
    window_seconds: float = MAX_REF_SECONDS,
    count: int | None = None,
    scan_seconds: float | None = SCAN_SECONDS,
) -> list[Path]:
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"Reference voice file not found: {source_path}")
    want = count or len(dests)
    pcm = _pcm_from_audio(source_path, scan_seconds)
    windows = _loudest_windows(pcm, window_seconds, want)
    if not windows:
        raise ValueError("Could not find enough clean speech in that clip.")
    written: list[Path] = []
    for dest, chunk in zip(dests, windows):
        duration = _write_mono_wav(Path(dest), chunk)
        if duration >= MIN_REF_SECONDS:
            written.append(Path(dest))
    if not written:
        raise ValueError("Need at least 3 seconds of speech in the reference clip.")
    return written


def _detect_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


class VoiceCloner:
    def __init__(self) -> None:
        self.model_home = _configure_model_home()
        self.ref_dir = ROOT / "uploads" / "clone"
        self.ref_dir.mkdir(parents=True, exist_ok=True)
        self.device = _detect_device()
        self._tts = None
        self._lock = threading.Lock()

    def _load(self):
        if self._tts is not None:
            return self._tts
        _configure_model_home()
        from TTS.api import TTS

        _patch_xtts_audio_loader()
        api = TTS(CLONE_MODEL).to(self.device)
        self._tts = api
        return api

    def speak(
        self,
        text: str,
        speaker_wav: str | Path | list[str | Path],
        language: str = "en",
        speed: float = 1.0,
        out_dir: Path | None = None,
        name: str | None = None,
        voice_id: str = "clone",
        remove_silence: bool = True,
    ) -> SpeakResult:
        script = " ".join(text.split())
        if not script:
            raise ValueError("Enter some script text to speak.")
        if len(script) > MAX_SCRIPT_CHARS:
            raise ValueError(f"Script is too long for cloning (max {MAX_SCRIPT_CHARS} characters).")
        lang = (language or "en").strip().lower()
        if lang not in {code for code, _ in CLONE_LANGUAGES}:
            raise ValueError(f"Unsupported clone language '{language}'.")
        speed = min(1.4, max(0.7, float(speed)))

        dest_dir = Path(out_dir) if out_dir else ROOT / "outputs"
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        sources = speaker_wav if isinstance(speaker_wav, (list, tuple)) else [speaker_wav]
        library = cloned_dir().resolve()
        refs: list[str] = []
        for index, item in enumerate(sources):
            source = Path(item)
            if source.resolve().parent == library and source.suffix.lower() == ".wav":
                refs.append(str(source))
                continue
            ref_wav = self.ref_dir / f"reference-{stamp}-{index}.wav"
            prepare_reference(source, ref_wav)
            refs.append(str(ref_wav))
        if not refs:
            raise ValueError("Need at least one reference clip to clone from.")

        stem = name or make_audio_stem(script, voice_id)
        dest = unique_path(dest_dir / f"{stem}.wav")

        with self._lock:
            tts = self._load()
            kwargs = {
                "text": script,
                "file_path": str(dest),
                "speaker_wav": refs if len(refs) > 1 else refs[0],
                "language": lang,
                "split_sentences": True,
                "temperature": 0.6,
                "top_p": 0.8,
                "top_k": 40,
                "repetition_penalty": 7.0,
                "sound_norm_refs": True,
            }
            try:
                tts.tts_to_file(**kwargs, speed=speed)
            except TypeError:
                kwargs.pop("sound_norm_refs", None)
                try:
                    tts.tts_to_file(**kwargs, speed=speed)
                except TypeError:
                    tts.tts_to_file(
                        text=script,
                        file_path=str(dest),
                        speaker_wav=kwargs["speaker_wav"],
                        language=lang,
                        split_sentences=True,
                    )

        original_duration, sample_rate = wav_duration(dest)
        silence_removed = 0.0
        if remove_silence:
            from silence import apply_to_wav

            try:
                stats = apply_to_wav(dest)
                duration, sample_rate = wav_duration(dest)
                silence_removed = stats.removed
            except ValueError:
                duration = original_duration
        else:
            duration = original_duration
        return SpeakResult(
            path=export_voiceover(dest),
            voice=voice_id,
            duration=duration,
            sample_rate=sample_rate,
            speed=speed,
            original_duration=original_duration,
            silence_removed=silence_removed,
        )
