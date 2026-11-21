"""Repair Kokoro using an existing installation or a separate project environment."""
from pathlib import Path
import importlib.util,json,os,subprocess,sys
ROOT=Path(__file__).resolve().parent
PROBE='import kokoro, soundfile, espeakng_loader; from phonemizer.backend.espeak.wrapper import EspeakWrapper; print(kokoro.__version__)'
def works(python):
    if not Path(python).is_file():return False
    return subprocess.run([str(python),'-c',PROBE],capture_output=True).returncode==0

def main():
    config={}
    try:config=json.loads((ROOT/'kokoro-runtime.json').read_text())
    except (OSError,ValueError):pass
    candidates=[os.environ.get('KOKORO_PYTHON'),config.get('python'),sys.executable,str(Path(sys.base_prefix)/('python.exe' if os.name=='nt' else 'bin/python3'))]
    for python in candidates:
        if python and works(python):break
    else:
        folder=ROOT/'.kokoro-runtime';python=folder/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        if not python.exists():subprocess.run([sys.executable,'-m','venv',str(folder)],check=True)
        subprocess.run([str(python),'-m','pip','install','torch==2.5.1','--index-url','https://download.pytorch.org/whl/cpu'],check=True)
        subprocess.run([str(python),'-m','pip','install','kokoro==0.9.4','soundfile','espeakng-loader'],check=True)
        if not works(python):raise RuntimeError('Kokoro imports failed. Check the installation log.')
    config['python']=str(python);config.setdefault('cache_dir',str(Path.home()/'.cache/huggingface/hub'))
    (ROOT/'kokoro-runtime.json').write_text(json.dumps(config,indent=2))
    print('Kokoro is ready. Select a Kokoro voice in Voice Studio. The core model downloads only if it is not cached.')
if __name__=='__main__':main()
