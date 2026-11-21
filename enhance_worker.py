"""Inference-only subprocess: no packages are imported into the Flask app."""
from pathlib import Path
import argparse,json,os,sys,time,traceback

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--provider',required=True,choices=['deepfilternet','resemble','clearvoice','clearvoice_sr']);ap.add_argument('--input',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--model-root',type=Path,required=True)
    a=ap.parse_args();a.input=a.input.resolve();a.output=a.output.resolve();a.model_root=a.model_root.resolve();a.model_root.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    os.environ['HF_HOME']=str(a.model_root/'huggingface');os.environ['XDG_CACHE_HOME']=str(a.model_root/'cache');os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING']='1';os.environ['CUDA_VISIBLE_DEVICES']='';os.environ['MPLCONFIGDIR']=str(a.model_root/'cache/matplotlib');os.environ['NUMBA_CACHE_DIR']=str(a.model_root/'cache/numba')
    import numpy as np,soundfile as sf,torch
    torch.set_num_threads(max(1,min(4,(os.cpu_count() or 4)//2)))
    torch.manual_seed(0);audio,rate=sf.read(a.input,dtype='float32');audio=audio.mean(axis=1) if audio.ndim>1 else audio
    if not len(audio) or not np.isfinite(audio).all():raise ValueError('Input audio is empty or contains invalid samples.')
    started=time.time()
    with torch.inference_mode():
        if a.provider=='deepfilternet':
            import importlib
            DF=importlib.import_module("df.enhance")
            from enhancer_models import ensure
            model_dir=ensure('deepfilternet',a.model_root)
            model,state,*_=DF.init_df(str(model_dir),log_level='WARNING',log_file=None)
            if rate!=state.sr():
                import torchaudio.functional as AF
                audio=AF.resample(torch.from_numpy(audio),rate,state.sr()).numpy();rate=state.sr()
            output=DF.enhance(model,state,torch.from_numpy(audio).unsqueeze(0),pad=True).squeeze(0).cpu().numpy()
        elif a.provider=='resemble':
            from enhancer_models import ensure
            ensure(a.provider,a.model_root)
            from resemble_enhance.enhancer.inference import enhance
            output,rate=enhance(torch.from_numpy(audio),rate,'cpu',nfe=16,solver='midpoint',lambd=.5,tau=.5,run_dir=a.model_root/'resemble')
            output=output.detach().cpu().numpy()
        else:
            from enhancer_models import ensure
            ensure(a.provider,a.model_root)
            from clearvoice import ClearVoice
            task='speech_super_resolution' if a.provider=='clearvoice_sr' else 'speech_enhancement'
            name='MossFormer2_SR_48K' if a.provider=='clearvoice_sr' else 'MossFormer2_SE_48K'
            # ClearVoice uses a relative checkpoints directory; keep it local.
            home=a.model_root/'clearvoice';home.mkdir(exist_ok=True);os.chdir(home)
            model=ClearVoice(task=task,model_names=[name])
            output=model(input_path=str(a.input.resolve()),online_write=False)
            model.write(output,output_path=str(a.output.resolve()))
            output,rate=sf.read(a.output,dtype='float32')
    output=np.asarray(output).squeeze()
    if output.ndim!=1 or not output.size or not np.isfinite(output).all():raise RuntimeError('The model produced invalid audio.')
    sf.write(a.output,np.clip(output,-1,1),rate,subtype='PCM_24')
    (a.model_root/(a.provider+'-status.json')).write_text(json.dumps({'state':'ready','detail':'Pretrained model loaded and produced valid audio on this computer.'}))
    print(json.dumps({'provider':a.provider,'sample_rate':rate,'duration':len(output)/rate,'seconds':time.time()-started}),flush=True)
if __name__=='__main__':
    try:main()
    except Exception:traceback.print_exc();sys.exit(1)
