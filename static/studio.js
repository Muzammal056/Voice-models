(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const sourceRadios = [...document.querySelectorAll('[name="enhance-source"]')];
  const modelInputs = [...document.querySelectorAll('[name="enhance-provider"]')];
  const labels = {deepfilternet:'DeepFilterNet 3',resemble:'Resemble Enhance',clearvoice:'ClearerVoice',clearvoice_sr:'Bandwidth extension'};
  const keys = {settings:'voiceStudio.enhanceSettings',active:'voiceStudio.selectedVoice',job:'voiceStudio.enhanceSession'};
  const read = key => { try { return JSON.parse(localStorage.getItem(key)); } catch { return null; } };
  const save = (key,value) => { try { localStorage.setItem(key,JSON.stringify(value)); } catch {} };
  let voices = [], latest = null, upload = null, uploadURL = '', pathVoice = null;
  let busy = false, run = null, pollToken = 0, sourcePreviewURL = '', libraryRequest = 0;
  const cards = new Map();
  const duration = seconds => { const n=Math.round(Number(seconds)||0);return `${Math.floor(n/60)}:${String(n%60).padStart(2,'0')}`; };
  const cleanName = name => String(name || 'Voiceover').replace(/\.[^.]+$/,'').replace(/-/g,' ');
  function message(text,error=false) { $('enhance-status').textContent=text;$('enhance-status').className='status'+(error?' error':''); }
  function voiceTitle(voice) {
    const text=String(voice?.text||'').replace(/\s+/g,' ').trim();
    return text?text.slice(0,75)+(text.length>75?'…':''):cleanName(voice?.name).replace(/\s+\d{8}\s+\d{6}$/,'');
  }
  function selectedModels() { return modelInputs.filter(input=>input.checked).map(input=>input.value); }
  function sourceMode() { return sourceRadios.find(input=>input.checked)?.value || 'latest'; }
  function chooseMode(mode) { sourceRadios.forEach(input=>{input.checked=input.value===mode;});updateSource(); }
  function selectedSource() {
    if (sourceMode()==='latest') return latest ? {path:latest.lossless_path||latest.path,name:latest.name,url:latest.url,base:latest} : null;
    if (sourceMode()==='saved') {const voice=voices.find(v=>v.id===$('enhance-history').value);return voice?{path:voice.lossless_path||voice.path,name:voice.name,url:voice.url,base:voice}:null;}
    if (upload) return {file:upload,name:upload.name,url:uploadURL,base:null};
    const path=$('enhance-path').value.trim();return path?{path,name:path.split(/[\\/]/).pop(),url:pathVoice?.url||'',base:pathVoice}:null;
  }
  function rememberSettings() { save(keys.settings,{providers:selectedModels(),strength:Number($('enhance-strength').value),normalize:$('enhance-normalize').checked,auto:$('enhance-auto').checked}); }
  function updateControls() {
    const models=selectedModels(),source=selectedSource();
    $('enhance-selection-count').textContent=`${models.length} enhancer${models.length===1?'':'s'} selected`;
    $('enhance-run').disabled=busy||!source||!models.length;
    $('enhance-run').textContent=busy?'Processing audio…':models.length>1?`Enhance with ${models.length} models →`:'Enhance audio →';
    $('enhance-cancel').classList.toggle('hidden',!busy);$('enhance-cancel').disabled=!run?.job;
    for (const input of [...sourceRadios,...modelInputs,$('enhance-history'),$('enhance-file'),$('enhance-path'),$('enhance-strength'),$('enhance-normalize'),$('enhance-auto')]) input.disabled=busy||(input.name==='enhance-source'&&input.value==='latest'&&!latest);
    for (const id of ['enhance-select-cleanup','enhance-clear-models','enhance-clear-file']) $(id).disabled=busy;
    $('speak').disabled=busy||voiceGenerating;
    $('voice-open-enhance').disabled=!lastVoice;
  }
  function updateSource() {
    const mode=sourceMode(),source=selectedSource();
    $('enhance-history-wrap').classList.toggle('hidden',mode!=='saved');$('enhance-upload-wrap').classList.toggle('hidden',mode!=='upload');
    $('latest-voice-caption').textContent=latest?voiceTitle(latest):'Generate a voiceover to use it here';
    $('enhance-source-name').textContent=source?.name || (mode==='latest'?'No generated voiceover yet.':mode==='saved'?'Choose a saved voiceover.':'Choose a file or paste its local path.');
    $('enhance-source-detail').textContent=source?.file?`${(source.file.size/1024/1024).toFixed(1)} MB · Ready to upload`:source?.base?`${duration(source.base.duration)} · Original voiceover`:source?'Preview available after processing.':'';
    const url=source?.url||'',audio=$('enhance-source-preview');
    if (url!==sourcePreviewURL) {audio.pause();if(url)audio.src=url;else audio.removeAttribute('src');sourcePreviewURL=url;}
    audio.classList.toggle('hidden',!url);updateControls();
  }
  function audioPlayer(url) {
    const audio=document.createElement('audio');audio.controls=true;audio.preload='metadata';audio.src=url;
    audio.addEventListener('play',()=>document.querySelectorAll('audio').forEach(other=>{if(other!==audio)other.pause();}));return audio;
  }
  function setActive(voice,{render=true,persist=true}={}) {
    lastVoice={speed:1,srt:'',...voice};if(persist)save(keys.active,lastVoice);
    $('voice-active-label').textContent=voice.label||'Original voiceover';
    $('voice-meta').textContent=`${voiceTitle(voice)} · ${duration(voice.duration)}${voice.sample_rate?' · '+(voice.sample_rate/1000).toFixed(1)+' kHz':''}`;
    $('download-voice-raw')?.classList.toggle('hidden',!voice.raw_url);
    $('download-audio').disabled=false;$('download-audio').textContent=voice.name?.toLowerCase().endsWith('.wav')?'Download WAV':'Download MP3';$('download-voice-srt').disabled=!voice.srt;
    if(render){const wrapper=document.createElement('div');wrapper.className='player-wrap';wrapper.append(audioPlayer(voice.url));$('voice-result').replaceChildren(wrapper);}
    if(voice.text&&!$('script').value.trim()){$('script').value=voice.text;updateScriptCount();}
    syncSelectedResults();
    updateControls();
  }
  function renderLibrary() {
    const previous=$('enhance-history').value,select=$('enhance-history');select.replaceChildren(new Option('Choose a saved voiceover',''));
    for(const voice of voices)select.append(new Option(`${voiceTitle(voice)} · ${duration(voice.duration)}`,voice.id));
    if(voices.some(v=>v.id===previous))select.value=previous;
    const list=$('recent-voice-list');list.replaceChildren();
    for(const voice of voices.slice(0,5)){
      const row=document.createElement('button');row.type='button';row.className='library-row';row.title=voice.name;
      const icon=document.createElement('span');icon.className='audio-icon';icon.textContent='≋';icon.setAttribute('aria-hidden','true');
      const name=document.createElement('span');name.className='library-name';const title=document.createElement('strong');title.textContent=voiceTitle(voice);const detail=document.createElement('small');detail.textContent=`${duration(voice.duration)} · ${new Date(voice.created*1000).toLocaleDateString()} · Original`;name.append(title,detail);
      const action=document.createElement('span');action.className='row-action';action.textContent='Select ↗';row.append(icon,name,action);row.addEventListener('click',()=>setActive(voice));list.append(row);
    }
    if(!voices.length){const empty=document.createElement('div');empty.className='empty-library';empty.textContent='Your generated voiceovers will appear here. Upload existing audio in the Enhance workspace.';list.append(empty);}
    updateSource();
  }
  async function loadLibrary({restore=false}={}) {
    const request=++libraryRequest;
    try{
      const response=await fetch('/api/voice-history',{cache:'no-store'});const data=await response.json();if(!response.ok)throw Error(data.error||'Could not load saved voices.');if(request!==libraryRequest)return;
      voices=data.voices||[];latest=data.latest;renderLibrary();
      if(restore&&!lastVoice){const saved=read(keys.active);let active=null;if(saved?.url){try{if((await fetch(saved.url,{method:'HEAD'})).ok)active=saved;}catch{}}
        if(active||latest)setActive(active||latest);
      }
    }catch(error){$('recent-voice-list').textContent=error.message;$('latest-voice-caption').textContent='Voice library unavailable. Refresh to retry.';}
  }
  async function loadModels() {
    try{const data=await(await fetch('/api/enhancers')).json();for(const model of data.enhancers||[]){const badge=document.querySelector(`[data-model-status="${model.id}"]`);if(badge){badge.textContent=model.state==='ready'?'● Ready on this computer':'↓ Downloads on first use';badge.classList.toggle('ready',model.state==='ready');}}
      $('enhancer-availability').textContent=data.enhancers?.every(model=>model.runtime_installed)?'Originals stay untouched. Processing runs on this computer.':'Enhancer setup is incomplete. Run Setup Voice Enhancers.bat in the app folder.';
    }catch{$('enhancer-availability').textContent='Model status unavailable. Refresh the page to retry.';}
  }
  function chooseFile(file) {
    if(!file)return;if(uploadURL)URL.revokeObjectURL(uploadURL);upload=file;uploadURL=URL.createObjectURL(file);pathVoice=null;$('enhance-path').value='';
    $('enhance-upload-name').textContent=`${file.name} · ${(file.size/1024/1024).toFixed(1)} MB`;$('enhance-upload-info').classList.remove('hidden');chooseMode('upload');
  }
  function openEnhance() {
    if(lastVoice){const voice=voices.find(item=>item.path===lastVoice.path);
      if(voice){$('enhance-history').value=voice.id;chooseMode(voice.id===latest?.id?'latest':'saved');}
      else {upload=null;$('enhance-file').value='';$('enhance-upload-info').classList.add('hidden');pathVoice={...lastVoice};$('enhance-path').value=lastVoice.lossless_path||lastVoice.path;chooseMode('upload');$('enhance-path').closest('details').open=true;}
    }else chooseMode('latest');showMode('enhance');
  }
  function syncSelectedResults() {
    for(const card of cards.values()) {
      const selected=!!lastVoice?.path&&card.dataset.voicePath===lastVoice.path;
      card.classList.toggle('selected',selected);
      card.querySelector('.result-use')?.setAttribute('aria-pressed',String(selected));
    }
  }
  function createResult(key,title,subtitle,url,path) {
    const card=document.createElement('article');card.className='result-card';card.dataset.provider=key;card.dataset.voicePath=path;
    const label=document.createElement('strong');label.className='result-label';label.textContent=title;
    const detail=document.createElement('div');detail.className='result-subtitle';detail.textContent=subtitle;card.append(label,detail,audioPlayer(url));cards.set(key,card);$('enhancement-results').append(card);return card;
  }
  function renderJob(job) {
    if(!$('enhancement-results').querySelector('.result-card')&&(job.original_url||job.results?.length||job.errors?.length))$('enhancement-results').replaceChildren();
    if(job.original_url&&!cards.has('original')){
      if(!run.base)run.base={path:job.original_path,url:job.original_url,name:run.sourceName,lossless_path:job.original_path,duration:job.results[0]?.duration||0,sample_rate:48000,srt:'',text:''};
      const base=run.base;const card=createResult('original','Original audio',run.sourceName,job.original_url,base.path);const use=document.createElement('button');use.className='secondary result-use';use.type='button';use.textContent='Use original';use.addEventListener('click',()=>{setActive(base);message('Original selected for downloads.');});card.append(use);
    }
    if(run.base&&!run.base.duration&&job.results?.[0])run.base.duration=job.results[0].duration;
    for(const item of job.results||[]){if(cards.has(item.provider))continue;const base={...run.base};const card=createResult(item.provider,item.label,`${duration(item.duration)} · 48 kHz · Enhanced`,item.url,item.path);
      const use=document.createElement('button');use.type='button';use.className='secondary result-use';use.textContent='Use this voice';use.addEventListener('click',()=>{setActive({...base,...item,lossless_path:item.wav_path,label:item.label});message(`${item.label} selected for downloads.`);});card.append(use);
      const links=document.createElement('div');links.className='result-downloads';for(const [label,url] of [['Download MP3',item.url],['Download WAV',item.wav_url]]){const link=document.createElement('a');link.textContent=label;link.href=url;link.download='';links.append(link);}card.append(links);
    }
    for(const failure of job.errors||[]){const key='error-'+failure.provider;if(cards.has(key))continue;const card=document.createElement('article');card.className='result-card result-error';const title=document.createElement('strong');title.textContent=labels[failure.provider]||failure.provider;const detail=document.createElement('p');detail.textContent=failure.error;card.append(title,detail);cards.set(key,card);$('enhancement-results').append(card);}
    if(job.log_url&&!$('enhancement-results').querySelector('.result-log')){const link=document.createElement('a');link.href=job.log_url;link.target='_blank';link.className='result-log';link.textContent='View processing log';$('enhancement-results').append(link);}
    syncSelectedResults();
    const completed=(job.results?.length||0)+(job.errors?.length||0);$('enhance-result-count').textContent=`${job.results?.length||0} enhanced version${job.results?.length===1?'':'s'}`;
    $('enhance-progress').max=run.providers.length||1;$('enhance-progress').value=completed;
  }
  async function watchJob(session,{cached=false}={}) {
    const token=++pollToken;run=session;$('enhance-results-source').textContent='Source: '+session.sourceName;busy=true;cards.clear();$('enhancement-results').replaceChildren();$('enhance-progress').classList.remove('hidden');updateControls();
    try{while(token===pollToken){const response=await fetch(session.status_url,{cache:'no-store'});const job=await response.json();
      if(!response.ok){if(cached&&session.data){renderJob(session.data);message('Showing your saved results. Choose a source to start another enhancement.');break;}throw Error(job.error||'Could not read enhancement progress.');}
      message(job.message||job.state,job.state==='error');renderJob(job);session.data=job;save(keys.job,session);
      if(['done','error','cancelled'].includes(job.state)){loadModels();break;}await new Promise(resolve=>setTimeout(resolve,1200));
    }}catch(error){message(error.message,true);}finally{if(token===pollToken){busy=false;$('enhance-progress').classList.add('hidden');updateControls();}}
  }
  async function startEnhancement() {
    if(busy)return;const source=selectedSource(),providers=selectedModels();
    if(!source){message('Choose a generated voice, saved voiceover, or new file first.',true);return;}if(!providers.length){message('Select at least one enhancer.',true);return;}
    busy=true;run=null;updateControls();message('Preparing your audio…');
    const session={providers,sourceName:source.name,base:source.base?{...source.base}:null};
    try{const settings={providers,path:source.path,strength:Number($('enhance-strength').value)/100,normalize:$('enhance-normalize').checked};let options;
      if(source.file){const data=new FormData();data.append('file',source.file);for(const provider of providers)data.append('providers',provider);data.append('strength',settings.strength);data.append('normalize',settings.normalize?'1':'0');options={method:'POST',body:data};}
      else options={method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)};
      const response=await fetch('/api/enhance',options);const payload=await response.json();if(!response.ok)throw Error(payload.error||'Could not start enhancement.');
      Object.assign(session,payload);save(keys.job,session);await watchJob(session);
    }catch(error){message(error.message,true);busy=false;updateControls();}
  }
  sourceRadios.forEach(input=>input.addEventListener('change',updateSource));modelInputs.forEach(input=>input.addEventListener('change',()=>{rememberSettings();updateControls();}));
  $('enhance-history').addEventListener('change',updateSource);
  $('enhance-drop').addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)&&!busy){event.preventDefault();$('enhance-file').click();}});
  $('enhance-file').addEventListener('change',()=>chooseFile($('enhance-file').files[0]));
  for(const type of ['dragenter','dragover'])$('enhance-drop').addEventListener(type,event=>{event.preventDefault();$('enhance-drop').classList.add('drag');});
  for(const type of ['dragleave','drop'])$('enhance-drop').addEventListener(type,event=>{event.preventDefault();$('enhance-drop').classList.remove('drag');if(type==='drop')chooseFile(event.dataTransfer.files[0]);});
  $('enhance-path').addEventListener('input',()=>{upload=null;pathVoice=null;$('enhance-file').value='';$('enhance-upload-info').classList.add('hidden');updateSource();});
  $('enhance-clear-file').addEventListener('click',()=>{upload=null;if(uploadURL)URL.revokeObjectURL(uploadURL);uploadURL='';$('enhance-file').value='';$('enhance-upload-info').classList.add('hidden');updateSource();});
  $('enhance-select-cleanup').addEventListener('click',()=>{modelInputs.forEach(input=>{input.checked=input.value!=='clearvoice_sr';});rememberSettings();updateControls();});
  $('enhance-clear-models').addEventListener('click',()=>{modelInputs.forEach(input=>{input.checked=false;});rememberSettings();updateControls();});
  $('enhance-strength').addEventListener('input',()=>{$('enhance-strength-value').textContent=$('enhance-strength').value+'%';rememberSettings();});
  for(const id of ['enhance-normalize','enhance-auto'])$(id).addEventListener('change',rememberSettings);
  $('enhance-run').addEventListener('click',startEnhancement);
  $('enhance-cancel').addEventListener('click',async()=>{if(!run?.job)return;try{const response=await fetch('/api/enhance/'+run.job+'/cancel',{method:'POST'});if(!response.ok)throw Error('Could not cancel this task.');message('Stopping enhancement…');}catch(error){message(error.message,true);}});
  for(const id of ['enhance-refresh','voice-library-refresh'])$(id).addEventListener('click',()=>loadLibrary());
  $('download-voice-raw')?.addEventListener('click',()=>{if(!lastVoice?.raw_url)return;const link=document.createElement('a');link.href=lastVoice.raw_url;link.download=lastVoice.name.replace(/\.[^.]+$/,'-raw.wav');link.click();});
  $('voice-open-enhance').addEventListener('click',openEnhance);
  window.addEventListener('studio:mode',event=>{if(['voice','enhance'].includes(event.detail))loadLibrary();});
  window.voiceEnhancement={generationBusy(value){voiceGenerating=!!value;updateControls();},generated(payload){latest=payload;setActive(payload,{render:false});loadLibrary();if($('enhance-auto').checked){chooseMode('latest');setTimeout(startEnhancement,0);}}};
  const settings=read(keys.settings);if(settings){if(Array.isArray(settings.providers))modelInputs.forEach(input=>{input.checked=settings.providers.includes(input.value);});$('enhance-strength').value=settings.strength||75;$('enhance-normalize').checked=settings.normalize!==false;$('enhance-auto').checked=!!settings.auto;}
  $('enhance-strength-value').textContent=$('enhance-strength').value+'%';updateSource();loadModels();
  loadLibrary({restore:true}).then(()=>{const previous=read(keys.job);if(previous?.job&&previous.status_url)watchJob(previous,{cached:true});});
})();
