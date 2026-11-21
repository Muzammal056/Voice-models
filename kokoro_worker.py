"""Kokoro inference worker. Runs in its installed runtime, outside Flask's TTS environment."""
from pathlib import Path
import argparse,json,os,sys

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True);args=parser.parse_args()
    request=json.loads(args.request.read_text(encoding='utf-8'))
    os.environ['CUDA_VISIBLE_DEVICES']='';os.environ.setdefault('OMP_NUM_THREADS','4');os.environ.setdefault('MKL_NUM_THREADS','4')
    cache=request.get('cache_dir')
    if cache:
        os.environ['HF_HOME']=str(Path(cache).parent);os.environ['HF_HUB_CACHE']=cache;os.environ['HUGGINGFACE_HUB_CACHE']=cache
    import numpy as np,soundfile as sf,torch
    torch.set_num_threads(min(4,max(1,(os.cpu_count() or 4)//2)))
    # Use the bundled phonemizer library already installed with this runtime.
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper
    EspeakWrapper.set_library(str(espeakng_loader.get_library_path()))
    os.environ['ESPEAK_DATA_PATH']=str(espeakng_loader.get_data_path())
    from kokoro import KPipeline
    voice=request['voice'];pipeline=KPipeline(lang_code=voice[0],repo_id='hexgrad/Kokoro-82M',device='cpu')
    pieces=[];pause=np.zeros(3600,dtype=np.float32)
    for _,_,audio in pipeline(request['text'],voice=voice,speed=request['speed'],split_pattern=r'\n+'):
        if audio is None:continue
        data=audio.detach().cpu().numpy() if hasattr(audio,'detach') else np.asarray(audio,dtype=np.float32)
        data=np.asarray(data,dtype=np.float32).reshape(-1)
        if not data.size:continue
        if pieces:pieces.append(pause)
        pieces.append(data)
    if not pieces:raise RuntimeError('Kokoro returned no speech. Check the text and voice language.')
    output=np.concatenate(pieces)
    if not np.isfinite(output).all():raise RuntimeError('Kokoro returned invalid audio samples.')
    sf.write(request['output'],np.clip(output,-1,1),24000,subtype='PCM_16')
    print(json.dumps({'voice':voice,'sample_rate':24000,'duration':len(output)/24000}),flush=True)
if __name__=='__main__':main()
