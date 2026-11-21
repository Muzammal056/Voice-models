"""Install inference dependencies into a project-local portable Python runtime."""
from pathlib import Path
import argparse,ast,io,json,os,subprocess,sys,urllib.request,zipfile
ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'.enhancers-runtime';PYTHON=RUNTIME/'python.exe'

def run(*args):
    subprocess.run([str(PYTHON),'-m','pip',*args],check=True)

def patch_resemble():
    package=RUNTIME/'Lib/site-packages/resemble_enhance'
    for part,klass in [('enhancer','Enhancer'),('denoiser','Denoiser')]:
        file=package/part/'inference.py';text=file.read_text();text=text.replace(f'from .train import {klass}, HParams',f'from .{part} import {klass}\nfrom .hparams import HParams')
        if part=='enhancer':text=text.replace('    if run_dir is None:\n        run_dir = download()','    run_dir = download(run_dir)') if 'def download(run_dir' in (package/part/'download.py').read_text() else text
        file.write_text(text)
    # Inference never runs training visualizations. Remove their DeepSpeed
    # imports, not the denoiser, generative model, or pretrained parameters.
    file=package/'enhancer/enhancer.py';tree=ast.parse(file.read_text())
    tree.body=[node for node in tree.body if not(isinstance(node,ast.ImportFrom) and node.module in ('utils.distributed','utils.train_loop'))]
    for node in ast.walk(tree):
        if isinstance(node,ast.FunctionDef) and node.name=='_visualize':
            node.decorator_list=[];node.body=[ast.Expr(value=ast.Constant(value='Training visualization is disabled in the inference-only Windows runtime.')),ast.Return(value=ast.Constant(value=None))]
    file.write_text(ast.unparse(ast.fix_missing_locations(tree))+'\n')
    base=package/'hparams.py';text=base.read_text()
    text=text.replace('OmegaConf.load(path)', 'OmegaConf.create(path.read_text(encoding="utf-8").replace("!!python/object/apply:pathlib.PosixPath", "!!python/object/apply:pathlib.WindowsPath"))')
    base.write_text(text)
    (package/'WINDOWS_INFERENCE_PATCH.txt').write_text('Training imports bypassed in enhancer/inference.py and denoiser/inference.py. Training-only visualization removed from enhancer.py to avoid DeepSpeed on Windows. Neural model computations and pretrained parameters are unchanged. Source: https://github.com/resemble-ai/resemble-enhance ; PyPI 0.0.1. This runtime is for inference, not training.\n')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--skip-torch',action='store_true');args=ap.parse_args()
    RUNTIME.mkdir(exist_ok=True)
    if not PYTHON.exists():
        print('Downloading project-local Python 3.11 for Windows model compatibility...',flush=True)
        data=urllib.request.urlopen('https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip',timeout=120).read()
        with zipfile.ZipFile(io.BytesIO(data)) as z:z.extractall(RUNTIME)
        f=RUNTIME/'python311._pth';f.write_text(f.read_text().replace('#import site','import site'))
    if not(RUNTIME/'Lib/site-packages/pip').exists():
        bootstrap=RUNTIME/'get-pip.py';bootstrap.write_bytes(urllib.request.urlopen('https://bootstrap.pypa.io/get-pip.py',timeout=120).read());subprocess.run([str(PYTHON),str(bootstrap)],check=True)
    constraints=ROOT/'enhancer-constraints.txt';constraints.write_text('numpy==1.26.4\npackaging==23.2\ntorch==2.5.1\ntorchaudio==2.5.1\ntorchvision==0.20.1\n')
    if not args.skip_torch:run('install','-c',str(constraints),'torch==2.5.1','torchaudio==2.5.1','torchvision==0.20.1','--index-url','https://download.pytorch.org/whl/cpu','--timeout','120')
    run('install','-c',str(constraints),'clearvoice==0.1.2','deepfilternet==0.5.6','omegaconf==2.3.0','rich==13.9.4','resampy==0.4.3','matplotlib==3.9.4','pandas==2.2.3','tabulate==0.9.0','--timeout','120')
    run('install','--no-deps','resemble-enhance==0.0.1','--timeout','120')
    patch_resemble()
    subprocess.run([str(PYTHON),'-c','import df.enhance; from clearvoice import ClearVoice; from resemble_enhance.enhancer.inference import enhance; print("Inference imports verified")'],check=True)
    (RUNTIME/'ready.json').write_text(json.dumps({'python':'3.11','torch':'2.5.1','runtime':'ready'}))
    print('Enhancement libraries installed. Pretrained models download on first use. Restart the app to load its new controls.',flush=True)
if __name__=='__main__':main()
