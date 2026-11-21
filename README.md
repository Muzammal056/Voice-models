# Local video → transcript

Uses [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) on this machine. That repo is the inference library (CTranslate2 Whisper). This folder is a thin wrapper so you can drop in a video and get `.txt` / `.srt`.

PyAV (bundled with faster-whisper) decodes audio from video, so you do **not** need a system FFmpeg install. This PC has no NVIDIA GPU, so the default is CPU + `int8`.

## Setup (once)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Transcribe

```powershell
.\.venv\Scripts\Activate.ps1
python transcribe.py "C:\path\to\video.mp4"
```

Flags:

- `--model small` (default). Use `base` for speed, `medium` for more accuracy.
- `--language en` to skip auto-detect.
- `--formats txt srt vtt json`
- `--out outputs`

The first run downloads the Whisper weights into `models/`. After that it works offline.

## Voice enhancement

The Voice tab now offers DeepFilterNet 3, Resemble Enhance, ClearerVoice enhancement, and ClearerVoice bandwidth extension. You can enhance generated or existing audio, compare the three enhancers, and choose a result for the video. Originals and lossless outputs are kept. See **Voice Enhancers - Help.txt** in this folder.

These optional models use a separate Windows runtime installed by **Setup Voice Enhancers.bat**. The existing app environment is unchanged. Large pretrained checkpoints download on first use and are cached in `models/enhancers`. Processing runs locally in a background worker.

## Voice Studio interface

Voice generation and enhancement now have separate workspaces. The voice library restores recent original narration after a reload. Enhance accepts the last generated voice, a saved voiceover, or a new file with any checked combination of enhancers. Results can be selected for the video. Story/Qwen rewriting was removed; stock-footage planning uses keywords. See `Voice Enhancers - Help.txt`.

Regression checks: `.venv\Scripts\python.exe -m unittest discover -s tests -v`. The browser workflow was also verified with a real new-file upload through DeepFilterNet and ClearerVoice, including restoration of the selected result after refresh.


## Kokoro voices

Open Voice Studio using `Start App.bat`, choose the Voice workspace and Preset voice, then select a voice under **Kokoro · English (US)**. The pack includes eight male and four female voice choices. Michael and Adam have playable samples from the supplied pack. Those two voices were tested with actual local synthesis.

**Pack clarity finish** applies the pack's high-pass filter, presence EQ and -16 LUFS loudness normalization. Turn it off to keep the native sound. Kokoro generates at 24 kHz; the finish exports at 44.1 kHz, which does not add new recorded detail. Both the MP3 and lossless WAV are retained; **Raw WAV** downloads the unprocessed synthesis. Generated voices enter the same recent-voice library and enhancement workflow as the existing models.

The existing Kokoro installation on this PC is used in a separate CPU process. `kokoro-runtime.json` records the Python interpreter and cache directory; `KOKORO_PYTHON` can override the interpreter. If moved to another PC, run `Setup Kokoro.bat`. It reuses a working installation or creates `.kokoro-runtime` without changing the main app's Torch installation. The core model and any uncached voice weights require internet on first use; cached voices run locally afterward. A newly selected voice may take longer on its first generation.
