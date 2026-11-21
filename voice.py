"""Local text-to-speech using Piper neural voices."""

from __future__ import annotations

import re
import threading
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import av
from piper import PiperVoice, SynthesisConfig
from piper.download_voices import download_voice

VOICE_DIR_NAME = "piper"
DEFAULT_VOICE = "en_US-lessac-medium"
MAX_SCRIPT_CHARS = 20_000

VOICES: tuple[dict[str, str], ...] = (
    {"id": 'en_US-amy-medium', "label": 'Amy — US female', "lang": 'English (US)'},
    {"id": 'en_US-amy-low', "label": 'Amy low — US female', "lang": 'English (US)'},
    {"id": 'en_US-bryce-medium', "label": 'Bryce — US male', "lang": 'English (US)'},
    {"id": 'en_US-danny-low', "label": 'Danny low — US male', "lang": 'English (US)'},
    {"id": 'en_US-hfc_female-medium', "label": 'HFC — US female', "lang": 'English (US)'},
    {"id": 'en_US-hfc_male-medium', "label": 'HFC — US male', "lang": 'English (US)'},
    {"id": 'en_US-joe-medium', "label": 'Joe — US male', "lang": 'English (US)'},
    {"id": 'en_US-john-medium', "label": 'John — US male', "lang": 'English (US)'},
    {"id": 'en_US-kathleen-low', "label": 'Kathleen low — US female', "lang": 'English (US)'},
    {"id": 'en_US-kristin-medium', "label": 'Kristin — US female', "lang": 'English (US)'},
    {"id": 'en_US-kusal-medium', "label": 'Kusal — US male', "lang": 'English (US)'},
    {"id": 'en_US-lessac-high', "label": 'Lessac high — US male, higher quality', "lang": 'English (US)'},
    {"id": 'en_US-lessac-medium', "label": 'Lessac — US male narrator', "lang": 'English (US)'},
    {"id": 'en_US-lessac-low', "label": 'Lessac low — US male, smaller file', "lang": 'English (US)'},
    {"id": 'en_US-ljspeech-high', "label": 'LJ Speech high — US female', "lang": 'English (US)'},
    {"id": 'en_US-ljspeech-medium', "label": 'LJ Speech — US female', "lang": 'English (US)'},
    {"id": 'en_US-mike-medium', "label": 'Mike — US male', "lang": 'English (US)'},
    {"id": 'en_US-norman-medium', "label": 'Norman — US male', "lang": 'English (US)'},
    {"id": 'en_US-reza_ibrahim-medium', "label": 'Reza — US male', "lang": 'English (US)'},
    {"id": 'en_US-ryan-high', "label": 'Ryan high — US male', "lang": 'English (US)'},
    {"id": 'en_US-ryan-medium', "label": 'Ryan — US male', "lang": 'English (US)'},
    {"id": 'en_US-ryan-low', "label": 'Ryan low — US male', "lang": 'English (US)'},
    {"id": 'en_US-sam-medium', "label": 'Sam — US male', "lang": 'English (US)'},
    {"id": 'en_GB-alan-medium', "label": 'Alan — UK male', "lang": 'English (UK)'},
    {"id": 'en_GB-alan-low', "label": 'Alan low — UK male', "lang": 'English (UK)'},
    {"id": 'en_GB-alba-medium', "label": 'Alba — Scottish female', "lang": 'English (UK)'},
    {"id": 'en_GB-cori-high', "label": 'Cori high — UK female', "lang": 'English (UK)'},
    {"id": 'en_GB-cori-medium', "label": 'Cori — UK female', "lang": 'English (UK)'},
    {"id": 'en_GB-jenny_dioco-medium', "label": 'Jenny — UK female', "lang": 'English (UK)'},
    {"id": 'en_GB-northern_english_male-medium', "label": 'Northern English — UK male', "lang": 'English (UK)'},
    {"id": 'en_GB-southern_english_female-low', "label": 'Southern English low — UK female', "lang": 'English (UK)'},
    {"id": 'sq_AL-edon-medium', "label": 'Edon — Albanian', "lang": 'Albanian'},
    {"id": 'ar_JO-kareem-medium', "label": 'Kareem — Arabic male', "lang": 'Arabic'},
    {"id": 'ar_JO-kareem-low', "label": 'Kareem low — Arabic', "lang": 'Arabic'},
    {"id": 'hy_AM-gor-medium', "label": 'Gor — Armenian', "lang": 'Armenian'},
    {"id": 'eu_ES-antton-medium', "label": 'Antton — Basque', "lang": 'Basque'},
    {"id": 'eu_ES-maider-medium', "label": 'Maider — Basque', "lang": 'Basque'},
    {"id": 'bg_BG-dimitar-medium', "label": 'Dimitar — Bulgarian', "lang": 'Bulgarian'},
    {"id": 'ca_ES-upc_ona-medium', "label": 'UPC Ona — Catalan', "lang": 'Catalan'},
    {"id": 'ca_ES-upc_ona-x_low', "label": 'UPC Ona x-low — Catalan', "lang": 'Catalan'},
    {"id": 'ca_ES-upc_pau-x_low', "label": 'UPC Pau x-low — Catalan', "lang": 'Catalan'},
    {"id": 'zh_CN-chaowen-medium', "label": 'Chaowen — Chinese', "lang": 'Chinese'},
    {"id": 'zh_CN-huayan-medium', "label": 'Huayan — Chinese female', "lang": 'Chinese'},
    {"id": 'zh_CN-huayan-x_low', "label": 'Huayan x-low — Chinese', "lang": 'Chinese'},
    {"id": 'zh_CN-xiao_ya-medium', "label": 'Xiao Ya — Chinese', "lang": 'Chinese'},
    {"id": 'cs_CZ-jirka-medium', "label": 'Jirka — Czech', "lang": 'Czech'},
    {"id": 'cs_CZ-jirka-low', "label": 'Jirka low — Czech', "lang": 'Czech'},
    {"id": 'cs_CZ-kasandra-medium', "label": 'Kasandra — Czech', "lang": 'Czech'},
    {"id": 'da_DK-talesyntese-medium', "label": 'Talesyntese — Danish', "lang": 'Danish'},
    {"id": 'nl_NL-alex-medium', "label": 'Alex — Dutch Netherlands', "lang": 'Dutch'},
    {"id": 'nl_NL-mls_5809-low', "label": 'MLS 5809 low — Dutch Netherlands', "lang": 'Dutch'},
    {"id": 'nl_NL-mls_7432-low', "label": 'MLS 7432 low — Dutch Netherlands', "lang": 'Dutch'},
    {"id": 'nl_BE-nathalie-medium', "label": 'Nathalie — Dutch Belgium', "lang": 'Dutch'},
    {"id": 'nl_BE-nathalie-x_low', "label": 'Nathalie x-low — Dutch Belgium', "lang": 'Dutch'},
    {"id": 'nl_NL-pim-medium', "label": 'Pim — Dutch male', "lang": 'Dutch'},
    {"id": 'nl_BE-rdh-medium', "label": 'Rdh — Dutch Belgium', "lang": 'Dutch'},
    {"id": 'nl_BE-rdh-x_low', "label": 'Rdh x-low — Dutch Belgium', "lang": 'Dutch'},
    {"id": 'nl_NL-ronnie-medium', "label": 'Ronnie — Dutch Netherlands', "lang": 'Dutch'},
    {"id": 'fa_IR-amir-medium', "label": 'Amir — Farsi', "lang": 'Farsi'},
    {"id": 'fa_IR-ganji-medium', "label": 'Ganji — Farsi', "lang": 'Farsi'},
    {"id": 'fa_IR-ganji_adabi-medium', "label": 'Ganji Adabi — Farsi', "lang": 'Farsi'},
    {"id": 'fa_IR-gyro-medium', "label": 'Gyro — Farsi', "lang": 'Farsi'},
    {"id": 'fa_IR-reza_ibrahim-medium', "label": 'Reza Ibrahim — Farsi', "lang": 'Farsi'},
    {"id": 'fi_FI-harri-medium', "label": 'Harri — Finnish', "lang": 'Finnish'},
    {"id": 'fi_FI-harri-low', "label": 'Harri low — Finnish', "lang": 'Finnish'},
    {"id": 'fr_FR-gilles-low', "label": 'Gilles low — French', "lang": 'French'},
    {"id": 'fr_FR-mls_1840-low', "label": 'MLS 1840 low — French', "lang": 'French'},
    {"id": 'fr_FR-siwis-medium', "label": 'Siwis — French female', "lang": 'French'},
    {"id": 'fr_FR-siwis-low', "label": 'Siwis low — French', "lang": 'French'},
    {"id": 'fr_FR-tom-medium', "label": 'Tom — French male', "lang": 'French'},
    {"id": 'ka_GE-natia-medium', "label": 'Natia — Georgian', "lang": 'Georgian'},
    {"id": 'de_DE-eva_k-x_low', "label": 'Eva K x-low — German', "lang": 'German'},
    {"id": 'de_DE-karlsson-low', "label": 'Karlsson low — German', "lang": 'German'},
    {"id": 'de_DE-kerstin-low', "label": 'Kerstin low — German', "lang": 'German'},
    {"id": 'de_DE-pavoque-low', "label": 'Pavoque low — German', "lang": 'German'},
    {"id": 'de_DE-ramona-low', "label": 'Ramona low — German', "lang": 'German'},
    {"id": 'de_DE-thorsten-high', "label": 'Thorsten high — German male', "lang": 'German'},
    {"id": 'de_DE-thorsten-medium', "label": 'Thorsten — German male', "lang": 'German'},
    {"id": 'de_DE-thorsten-low', "label": 'Thorsten low — German', "lang": 'German'},
    {"id": 'el_GR-joy-medium', "label": 'Joy — Greek', "lang": 'Greek'},
    {"id": 'el_GR-rapunzelina-medium', "label": 'Rapunzelina — Greek', "lang": 'Greek'},
    {"id": 'el_GR-rapunzelina-low', "label": 'Rapunzelina low — Greek', "lang": 'Greek'},
    {"id": 'he_IL-saspeech-medium', "label": 'Saspeech — Hebrew', "lang": 'Hebrew'},
    {"id": 'hi_IN-pratham-medium', "label": 'Pratham — Hindi male', "lang": 'Hindi'},
    {"id": 'hi_IN-priyamvada-medium', "label": 'Priyamvada — Hindi female', "lang": 'Hindi'},
    {"id": 'hi_IN-rohan-medium', "label": 'Rohan — Hindi', "lang": 'Hindi'},
    {"id": 'hu_HU-anna-medium', "label": 'Anna — Hungarian', "lang": 'Hungarian'},
    {"id": 'hu_HU-berta-medium', "label": 'Berta — Hungarian', "lang": 'Hungarian'},
    {"id": 'hu_HU-imre-medium', "label": 'Imre — Hungarian', "lang": 'Hungarian'},
    {"id": 'is_IS-bui-medium', "label": 'Bui — Icelandic', "lang": 'Icelandic'},
    {"id": 'is_IS-salka-medium', "label": 'Salka — Icelandic', "lang": 'Icelandic'},
    {"id": 'is_IS-steinn-medium', "label": 'Steinn — Icelandic', "lang": 'Icelandic'},
    {"id": 'is_IS-ugla-medium', "label": 'Ugla — Icelandic', "lang": 'Icelandic'},
    {"id": 'id_ID-news_tts-medium', "label": 'News TTS — Indonesian', "lang": 'Indonesian'},
    {"id": 'it_IT-paola-medium', "label": 'Paola — Italian female', "lang": 'Italian'},
    {"id": 'it_IT-riccardo-x_low', "label": 'Riccardo x-low — Italian', "lang": 'Italian'},
    {"id": 'it_IT-serena-high', "label": 'Serena high — Italian female', "lang": 'Italian'},
    {"id": 'it_IT-serena-medium', "label": 'Serena — Italian', "lang": 'Italian'},
    {"id": 'kk_KZ-iseke-x_low', "label": 'Iseke x-low — Kazakh', "lang": 'Kazakh'},
    {"id": 'kk_KZ-raya-x_low', "label": 'Raya x-low — Kazakh', "lang": 'Kazakh'},
    {"id": 'ko_KR-kss-medium', "label": 'KSS — Korean', "lang": 'Korean'},
    {"id": 'lv_LV-aivars-medium', "label": 'Aivars — Latvian', "lang": 'Latvian'},
    {"id": 'lt_LT-reginute1-medium', "label": 'Reginute1 — Lithuanian', "lang": 'Lithuanian'},
    {"id": 'lb_LU-marylux-medium', "label": 'Marylux — Luxembourgish', "lang": 'Luxembourgish'},
    {"id": 'ml_IN-arjun-medium', "label": 'Arjun — Malayalam', "lang": 'Malayalam'},
    {"id": 'ml_IN-meera-medium', "label": 'Meera — Malayalam', "lang": 'Malayalam'},
    {"id": 'ne_NP-chitwan-medium', "label": 'Chitwan — Nepali', "lang": 'Nepali'},
    {"id": 'no_NO-talesyntese-medium', "label": 'Talesyntese — Norwegian', "lang": 'Norwegian'},
    {"id": 'pl_PL-bass-high', "label": 'Bass high — Polish', "lang": 'Polish'},
    {"id": 'pl_PL-darkman-medium', "label": 'Darkman — Polish', "lang": 'Polish'},
    {"id": 'pl_PL-gosia-medium', "label": 'Gosia — Polish female', "lang": 'Polish'},
    {"id": 'pl_PL-mc_speech-medium', "label": 'Mc Speech — Polish', "lang": 'Polish'},
    {"id": 'pl_PL-mls_6892-low', "label": 'MLS 6892 low — Polish', "lang": 'Polish'},
    {"id": 'pt_BR-cadu-medium', "label": 'Cadu — Brazilian Portuguese male', "lang": 'Portuguese'},
    {"id": 'pt_BR-edresson-low', "label": 'Edresson low — Portuguese Brazil', "lang": 'Portuguese'},
    {"id": 'pt_BR-faber-medium', "label": 'Faber — Brazilian Portuguese male', "lang": 'Portuguese'},
    {"id": 'pt_BR-jeff-medium', "label": 'Jeff — Portuguese Brazil', "lang": 'Portuguese'},
    {"id": 'pt_PT-tugão-medium', "label": 'Tugão — Portuguese Portugal', "lang": 'Portuguese'},
    {"id": 'ro_RO-mihai-medium', "label": 'Mihai — Romanian', "lang": 'Romanian'},
    {"id": 'ru_RU-denis-medium', "label": 'Denis — Russian', "lang": 'Russian'},
    {"id": 'ru_RU-dmitri-medium', "label": 'Dmitri — Russian male', "lang": 'Russian'},
    {"id": 'ru_RU-irina-medium', "label": 'Irina — Russian female', "lang": 'Russian'},
    {"id": 'ru_RU-ruslan-medium', "label": 'Ruslan — Russian', "lang": 'Russian'},
    {"id": 'sk_SK-lili-medium', "label": 'Lili — Slovak', "lang": 'Slovak'},
    {"id": 'sl_SI-artur-medium', "label": 'Artur — Slovenian', "lang": 'Slovenian'},
    {"id": 'es_MX-ald-medium', "label": 'Ald — Spanish Mexico', "lang": 'Spanish'},
    {"id": 'es_MX-ald-x_low', "label": 'Ald x-low — Spanish Mexico', "lang": 'Spanish'},
    {"id": 'es_ES-carlfm-x_low', "label": 'Carlfm x-low — Spanish Spain', "lang": 'Spanish'},
    {"id": 'es_MX-claude-high', "label": 'Claude high — Mexican Spanish male', "lang": 'Spanish'},
    {"id": 'es_AR-daniela-high', "label": 'Daniela high — Argentine Spanish female', "lang": 'Spanish'},
    {"id": 'es_ES-davefx-medium', "label": 'DaveFX — Spanish male', "lang": 'Spanish'},
    {"id": 'es_ES-mls_10246-low', "label": 'MLS 10246 low — Spanish Spain', "lang": 'Spanish'},
    {"id": 'es_ES-mls_9972-low', "label": 'MLS 9972 low — Spanish Spain', "lang": 'Spanish'},
    {"id": 'sw_CD-lanfrica-medium', "label": 'Lanfrica — Swahili', "lang": 'Swahili'},
    {"id": 'sv_SE-alma-medium', "label": 'Alma — Swedish', "lang": 'Swedish'},
    {"id": 'sv_SE-lisa-medium', "label": 'Lisa — Swedish female', "lang": 'Swedish'},
    {"id": 'sv_SE-nst-medium', "label": 'Nst — Swedish', "lang": 'Swedish'},
    {"id": 'te_IN-maya-medium', "label": 'Maya — Telugu', "lang": 'Telugu'},
    {"id": 'te_IN-padmavathi-medium', "label": 'Padmavathi — Telugu', "lang": 'Telugu'},
    {"id": 'te_IN-venkatesh-medium', "label": 'Venkatesh — Telugu', "lang": 'Telugu'},
    {"id": 'th_TH-tsync2-medium', "label": 'Tsync2 — Thai', "lang": 'Thai'},
    {"id": 'tr_TR-dfki-medium', "label": 'DFKI — Turkish', "lang": 'Turkish'},
    {"id": 'uk_UA-lada-x_low', "label": 'Lada x-low — Ukrainian', "lang": 'Ukrainian'},
    {"id": 'uk_UA-mykyta-high', "label": 'Mykyta high — Ukrainian', "lang": 'Ukrainian'},
    {"id": 'uk_UA-oleksa-high', "label": 'Oleksa high — Ukrainian', "lang": 'Ukrainian'},
    {"id": 'uk_UA-tetiana-high', "label": 'Tetiana high — Ukrainian', "lang": 'Ukrainian'},
    {"id": 'ur_PK-aegis_female-medium', "label": 'Aegis Female — Urdu', "lang": 'Urdu'},
    {"id": 'ur_PK-fasih-medium', "label": 'Fasih — Urdu', "lang": 'Urdu'},
    {"id": 'vi_VN-25hours_single-low', "label": '25hours Single low — Vietnamese', "lang": 'Vietnamese'},
    {"id": 'vi_VN-vais1000-medium', "label": 'Vais1000 — Vietnamese', "lang": 'Vietnamese'},
    {"id": 'cy_GB-gwryw_gogleddol-medium', "label": 'Gwryw Gogleddol — Welsh', "lang": 'Welsh'},
)

_VOICE_IDS = {item["id"] for item in VOICES}
_UNSAFE = re.compile(r"[^\w\s-]", re.UNICODE)


@dataclass
class SpeakResult:
    path: Path
    voice: str
    duration: float
    sample_rate: int
    speed: float
    original_duration: float | None = None
    silence_removed: float = 0.0


def voice_dir(root: Path | None = None) -> Path:
    base = root if root else Path(__file__).resolve().parent
    return base / "models" / VOICE_DIR_NAME


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


def list_voices(download_root: Path | None = None) -> list[dict[str, object]]:
    folder = voice_dir(download_root)
    listed: list[dict[str, object]] = []
    for item in VOICES:
        model = folder / f"{item['id']}.onnx"
        listed.append(
            {
                **item,
                "downloaded": model.exists() and model.stat().st_size > 0,
            }
        )
    return listed


class LocalSpeaker:
    def __init__(self, download_root: Path | None = None) -> None:
        self.download_dir = voice_dir(download_root)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._loaded: dict[str, PiperVoice] = {}
        self._lock = threading.Lock()

    def _model_path(self, voice_id: str) -> Path:
        return self.download_dir / f"{voice_id}.onnx"

    def is_downloaded(self, voice_id: str) -> bool:
        model = self._model_path(voice_id)
        config = self.download_dir / f"{voice_id}.onnx.json"
        return model.exists() and config.exists() and model.stat().st_size > 0

    def ensure_voice(self, voice_id: str) -> Path:
        if voice_id not in _VOICE_IDS:
            raise ValueError(f"Unknown voice '{voice_id}'.")
        model = self._model_path(voice_id)
        if not self.is_downloaded(voice_id):
            download_voice(voice_id, self.download_dir)
        if not model.exists() or model.stat().st_size == 0:
            raise RuntimeError(f"Voice download failed: {voice_id}")
        return model

    def speak(
        self,
        text: str,
        voice_id: str = DEFAULT_VOICE,
        speed: float = 1.0,
        out_dir: Path | None = None,
        name: str | None = None,
        remove_silence: bool = True,
    ) -> SpeakResult:
        script = " ".join(text.split())
        if not script:
            raise ValueError("Enter some script text to speak.")
        if len(script) > MAX_SCRIPT_CHARS:
            raise ValueError(f"Script is too long (max {MAX_SCRIPT_CHARS} characters).")
        if voice_id not in _VOICE_IDS:
            raise ValueError(f"Unknown voice '{voice_id}'.")

        speed = min(1.5, max(0.6, float(speed)))
        dest_dir = Path(out_dir) if out_dir else Path(__file__).resolve().parent / "outputs"
        dest_dir.mkdir(parents=True, exist_ok=True)
        stem = name or make_audio_stem(script, voice_id)
        dest = unique_path(dest_dir / f"{stem}.wav")

        with self._lock:
            if voice_id not in self._loaded:
                model = self.ensure_voice(voice_id)
                self._loaded[voice_id] = PiperVoice.load(str(model))
            voice = self._loaded[voice_id]
            syn_config = SynthesisConfig(
                length_scale=1.0 / speed,
                volume=1.0,
                normalize_audio=True,
            )
            with wave.open(str(dest), "wb") as wav_file:
                voice.synthesize_wav(script, wav_file, syn_config=syn_config)

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
