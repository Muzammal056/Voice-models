"""Kokoro voices integrated with the app's audio, captions and history workflow."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import importlib.util,json,math,os,shutil,subprocess,sys,tempfile,threading,uuid
from voice import SpeakResult,MAX_SCRIPT_CHARS,make_audio_stem,wav_duration,export_voiceover
ROOT=Path(__file__).resolve().parent
KOKORO_DEFAULT='kokoro:am_michael'
KOKORO_VOICES=(('am_michael','Michael — US male narrator'),('am_adam','Adam — US male'),)

IDS={voice for voice,_ in KOKORO_VOICES}

def configuration():
    try:config=json.loads((ROOT/'kokoro-runtime.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):config={}
    python=os.environ.get('KOKORO_PYTHON') or config.get('python')
    if not python:
        python=sys.executable if importlib.util.find_spec('kokoro') else str(Path(sys.base_prefix)/('python.exe' if os.name=='nt' else 'bin/python3'))
    config['python']=str(python)
    config.setdefault('cache_dir',str(Path.home()/'.cache/huggingface/hub'))
    return config

def list_kokoro_voices():
    cache=Path(configuration()['cache_dir'])/'models--hexgrad--Kokoro-82M'/'snapshots'
    snapshots=list(cache.glob('*')) if cache.exists() else []
    core=any((snapshot/'kokoro-v1_0.pth').is_file() for snapshot in snapshots)
    return [{'id':'kokoro:'+voice,'label':label,'lang':'English (US)','kind':'kokoro','downloaded':core and any((snapshot/'voices'/(voice+'.pt')).is_file() for snapshot in snapshots),'sample_url':'/api/kokoro-samples/'+voice if voice in ('am_michael','am_adam') else None} for voice,label in KOKORO_VOICES]

@dataclass
class KokoroResult(SpeakResult):
    raw_path:Path|None=None
    engine:str='kokoro'
    polished:bool=True

class KokoroSpeaker:
    def __init__(self):self._lock=threading.Lock()
    def speak(self,text,voice_id=KOKORO_DEFAULT,speed=1.0,out_dir=None,remove_silence=False,polish=True):
        script=str(text).strip();voice=voice_id.removeprefix('kokoro:')
        if voice not in IDS:raise ValueError('Choose a listed Kokoro voice.')
        if not script or len(script)>MAX_SCRIPT_CHARS:raise ValueError(f'Enter narration of 1–{MAX_SCRIPT_CHARS} characters.')
        speed=float(speed)
        if not math.isfinite(speed):raise ValueError('Speed must be a finite number.')
        speed=max(.6,min(1.5,speed));config=configuration();python=Path(config['python'])
        if not python.is_file():raise RuntimeError('Kokoro runtime was not found. Run Setup Kokoro.bat or set KOKORO_PYTHON.')
        dest=Path(out_dir) if out_dir else ROOT/'outputs';dest.mkdir(parents=True,exist_ok=True)
        token=uuid.uuid4().hex[:10];stem=make_audio_stem(script,'kokoro-'+voice)
        final=dest/(stem+'-'+token+'.wav');raw_dir=dest/'kokoro-originals';raw_dir.mkdir(exist_ok=True);raw=raw_dir/(stem+'-'+token+'.wav')
        log=dest/('kokoro-'+token+'.log')
        with self._lock:
            with tempfile.TemporaryDirectory(prefix='kokoro-',dir=dest) as folder:
                request=Path(folder)/'request.json';request.write_text(json.dumps({'text':script,'voice':voice,'speed':speed,'output':str(raw.resolve()),'cache_dir':config['cache_dir']},ensure_ascii=False),encoding='utf-8')
                env=os.environ.copy();env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8'
                with log.open('w',encoding='utf-8') as stream:
                    result=subprocess.run([str(python),str(ROOT/'kokoro_worker.py'),'--request',str(request)],env=env,stdout=stream,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if result.returncode:
                    lines=log.read_text(encoding='utf-8',errors='replace').strip().splitlines()
                    raise RuntimeError('Kokoro could not generate this voice. '+(lines[-1] if lines else 'Check '+str(log)))
                original_duration,rate=wav_duration(raw);working=Path(folder)/'working.wav';shutil.copy2(raw,working);removed=0.0
                if remove_silence:
                    from silence import apply_to_wav
                    try:removed=apply_to_wav(working).removed
                    except ValueError:pass
                if polish:
                    from enhancement import ffmpeg_path
                    command=[ffmpeg_path(),'-y','-v','error','-i',str(working),'-af','highpass=f=80,equalizer=f=3000:width_type=o:width=1.5:g=3,equalizer=f=6000:width_type=o:width=1.5:g=2,loudnorm=I=-16:TP=-1.5:LRA=11','-ar','44100','-c:a','pcm_s16le',str(final)]
                    with log.open('a',encoding='utf-8') as stream:subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                else:shutil.copy2(working,final)
                duration,rate=wav_duration(final);mp3=export_voiceover(final)
        return KokoroResult(path=mp3,voice=voice_id,duration=duration,sample_rate=rate,speed=speed,original_duration=original_duration,silence_removed=removed,raw_path=raw,polished=bool(polish))
