"""One bounded CPU synthesis process; exiting releases model memory."""
import json,os,re,sys,wave
from pathlib import Path
os.environ['OMP_NUM_THREADS']='1';os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['MKL_NUM_THREADS']='1'
def main():
 import numpy as np
 payload=json.loads(Path(sys.argv[1]).read_text());root=Path(payload['model_dir']);voice=payload['voice'];speed=payload['speed']
 sentences=re.split(r'(?<=[.!?])\s+|\n+',payload['text']);chunks=[]
 for sentence in sentences:
  words=sentence.split();current=''
  for word in words:
   if len(current)+len(word)>160 and current:chunks.append(current);current=''
   current=(current+' '+word).strip()
  if current:chunks.append(current)
 if voice.startswith('kokoro:'):
  import onnxruntime as rt
  from kokoro_onnx import Kokoro
  options=rt.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1;options.enable_cpu_mem_arena=False;options.enable_mem_pattern=False;options.graph_optimization_level=rt.GraphOptimizationLevel.ORT_ENABLE_BASIC
  options.add_session_config_entry('session.intra_op.allow_spinning','0')
  model=rt.InferenceSession(str(root/'kokoro.int8.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
  engine=Kokoro.from_session(model,str(root/'voices.bin'))
  def generate(text):return engine.create(text,voice=voice.split(':',1)[1],speed=speed,lang='en-us')[0]
  rate=24000
 else:raise ValueError('Choose a Kokoro voice.')
 with wave.open(payload['output'],'wb') as out:
  out.setnchannels(1);out.setsampwidth(2);out.setframerate(rate)
  for index,text in enumerate(chunks):
   samples=np.asarray(generate(text),dtype=np.float32).reshape(-1)
   if not samples.size or not np.isfinite(samples).all():raise ValueError('Invalid speech output')
   if index:out.writeframes(b'\0\0'*int(rate*.15))
   out.writeframes((np.clip(samples,-1,1)*32767).astype('<i2').tobytes())
 print('Speech ready',flush=True)
if __name__=='__main__':main()
