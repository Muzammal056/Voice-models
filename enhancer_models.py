"""Download verified, public pretrained checkpoints from the original authors."""
from pathlib import Path,PurePosixPath
import concurrent.futures,hashlib,json,time,urllib.request,re,contextlib,msvcrt
REPOS={
 'resemble':('ResembleAI/resemble-enhance','enhancer_stage2/','resemble'),
 'clearvoice':('alibabasglab/MossFormer2_SE_48K','','clearvoice/checkpoints/MossFormer2_SE_48K'),
 'clearvoice_sr':('alibabasglab/MossFormer2_SR_48K','','clearvoice/checkpoints/MossFormer2_SR_48K'),
}
def _ensure(provider,root):
 repo,prefix,folder=REPOS[provider];root=Path(root);dest=root/folder;dest.mkdir(parents=True,exist_ok=True)
 request=urllib.request.Request('https://huggingface.co/api/models/'+repo+'?blobs=true')
 data=json.load(urllib.request.urlopen(request,timeout=60))
 for item in data['siblings']:
  name=item['rfilename']
  if prefix and not name.startswith(prefix):continue
  relative=name[len(prefix):] if prefix else name
  if not relative or '..' in PurePosixPath(relative).parts or relative.startswith('/') or relative.startswith('.'):continue
  if not (relative.endswith(('.pt','.yaml','.json','.md')) or PurePosixPath(relative).name in ['latest','last_best_checkpoint']):continue
  target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True);size=item.get('size');sha=item.get('lfs',{}).get('sha256')
  if target.exists() and (not size or target.stat().st_size==size):continue
  partial=target.with_name(target.name+'.part')
  if size and size>32*1024*1024:
   parallel_download('https://huggingface.co/'+repo+'/resolve/'+data['sha']+'/'+name,partial,size,sha)
   partial.replace(target);print('Cached',provider,relative,flush=True);continue
  for attempt in range(4):
   try:
    offset=partial.stat().st_size if partial.exists() else 0
    headers={'Range':'bytes='+str(offset)+'-'} if offset else {}
    req=urllib.request.Request('https://huggingface.co/'+repo+'/resolve/'+data['sha']+'/'+name,headers=headers)
    with urllib.request.urlopen(req,timeout=120) as response:
     append=offset>0 and response.status==206
     with partial.open('ab' if append else 'wb') as out:
      while True:
       chunk=response.read(1024*1024)
       if not chunk:break
       out.write(chunk)
    if size and partial.stat().st_size!=size:raise RuntimeError('Incomplete checkpoint download: '+name)
    if sha:
     checksum=hashlib.sha256()
     with partial.open('rb') as inp:
      for chunk in iter(lambda:inp.read(1024*1024),b''):checksum.update(chunk)
     if checksum.hexdigest()!=sha:partial.rename(partial.with_name(partial.name+'.invalid-'+str(time.time_ns())));raise RuntimeError('Checkpoint checksum mismatch: '+name)
    partial.replace(target);print('Cached',provider,relative,flush=True);break
   except Exception:
    if attempt==3:raise
    time.sleep(2*(attempt+1))
 return dest
def parallel_download(url,partial,size,sha):
 chunk_size=8*1024*1024
 count=(size+chunk_size-1)//chunk_size
 # Retain the complete chunks of an earlier sequential download.
 if partial.exists():
  with partial.open('rb') as original:
   for index in range(partial.stat().st_size//chunk_size):
    piece=partial.with_name(partial.name+'.chunk'+str(index))
    if not piece.exists():piece.write_bytes(original.read(chunk_size))
    else:original.seek(chunk_size,1)
 def fetch(index):
  start=index*chunk_size;end=min(size,start+chunk_size)-1;expected=end-start+1
  piece=partial.with_name(partial.name+'.chunk'+str(index))
  for attempt in range(5):
   try:
    offset=piece.stat().st_size if piece.exists() else 0
    if offset==expected:return piece
    if offset>expected:piece.rename(piece.with_name(piece.name+'.invalid-'+str(time.time_ns())));offset=0
    req=urllib.request.Request(url,headers={'Range':f'bytes={start+offset}-{end}'})
    with urllib.request.urlopen(req,timeout=120) as response:
     header=response.headers.get('Content-Range','')
     if response.status!=206 or not header.startswith(f'bytes {start+offset}-{end}/'):raise RuntimeError('Server returned an unexpected byte range')
     with piece.open('ab' if offset else 'wb') as output:
      while True:
       data=response.read(1024*1024)
       if not data:break
       output.write(data)
    if piece.stat().st_size!=expected:raise RuntimeError('Incomplete download chunk')
    return piece
   except Exception:
    if attempt==4:raise
    time.sleep(2*(attempt+1))
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:pieces=list(pool.map(fetch,range(count)))
 assembled=partial.with_name(partial.name+'.verified');checksum=hashlib.sha256()
 with assembled.open('wb') as out:
  for piece in pieces:
   with piece.open('rb') as stream:
    for block in iter(lambda:stream.read(1024*1024),b''):checksum.update(block);out.write(block)
 if assembled.stat().st_size!=size or (sha and checksum.hexdigest()!=sha):raise RuntimeError('Downloaded model checksum mismatch')
 assembled.replace(partial)
 for piece in pieces:piece.unlink()

def ensure_deepfilter(root):
 import zipfile
 folder=Path(root)/'deepfilternet';folder.mkdir(parents=True,exist_ok=True)
 model=folder/'DeepFilterNet3'
 if (model/'config.ini').exists() and list((model/'checkpoints').glob('*')):return model
 request=urllib.request.Request('https://api.github.com/repos/Rikorose/DeepFilterNet/contents/models/DeepFilterNet3.zip',headers={'User-Agent':'LocalVoiceEnhancement'})
 metadata=json.load(urllib.request.urlopen(request,timeout=60))
 partial=folder/'DeepFilterNet3.zip.part'
 offset=partial.stat().st_size if partial.exists() else 0
 headers={'Range':f'bytes={offset}-'} if offset else {}
 request=urllib.request.Request(metadata['download_url'],headers=headers)
 with urllib.request.urlopen(request,timeout=120) as response:
  with partial.open('ab' if offset and response.status==206 else 'wb') as output:
   while True:
    block=response.read(1024*1024)
    if not block:break
    output.write(block)
 if partial.stat().st_size!=metadata['size']:raise RuntimeError('Incomplete DeepFilterNet model download. Retry to resume.')
 checksum=hashlib.sha1(f"blob {metadata['size']}\0".encode())
 with partial.open('rb') as source:
  for block in iter(lambda:source.read(1024*1024),b''):checksum.update(block)
 if checksum.hexdigest()!=metadata['sha']:raise RuntimeError('DeepFilterNet model checksum mismatch.')
 with zipfile.ZipFile(partial) as archive:
  for entry in archive.infolist():
   if not (folder/entry.filename).resolve().is_relative_to(folder.resolve()):raise RuntimeError('Unsafe checkpoint archive path.')
  archive.extractall(folder)
 (folder/'source.json').write_text(json.dumps({'url':metadata['download_url'],'git_blob_sha1':metadata['sha']}))
 return model

def ensure(provider,root):
 root=Path(root);root.mkdir(parents=True,exist_ok=True)
 # A file lock prevents first-use inference from racing the cache installer.
 with (root/(provider+'.lock')).open('a+b') as lock:
  if lock.tell()==0:lock.write(b'0');lock.flush()
  while True:
   try:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);break
   except OSError:time.sleep(2)
  try:return ensure_deepfilter(root) if provider=='deepfilternet' else _ensure(provider,root)
  finally:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
if __name__=='__main__':
 import argparse
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--all',action='store_true');ap.add_argument('--provider',choices=list(REPOS));args=ap.parse_args()
 providers=list(REPOS) if args.all else [args.provider]
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
  for result in pool.map(lambda p:ensure(p,args.root),providers):print('MODEL CACHED:',result,flush=True)
