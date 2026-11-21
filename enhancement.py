"""Run neural speech enhancers outside the app's TTS environment."""
from __future__ import annotations
import json,math,os,shutil,subprocess,tempfile,threading,time,uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'.enhancers-runtime'/'python.exe'
MODEL_ROOT=ROOT/'models'/'enhancers'
PROVIDERS={
 'deepfilternet':{'label':'DeepFilterNet 3','description':'Fast noise and hiss reduction'},
 'resemble':{'label':'Resemble Enhance','description':'Restore muffled or distorted speech; slower on CPU'},
 'clearvoice':{'label':'ClearerVoice — enhancement','description':'MossFormer2 full-band speech cleanup'},
 'clearvoice_sr':{'label':'ClearerVoice — super-resolution','description':'Extend speech bandwidth to 48 kHz'},
}
_jobs={};_cancels={};_jobs_lock=threading.Lock();_queue=ThreadPoolExecutor(max_workers=1,thread_name_prefix='voice-enhance')

def ffmpeg_path():
    binary=shutil.which('ffmpeg')
    if not binary:
        import imageio_ffmpeg
        binary=imageio_ffmpeg.get_ffmpeg_exe()
    return binary

def status():
    try:ready=json.loads((MODEL_ROOT/'status.json').read_text())
    except (OSError,ValueError):ready={}
    for key in PROVIDERS:
        try:ready[key]=json.loads((MODEL_ROOT/(key+'-status.json')).read_text())
        except (OSError,ValueError):pass
    return [{'id':key,**value,'runtime_installed':(RUNTIME.parent/'ready.json').exists(),'state':ready.get(key,{}).get('state','not_prepared'),'detail':ready.get(key,{}).get('detail','First use downloads this model; CPU processing can take several minutes.')} for key,value in PROVIDERS.items()]

def _update(job,**values):
    with _jobs_lock:_jobs[job].update(values)

def job_status(job):
    with _jobs_lock:
        data=_jobs.get(job)
        return json.loads(json.dumps(data)) if data else None

class Cancelled(Exception):pass

def cancel(job):
    with _jobs_lock:
        if job not in _cancels:return False
        _cancels[job].set();return True

def _run(command,log,cancel_event=None):
    with log.open('a',encoding='utf-8') as stream:
        if cancel_event and cancel_event.is_set():raise Cancelled()
        environment=os.environ.copy();environment['PYTHONUTF8']='1';environment['PYTHONIOENCODING']='utf-8'
        process=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT,env=environment,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        while True:
            try:code=process.wait(timeout=.4);break
            except subprocess.TimeoutExpired:
                if cancel_event and cancel_event.is_set():
                    process.terminate();process.wait();raise Cancelled()
    if code:
        lines=log.read_text(encoding='utf-8',errors='replace').strip().splitlines()
        detail=lines[-1] if lines else 'Worker exited with code '+str(code)
        raise RuntimeError('Enhancement failed. '+detail)

def start(source:Path,providers:list[str],out_dir:Path,*,strength:float=.75,normalize:bool=True,cleanup:bool=False):
    source=Path(source).resolve()
    if not source.is_file():raise ValueError('Choose an existing audio or video file.')
    if not providers or len(providers)>4 or len(set(providers))!=len(providers) or any(p not in PROVIDERS for p in providers):raise ValueError('Choose a supported enhancer, or compare the three enhancers.')
    strength=float(strength)
    if not math.isfinite(strength) or not .05<=strength<=1:raise ValueError('Enhancement strength must be between 5% and 100%.')
    if not RUNTIME.exists() or not(RUNTIME.parent/'ready.json').exists():raise RuntimeError('Enhancement runtime is not installed. Run Setup Voice Enhancers.bat in the app folder.')
    out_dir=Path(out_dir);out_dir.mkdir(parents=True,exist_ok=True)
    job=uuid.uuid4().hex
    with _jobs_lock:
        # Keep active jobs and the latest 100 completed jobs.
        done=[key for key,value in _jobs.items() if value['state'] in ('done','error','cancelled')]
        for key in done[:-100]:_jobs.pop(key,None);_cancels.pop(key,None)
        _cancels[job]=threading.Event()
        _jobs[job]={'id':job,'state':'queued','message':'Waiting for the enhancement worker','results':[],'errors':[],'original_path':str(source),'created':time.time()}
    _queue.submit(_process,job,source,providers,out_dir,strength,normalize,cleanup)
    return job

def _process(job,source,providers,out_dir,strength,normalize,cleanup):
    import wave
    cancel_event=_cancels[job]
    prefix=source.stem[:55] if not cleanup else 'uploaded-voice'
    work=out_dir/('.enhance-'+job)
    results=[];errors=[]
    try:
        work.mkdir()
        original=out_dir/(prefix+'-original-'+job[:8]+'.wav')
        log=out_dir/('enhance-'+job[:8]+'.log')
        _update(job,state='running',message='Preparing the original audio')
        _run([ffmpeg_path(),'-y','-v','error','-i',str(source),'-vn','-ac','1','-ar','48000','-c:a','pcm_s16le',str(original)],log,cancel_event)
        _update(job,original_path=str(original),original_url='/outputs/'+quote(original.name,safe=''))
        for provider in providers:
            label=PROVIDERS[provider]['label'];_update(job,message='Processing with '+label+' — model download may run on first use')
            try:
                raw=work/(provider+'.wav')
                _run([str(RUNTIME),str(ROOT/'enhance_worker.py'),'--provider',provider,'--input',str(original),'--output',str(raw),'--model-root',str(MODEL_ROOT)],log,cancel_event)
                # Align sample rate/length before blending; do not cut pauses.
                matched=work/(provider+'-48k.wav')
                _run([ffmpeg_path(),'-y','-v','error','-i',str(raw),'-ac','1','-ar','48000','-c:a','pcm_s16le',str(matched)],log,cancel_event)
                with wave.open(str(original),'rb') as wav:duration=wav.getnframes()/wav.getframerate()
                output=out_dir/(prefix+'-'+provider+'-'+job[:8]+'.wav')
                chain=f'[0:a]volume={1-strength}[dry];[1:a]apad,atrim=duration={duration},volume={strength}[wet];[dry][wet]amix=inputs=2:normalize=0'
                if normalize:chain+=',loudnorm=I=-16:TP=-1.5:LRA=11'
                _run([ffmpeg_path(),'-y','-v','error','-i',str(original),'-i',str(matched),'-filter_complex',chain,'-t',str(duration),'-ar','48000','-c:a','pcm_s24le',str(output)],log,cancel_event)
                mp3=output.with_suffix('.mp3')
                _run([ffmpeg_path(),'-y','-v','error','-i',str(output),'-c:a','libmp3lame','-b:a','192k',str(mp3)],log,cancel_event)
                results.append({'provider':provider,'label':label,'path':str(mp3),'name':mp3.name,'url':'/outputs/'+quote(mp3.name,safe=''),'wav_url':'/outputs/'+quote(output.name,safe=''),'wav_path':str(output),'duration':duration,'sample_rate':48000,'strength':strength})
            except Cancelled:raise
            except Exception as exc:errors.append({'provider':provider,'error':str(exc)})
            _update(job,results=list(results),errors=list(errors))
        _update(job,state='done' if results else 'error',message='Enhancement complete. Compare with the original.' if results else 'No enhancer completed; see the model error below.',results=results,errors=errors,log_url='/outputs/'+quote(log.name,safe=''))
    except Cancelled:_update(job,state='cancelled',message='Enhancement cancelled. Original audio and completed results are retained.')
    except Exception as exc:_update(job,state='error',message=str(exc),error=str(exc))
    finally:
        if work.resolve().parent == out_dir.resolve() and work.name == '.enhance-'+job:
            shutil.rmtree(work,ignore_errors=True)
        if cleanup:source.unlink(missing_ok=True)
