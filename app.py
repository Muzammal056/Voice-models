"""Local browser UI for voice generation, enhancement and transcription."""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
import traceback
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from captions import captions_from_script, rechunk_transcript, save_srt
from clone import CLONE_LANGUAGES, VoiceCloner, get_cloned_voice, list_cloned_voices, save_cloned_voice
from silence import DEFAULT_MAX_PAUSE, clamp_max_pause, remove_silence_file
from transcriber import MODEL_SIZES, LocalTranscriber, SUPPORTED_MEDIA, write_outputs
from voice import DEFAULT_VOICE
from audio_library import VoiceLibrary
from kokoro_voice import KokoroSpeaker, list_kokoro_voices
import enhancement

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
UPLOAD_DIR = ROOT / "uploads"
voice_library = VoiceLibrary(OUTPUT_DIR, ROOT / "voice-history.json", ['25hours_single', 'aegis_female', 'aivars', 'alan', 'alba', 'ald', 'alex', 'alma', 'amir', 'amy', 'anna', 'antton', 'arjun', 'artur', 'bass', 'berta', 'bryce', 'bui', 'cadu', 'carlfm', 'chaowen', 'chitwan', 'claude', 'cori', 'daniela', 'danny', 'darkman', 'davefx', 'denis', 'dfki', 'dimitar', 'dmitri', 'edon', 'edresson', 'eva_k', 'faber', 'fasih', 'ganji', 'ganji_adabi', 'gilles', 'gor', 'gosia', 'gwryw_gogleddol', 'gyro', 'harri', 'hfc_female', 'hfc_male', 'huayan', 'imre', 'irina', 'iseke', 'jeff', 'jenny_dioco', 'jirka', 'joe', 'john', 'joy', 'kareem', 'karlsson', 'kasandra', 'kathleen', 'kerstin', 'kristin', 'kss', 'kusal', 'lada', 'lanfrica', 'lessac', 'lili', 'lisa', 'ljspeech', 'maider', 'marylux', 'maya', 'mc_speech', 'meera', 'mihai', 'mike', 'mls_10246', 'mls_1840', 'mls_5809', 'mls_6892', 'mls_7432', 'mls_9972', 'mykyta', 'nathalie', 'natia', 'news_tts', 'norman', 'northern_english_male', 'nst', 'oleksa', 'padmavathi', 'paola', 'pavoque', 'pim', 'pratham', 'priyamvada', 'ramona', 'rapunzelina', 'raya', 'rdh', 'reginute1', 'reza_ibrahim', 'riccardo', 'rohan', 'ronnie', 'ruslan', 'ryan', 'salka', 'sam', 'saspeech', 'serena', 'siwis', 'southern_english_female', 'steinn', 'talesyntese', 'tetiana', 'thorsten', 'tom', 'tsync2', 'tugão', 'ugla', 'upc_ona', 'upc_pau', 'vais1000', 'venkatesh', 'xiao_ya'])

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2 GB
app.config["MAX_FORM_MEMORY_SIZE"] = 2 * 1024 * 1024 * 1024
app.config["MAX_FORM_PARTS"] = 1000
app.config["PROPAGATE_EXCEPTIONS"] = False

logging.basicConfig(level=logging.INFO)
_engines: dict[str, LocalTranscriber] = {}
_engine_lock = threading.Lock()
_kokoro: KokoroSpeaker | None = None
_kokoro_lock = threading.Lock()
_cloner: VoiceCloner | None = None
_cloner_lock = threading.Lock()

LANGUAGES = [
    ("auto", "Auto detect"),
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("hi", "Hindi"),
    ("ar", "Arabic"),
    ("zh", "Chinese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("ru", "Russian"),
    ("ur", "Urdu"),
]


def get_engine(model_size: str) -> LocalTranscriber:
    with _engine_lock:
        if model_size not in _engines:
            _engines[model_size] = LocalTranscriber(model_size=model_size)
        return _engines[model_size]




def get_kokoro() -> KokoroSpeaker:
    global _kokoro
    with _kokoro_lock:
        if _kokoro is None:
            _kokoro = KokoroSpeaker()
        return _kokoro


def get_cloner() -> VoiceCloner:
    global _cloner
    with _cloner_lock:
        if _cloner is None:
            _cloner = VoiceCloner()
        return _cloner






def api_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def _as_bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def parse_media_paths(raw: str) -> list[Path]:
    """Accept one path, quoted paths, or a JSON-like list of Windows paths."""
    text = (raw or "").strip()
    if not text:
        return []
    items: list[str] = re.findall(r'"([^"\r\n]+)"', text)
    items.extend(re.findall(r"'([^'\r\n]+)'", text))
    if not items:
        try:
            import json

            data = json.loads(text)
            if isinstance(data, list):
                items = [str(item) for item in data]
            elif isinstance(data, str):
                items = [data]
        except (json.JSONDecodeError, TypeError, ValueError):
            items = []
        if not items:
            for line in text.splitlines():
                cleaned = line.strip().strip("[],").strip().strip('"').strip("'")
                if cleaned:
                    items.append(cleaned)
    seen: set[str] = set()
    paths: list[Path] = []
    for item in items:
        cleaned = item.strip().strip('"').strip("'")
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        paths.append(Path(cleaned))
    return paths


def _transcript_payload(result, display_name: str, written: list[Path]) -> dict:
    return {
        "name": display_name,
        "language": str(result.language),
        "language_probability": float(result.language_probability),
        "duration": float(result.duration),
        "text": result.plain_text,
        "srt": result.to_srt(),
        "segments": [
            {
                "start": float(seg.start),
                "end": float(seg.end),
                "text": str(seg.text).strip(),
            }
            for seg in result.segments
        ],
        "files": [str(path) for path in written],
    }


def _save_upload(upload, suffix: str) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=suffix, dir=UPLOAD_DIR)
    os.close(fd)
    cleanup = Path(tmp_name)
    upload.save(cleanup)
    return cleanup


def _captions_for(media_path: Path, script: str = "", language: str | None = None) -> tuple[str, str | None]:
    try:
        text = " ".join((script or "").split())
        result = None
        if text:
            try:
                result = captions_from_script(text, media_path)
            except Exception:
                app.logger.exception("Script caption align failed; transcribing instead.")
                result = None
        if result is None:
            engine = get_engine("small")
            lang = None if not language or language in {"auto", ""} else language
            with _engine_lock:
                result = engine.transcribe(media_path, language=lang, vad_filter=False)
            result = rechunk_transcript(result)
        srt_path = save_srt(result, media_path)
        return result.to_srt(), str(srt_path)
    except Exception:
        app.logger.exception("Could not build SRT for %s", media_path)
        return "", None


@app.errorhandler(RequestEntityTooLarge)
def too_large(_e):
    return api_error(
        "That file is too large to upload in the browser. Paste the full local path instead.",
        413,
    )


@app.errorhandler(HTTPException)
def http_error(e: HTTPException):
    if request.path.startswith("/api/"):
        return api_error(e.description or e.name, e.code or 500)
    return e


@app.errorhandler(Exception)
def unhandled(e: Exception):
    app.logger.error("Unhandled error:\n%s", traceback.format_exc())
    if request.path.startswith("/api/"):
        return api_error(str(e) or "Internal server error", 500)
    return e


@app.get("/")
def index():
    return render_template(
        "index.html",
        models=MODEL_SIZES,
        languages=LANGUAGES,
        clone_languages=CLONE_LANGUAGES,
    )


@app.post("/api/transcribe")
def transcribe():
    cleanup: Path | None = None
    try:
        model_size = (request.form.get("model") or "small").strip()
        language = (request.form.get("language") or "auto").strip()
        local_path = (request.form.get("path") or "").strip()
        upload = request.files.get("file")

        source: Path | None = None
        display_name = "audio"

        if upload and upload.filename:
            suffix = Path(upload.filename).suffix.lower()
            if suffix not in SUPPORTED_MEDIA:
                return api_error(f"Unsupported file type '{suffix}'.")
            cleanup = _save_upload(upload, suffix)
            source = cleanup
            display_name = Path(upload.filename).name
        else:
            paths = parse_media_paths(local_path)
            if not paths:
                return api_error("Choose a video file or paste a local path (or a list of paths).")
            if len(paths) > 1:
                items = []
                for source_path in paths:
                    try:
                        if not source_path.exists():
                            raise FileNotFoundError(f"File not found: {source_path}")
                        engine = get_engine(model_size)
                        lang = None if language == "auto" else language
                        with _engine_lock:
                            result = engine.transcribe(source_path, language=lang, vad_filter=False)
                        result = rechunk_transcript(result)
                        written = write_outputs(result, Path(source_path.name), OUTPUT_DIR, ["txt", "srt", "json"])
                        items.append(_transcript_payload(result, source_path.name, written))
                    except Exception as exc:
                        app.logger.error("Batch item failed (%s):\n%s", source_path, traceback.format_exc())
                        items.append(
                            {
                                "name": source_path.name,
                                "path": str(source_path),
                                "error": str(exc) or "Transcription failed",
                            }
                        )
                ok = next((item for item in items if not item.get("error")), None)
                return jsonify({"batch": True, "count": len(items), "items": items, **(ok or items[0])})
            source = paths[0]
            if not source.exists():
                return api_error(f"File not found: {source}")
            display_name = source.name

        engine = get_engine(model_size)
        lang = None if language == "auto" else language
        with _engine_lock:
            result = engine.transcribe(source, language=lang, vad_filter=False)
        result = rechunk_transcript(result)
        written = write_outputs(result, Path(display_name), OUTPUT_DIR, ["txt", "srt", "json"])
        return jsonify(_transcript_payload(result, display_name, written))
    except Exception as exc:
        app.logger.error("Transcribe failed:\n%s", traceback.format_exc())
        return api_error(str(exc) or "Transcription failed", 500)
    finally:
        if cleanup is not None:
            try:
                cleanup.unlink(missing_ok=True)
            except OSError:
                pass


@app.get("/api/voices")
def voices():
    cloned = list_cloned_voices()
    return jsonify({"default": DEFAULT_VOICE, "voices": cloned + list_kokoro_voices()})


@app.get("/api/kokoro-samples/<voice>")
def kokoro_sample(voice):
    if voice not in {"am_michael", "am_adam"}:
        return api_error("No pack sample is available for this voice.", 404)
    return send_from_directory(ROOT / "models" / "kokoro" / "samples", voice + ".mp3", mimetype="audio/mpeg")


@app.post("/api/speak")
def speak():
    cleanup: Path | None = None
    try:
        payload = request.get_json(silent=True) or {}
        mode = str(payload.get("mode") or request.form.get("mode") or "preset").strip().lower()
        text = str(payload.get("text") or request.form.get("text") or "").strip()
        try:
            speed = float(
                payload.get("speed")
                if payload.get("speed") is not None
                else request.form.get("speed") or 1.0
            )
        except (TypeError, ValueError):
            return api_error("Speed must be a number.")

        remove_silence = _as_bool(
            payload.get("remove_silence")
            if payload.get("remove_silence") is not None
            else request.form.get("remove_silence"),
            False,
        )

        voice_id = str(payload.get("voice") or request.form.get("voice") or "").strip()
        saved = get_cloned_voice(voice_id) if voice_id else None

        if saved and mode != "clone":
            refs = [Path(path) for path in (saved.get("paths") or [saved["path"]])]
            result = get_cloner().speak(
                text,
                speaker_wav=refs if len(refs) > 1 else refs[0],
                language=str(saved.get("lang") or "en"),
                speed=speed,
                out_dir=OUTPUT_DIR,
                voice_id=str(saved["id"]),
                remove_silence=remove_silence,
            )
        elif mode == "clone":
            language = str(payload.get("language") or request.form.get("language") or "en").strip()
            local_path = str(payload.get("path") or request.form.get("path") or "").strip().strip('"')
            save_as = str(payload.get("save_as") or request.form.get("save_as") or "").strip()
            upload = request.files.get("file")
            source: Path | None = None
            if upload and upload.filename:
                suffix = Path(upload.filename).suffix.lower() or ".wav"
                cleanup = _save_upload(upload, suffix)
                source = cleanup
                if not save_as:
                    save_as = Path(upload.filename).stem
            elif local_path:
                source = Path(local_path)
                if not source.exists():
                    return api_error(f"File not found: {source}")
                if not save_as:
                    save_as = source.stem
            else:
                return api_error("Drop a voice sample you have the right to use, or paste a local path.")
            saved = save_cloned_voice(source, save_as or "Cloned voice", language)
            refs = [Path(path) for path in (saved.get("paths") or [saved["path"]])]
            result = get_cloner().speak(
                text,
                speaker_wav=refs if len(refs) > 1 else refs[0],
                language=language,
                speed=speed,
                out_dir=OUTPUT_DIR,
                voice_id=str(saved["id"]),
                remove_silence=remove_silence,
            )
        else:
            voice_id = voice_id or DEFAULT_VOICE
            if voice_id.startswith("kokoro:"):
                polish = _as_bool(payload.get("kokoro_polish") if payload.get("kokoro_polish") is not None else request.form.get("kokoro_polish"), True)
                result = get_kokoro().speak(text, voice_id=voice_id, speed=speed,
                    out_dir=OUTPUT_DIR, remove_silence=remove_silence, polish=polish)
            else:
                raise ValueError("Choose a Kokoro voice or a saved clone.")

        srt, srt_path = _captions_for(result.path, script=text)
        data = {
                "name": result.path.name,
                "path": str(result.path),
                "url": f"/outputs/{result.path.name}",
                "voice": result.voice,
                "engine": getattr(result, "engine", "xtts" if saved or mode == "clone" else "kokoro"),
                "polished": bool(getattr(result, "polished", False)),
                "raw_url": "/outputs/" + result.raw_path.relative_to(OUTPUT_DIR).as_posix() if getattr(result, "raw_path", None) else None,
                "lossless_path": str(result.path.with_suffix(".wav")) if result.path.with_suffix(".wav").is_file() else None,
                "duration": float(result.duration),
                "sample_rate": int(result.sample_rate),
                "speed": float(result.speed),
                "mode": mode,
                "original_duration": float(result.original_duration or result.duration),
                "silence_removed": float(result.silence_removed),
                "srt": srt,
                "srt_path": srt_path,
                "srt_url": f"/outputs/{Path(srt_path).name}" if srt_path else None,
        }
        try:
            data["text"] = text
            data = voice_library.record(data)
        except Exception:
            app.logger.exception("Could not save voice history")
        return jsonify(data)
    except ValueError as exc:
        return api_error(str(exc), 400)
    except Exception as exc:
        app.logger.error("Speak failed:\n%s", traceback.format_exc())
        return api_error(str(exc) or "Voice generation failed", 500)
    finally:
        if cleanup is not None:
            try:
                cleanup.unlink(missing_ok=True)
            except OSError:
                pass


@app.get("/api/voice-history")
def voice_history():
    records = voice_library.recent()
    return jsonify({"voices": records, "latest": records[0] if records else None})


@app.get("/api/enhancers")
def enhancers_status():
    return jsonify({"enhancers": enhancement.status()})


@app.post("/api/enhance")
def enhance_voice():
    cleanup = None
    try:
        payload = request.get_json(silent=True) or request.form
        raw = payload.get("providers") if request.is_json else (request.form.getlist("providers") if "providers" in request.form else None)
        if raw is None:
            raw = payload.get("provider") or "deepfilternet"
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return api_error("Choose a supported enhancer.")
        providers = [str(value) for value in raw]
        upload = request.files.get("file")
        if upload and upload.filename:
            suffix = Path(upload.filename).suffix.lower()
            if suffix not in SUPPORTED_MEDIA:
                return api_error("Unsupported audio or video type.")
            cleanup = _save_upload(upload, suffix)
            source = cleanup
        else:
            source = Path(str(payload.get("path") or "").strip().strip('"'))
        job = enhancement.start(source, providers, OUTPUT_DIR,
            strength=float(payload.get("strength", .75)),
            normalize=_as_bool(payload.get("normalize"), True), cleanup=cleanup is not None)
        cleanup = None  # worker owns the uploaded file until it has finished
        return jsonify({"job": job, "status_url": "/api/enhance/" + job}), 202
    except (ValueError, TypeError) as exc:
        return api_error(str(exc), 400)
    except Exception as exc:
        app.logger.exception("Enhancement failed to start")
        return api_error(str(exc), 500)
    finally:
        if cleanup is not None:
            cleanup.unlink(missing_ok=True)


@app.post("/api/enhance/<job>/cancel")
def cancel_enhancement(job):
    if not enhancement.cancel(job):
        return api_error("Enhancement job was not found.", 404)
    return jsonify({"message": "Cancellation requested"})


@app.get("/api/enhance/<job>")
def enhance_progress(job):
    result = enhancement.job_status(job)
    if result is None:
        return api_error("Enhancement job was not found. Results already saved remain in outputs.", 404)
    return jsonify(result)








def _output_mime(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".m4a":
        return "audio/mp4"
    if suffix == ".srt":
        return "application/x-subrip"
    if suffix == ".txt":
        return "text/plain; charset=utf-8"
    if suffix == ".mp4":
        return "video/mp4"
    return "application/octet-stream"


@app.post("/api/silence")
def silence_cut():
    cleanup: Path | None = None
    try:
        local_path = (request.form.get("path") or "").strip().strip('"')
        upload = request.files.get("file")
        try:
            max_pause = float(request.form.get("max_pause") or DEFAULT_MAX_PAUSE)
        except (TypeError, ValueError):
            return api_error("Pause length must be a number.")
        max_pause = clamp_max_pause(max_pause)

        source: Path | None = None
        display_name = "audio"
        if upload and upload.filename:
            suffix = Path(upload.filename).suffix.lower()
            if suffix not in SUPPORTED_MEDIA:
                return api_error(f"Unsupported file type '{suffix}'.")
            cleanup = _save_upload(upload, suffix)
            source = cleanup
            display_name = Path(upload.filename).name
        elif local_path:
            source = Path(local_path)
            if not source.exists():
                return api_error(f"File not found: {source}")
            display_name = source.name
        else:
            return api_error("Choose an audio or video file, or paste a local path.")

        result, stats = remove_silence_file(
            source,
            OUTPUT_DIR,
            max_pause=max_pause,
            name=f"{Path(display_name).stem}-silence",
        )
        script = str(request.form.get("text") or "").strip()
        srt, srt_path = _captions_for(result.path, script=script)
        return jsonify(
            {
                "name": result.path.name,
                "path": str(result.path),
                "url": f"/outputs/{result.path.name}",
                "duration": float(result.duration),
                "original_duration": float(stats.original_duration),
                "silence_removed": float(stats.removed),
                "pauses_shortened": int(stats.pauses_shortened),
                "sample_rate": int(result.sample_rate),
                "max_pause": float(max_pause),
                "srt": srt,
                "srt_path": srt_path,
                "srt_url": f"/outputs/{Path(srt_path).name}" if srt_path else None,
            }
        )
    except ValueError as exc:
        return api_error(str(exc), 400)
    except Exception as exc:
        app.logger.error("Silence removal failed:\n%s", traceback.format_exc())
        return api_error(str(exc) or "Silence removal failed", 500)
    finally:
        if cleanup is not None:
            try:
                cleanup.unlink(missing_ok=True)
            except OSError:
                pass


@app.get("/outputs/<path:name>")
def serve_output(name):
    return send_from_directory(OUTPUT_DIR, name, mimetype=_output_mime(name))


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    print("Open http://127.0.0.1:7860")
    app.run(host="127.0.0.1", port=7860, threaded=True, use_reloader=False)
