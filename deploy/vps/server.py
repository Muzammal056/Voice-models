"""Small, authenticated standalone Voice Studio. Neural weights stay off the web process."""
import hmac,json,os,secrets,subprocess,sys,threading,time,uuid,wave
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from flask import Flask,abort,jsonify,redirect,render_template,request,send_from_directory,session,url_for
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash
import imageio_ffmpeg
FFMPEG=imageio_ffmpeg.get_ffmpeg_exe()

DATA=Path(os.environ.get('VOICE_DATA','/data'));DATA.mkdir(parents=True,exist_ok=True)
OUT=DATA/'outputs';OUT.mkdir(exist_ok=True)
app=Flask(__name__);app.wsgi_app=ProxyFix(app.wsgi_app,x_for=1,x_proto=1)
app.config.update(SECRET_KEY=os.environ['VOICE_SESSION_SECRET'],MAX_CONTENT_LENGTH=30*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Strict',SESSION_COOKIE_SECURE=os.environ.get('VOICE_HTTPS','1')=='1',PERMANENT_SESSION_LIFETIME=timedelta(hours=12))
pool=ThreadPoolExecutor(max_workers=1);lock=threading.RLock();jobs={};attempts={}
VOICES=[{'id':'kokoro:'+v,'label':n+' · Kokoro'} for v,n in [('am_michael','Michael'),('am_adam','Adam'),('am_echo','Echo'),('am_eric','Eric'),('am_fenrir','Fenrir'),('am_liam','Liam'),('am_onyx','Onyx'),('am_puck','Puck'),('af_heart','Heart'),('af_bella','Bella'),('af_sarah','Sarah'),('af_nicole','Nicole')]]
IDS={v['id'] for v in VOICES};FILTERS={'denoise':'afftdn=nf=-25','presence':'highpass=f=80,equalizer=f=3000:t=o:w=1.5:g=3,equalizer=f=6000:t=o:w=1.5:g=2','compress':'acompressor=threshold=0.125:ratio=2:attack=20:release=200:makeup=1.3','normalize':'loudnorm=I=-16:TP=-1.5:LRA=11','silence':'silenceremove=start_periods=1:start_duration=0.1:start_threshold=-45dB:stop_periods=-1:stop_duration=0.8:stop_threshold=-45dB:stop_silence=0.25'}

def csrf():
 if 'csrf' not in session:session['csrf']=secrets.token_urlsafe(24)
 return session['csrf']
app.jinja_env.globals['csrf']=csrf

@app.before_request
def access():
 if request.endpoint in ('health','static'):return
 if not session.get('authenticated') and request.endpoint!='login':
  if request.path.startswith('/api/') or request.path.startswith('/audio/'):abort(401)
  return redirect(url_for('login'))
 if request.method=='POST':
  token=request.headers.get('X-CSRF-Token') or request.form.get('csrf','')
  if not token or not hmac.compare_digest(token,session.get('csrf','')):abort(403)

@app.after_request
def headers(response):
 response.headers['X-Content-Type-Options']='nosniff';response.headers['X-Frame-Options']='DENY';response.headers['Referrer-Policy']='no-referrer'
 response.headers['Cache-Control']='no-store'
 return response

@app.errorhandler(413)
def too_large(_):return jsonify(error='Choose an audio file smaller than 30 MB.'),413

@app.get('/health')
def health():return jsonify(status='ok',profile='standalone-voice')

@app.route('/login',methods=['GET','POST'])
def login():
 error=''
 if request.method=='POST':
  key=request.remote_addr;now=time.time();failures=[t for t in attempts.get(key,[]) if now-t<600]
  if len(failures)>=10:return render_template('login.html',error='Too many attempts. Try again in ten minutes.'),429
  if request.form.get('username')=='admin' and check_password_hash(os.environ['VOICE_PASSWORD_HASH'],request.form.get('password','')):
   session.clear();session['authenticated']=True;session.permanent=True;csrf();return redirect('/')
  attempts[key]=failures+[now];error='Incorrect username or password.'
 return render_template('login.html',error=error)

@app.post('/logout')
def logout():session.clear();return redirect('/login')

@app.get('/')
def home():return render_template('index.html',voices=VOICES)

def history():
 items=[]
 for path in OUT.glob('*.json'):
  try:
   item=json.loads(path.read_text());
   if (OUT/(item['id']+'.mp3')).is_file():items.append(item)
  except (OSError,ValueError,KeyError):pass
 return sorted(items,key=lambda x:x['created'],reverse=True)[:100]

@app.get('/api/history')
def recent():return jsonify(items=history())

@app.get('/api/jobs/<job>')
def status(job):
 with lock:
  if job not in jobs:abort(404)
  return jsonify(jobs[job])

def slots():return sum(j['state'] in ('queued','running') for j in jobs.values())

def submit(kind,payload):
 with lock:
  if slots()>=2:return jsonify(error='Two jobs are already queued. Please wait for one to finish.'),429
  token=uuid.uuid4().hex;jobs[token]={'id':token,'state':'queued','message':'Queued. One audio job runs at a time.'}
  pool.submit(process,token,kind,payload)
 return jsonify(id=token),202

@app.post('/api/speak')
def speak():
 payload=request.get_json(silent=True) or {};text=str(payload.get('text','')).strip();voice=str(payload.get('voice',''))
 try:speed=float(payload.get('speed',1))
 except (ValueError,TypeError):return jsonify(error='Choose a valid speaking speed.'),400
 if not text or len(text)>6000:return jsonify(error='Enter between 1 and 6,000 characters.'),400
 if voice not in IDS or not .6<=speed<=1.5:return jsonify(error='Choose a listed voice and a speed between 0.6 and 1.5.'),400
 return submit('speak',{'text':text,'voice':voice,'speed':speed,'filters':['presence','normalize'] if payload.get('finish',True) else []})

@app.post('/api/enhance')
def enhance():
 filters=request.form.getlist('filters')
 if not filters or any(f not in FILTERS for f in filters):return jsonify(error='Select at least one audio treatment.'),400
 with lock:
  if slots()>=2:return jsonify(error='Please wait for the current jobs to finish.'),429
  file=request.files.get('file');source_id=request.form.get('source','');uploaded=False
  if file and file.filename:
   suffix=Path(file.filename).suffix.lower()
   if suffix not in {'.wav','.mp3','.m4a','.flac','.ogg','.aac'}:return jsonify(error='Choose WAV, MP3, M4A, FLAC, OGG or AAC audio.'),400
   path=OUT/('upload-'+uuid.uuid4().hex+suffix);file.save(path);uploaded=True;title=Path(file.filename).name[:100]
  elif len(source_id)==32 and all(c in '0123456789abcdef' for c in source_id) and (OUT/(source_id+'.mp3')).is_file():
   path=OUT/(source_id+'.wav');path=path if path.is_file() else OUT/(source_id+'.mp3');title=next((x['title'] for x in history() if x['id']==source_id),'Saved voiceover')
  else:return jsonify(error='Select a generated voice or upload a new audio file.'),400
  return submit('enhance',{'source':str(path),'uploaded':uploaded,'title':title,'filters':filters})

def run(command,timeout=900):
 result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
 if result.returncode:raise RuntimeError(result.stderr[-1600:] or 'The audio process could not finish.')
 return result

def process(token,kind,payload):
 raw=OUT/(token+'-raw.wav');wav=OUT/(token+'.wav');mp3=OUT/(token+'.mp3');request_path=OUT/(token+'-request.json')
 try:
  with lock:jobs[token].update(state='running',message='Generating speech on the VPS…' if kind=='speak' else 'Finishing your audio…')
  if kind=='speak':
   request_path.write_text(json.dumps({**payload,'output':str(raw),'model_dir':str(DATA/'models')}))
   run([sys.executable,str(Path(__file__).with_name('worker.py')),str(request_path)])
   source=raw;title=payload['text'][:110];voice=payload['voice']
  else:
   source=Path(payload['source']);title=payload['title'];voice='Audio finishing'
   if payload.get('uploaded'):raw=source
   else:raw=OUT/(token+'-raw.wav');run([FFMPEG,'-v','error','-y','-threads','1','-i',str(source),'-vn','-t','600','-ar','24000','-ac','1',str(raw)]);source=raw
  command=[FFMPEG,'-v','error','-y','-threads','1','-filter_threads','1','-i',str(source),'-vn','-t','600']
  if payload['filters']:command+=['-af',','.join(FILTERS[f] for f in payload['filters'])]
  run(command+['-ac','1','-ar','24000','-c:a','pcm_s16le',str(wav)])
  with wave.open(str(wav)) as audio:duration=audio.getnframes()/audio.getframerate()
  if duration<.05:raise ValueError('No audible audio remained. Try disabling silence removal.')
  run([FFMPEG,'-v','error','-y','-threads','1','-i',str(wav),'-c:a','libmp3lame','-b:a','192k',str(mp3)])
  item={'id':token,'title':title,'voice':voice,'kind':kind,'duration':round(duration,2),'created':time.time(),'url':'/audio/'+mp3.name,'wav_url':'/audio/'+wav.name,'raw_url':'/audio/'+raw.name,'text':payload.get('text',''),'filters':payload['filters']}
  (OUT/(token+'.json')).write_text(json.dumps(item));
  with lock:jobs[token].update(state='done',message='Your audio is ready.',result=item)
 except Exception as error:
  app.logger.exception('Audio job failed: %s',token)
  with lock:jobs[token].update(state='error',message='Audio could not finish. '+('Try a shorter script.' if kind=='speak' else 'Check the audio file and try again.'))
 finally:request_path.unlink(missing_ok=True)

@app.get('/audio/<name>')
def audio(name):
 if Path(name).suffix not in {'.wav','.mp3','.m4a','.flac','.ogg','.aac'}:abort(404)
 return send_from_directory(OUT,name,as_attachment=request.args.get('download')=='1')

if __name__=='__main__':
 from waitress import serve
 serve(app,host='0.0.0.0',port=7860,threads=4,max_request_body_size=30*1024*1024,channel_timeout=120)
