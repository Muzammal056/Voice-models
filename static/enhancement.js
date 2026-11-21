(() => {
  const el = id => document.getElementById(id);
  const selector = el('voice-enhancer'), strength = el('enhance-strength');
  const status = el('enhance-status'), results = el('enhancement-results');
  let originalVoice = null, busy = false, token = 0, activeJob = null;
  const prefs = 'voiceApp.enhancer';
  try { const saved = localStorage.getItem(prefs); if ([...selector.options].some(o => o.value === saved)) selector.value = saved; } catch (_) {}
  selector.addEventListener('change', () => { try { localStorage.setItem(prefs, selector.value); } catch (_) {} updateButtons(); });
  strength.addEventListener('input', () => { el('enhance-strength-value').textContent = strength.value + '%'; });
  function updateButtons() {
    el('enhance-last').disabled = busy || !(originalVoice || lastVoice) || selector.value === 'off';
    el('enhance-existing').disabled = busy;
    selector.disabled = busy; strength.disabled = busy; el('enhance-normalize').disabled = busy;
    el('speak').disabled = busy; el('enhance-cancel').classList.toggle('hidden',!busy);
  }
  function message(text, error = false) { status.textContent = text; status.className = 'status' + (error ? ' error' : ''); }
  function player(label, url) {
    const box = document.createElement('div'); box.className = 'player-wrap';
    const title = document.createElement('strong'); title.textContent = label; box.append(title);
    const audio = document.createElement('audio'); audio.controls = true; audio.src = url; audio.addEventListener('play',()=>document.querySelectorAll('#layout-voice audio').forEach(other=>{if(other!==audio)other.pause()})); box.append(audio);
    return box;
  }
  function useVoice(item) {
    lastVoice = {speed:1, voice:'enhanced', mode:'enhanced', srt:'', ...originalVoice, ...item};
    const wrap = el('voice-result'); wrap.replaceChildren(player('Selected voiceover', lastVoice.url));
    el('voice-meta').textContent = lastVoice.name + ' · ' + Number(lastVoice.duration).toFixed(1) + 's · ' + lastVoice.sample_rate + ' Hz';
    el('download-audio').disabled = false;
    el('download-audio').textContent = lastVoice.name.endsWith('.wav') ? 'Download WAV' : 'Download MP3';
    el('download-voice-srt').disabled = !lastVoice.srt;
    message('Selected ' + (item.label || 'original') + ' for downloads and music mixing.');
  }
  function render(job) {
    results.replaceChildren();
    if (job.original_url) {
      if (!originalVoice) originalVoice = {path:job.original_path,url:job.original_url,name:job.original_path.split(/[\\/]/).pop(),duration:job.results[0]?.duration || 0,sample_rate:48000,speed:1,srt:''};
      if (!originalVoice.duration && job.results[0]) originalVoice.duration = job.results[0].duration;
      const box = player('Original — unchanged content', job.original_url);
      const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = 'Use original';
      button.addEventListener('click', () => useVoice(originalVoice || {path:job.original_path, url:job.original_url, name:job.original_path.split(/[\\/]/).pop(), duration:job.results[0]?.duration || 0, sample_rate:48000}));
      box.append(button); results.append(box);
    }
    for (const item of job.results || []) {
      const box = player(item.label, item.url);
      const select = document.createElement('button'); select.type = 'button'; select.className = 'secondary'; select.textContent = 'Use this voice'; select.addEventListener('click', () => useVoice(item)); box.append(select);
      for (const [label,url] of [['Download MP3',item.url],['Download WAV',item.wav_url]]) {
        const link = document.createElement('a'); link.textContent = label; link.href = url; link.download = ''; link.style.cssText = 'display:inline-block;margin:10px;color:var(--accent)'; box.append(link);
      }
      results.append(box);
    }
    for (const failure of job.errors || []) {
      const line = document.createElement('p'); line.className = 'status error'; line.textContent = failure.provider + ': ' + failure.error; results.append(line);
    }
    if (job.log_url) { const log = document.createElement('a'); log.href = job.log_url; log.textContent = 'Processing log'; log.target = '_blank'; results.append(log); }
  }
  async function start(source, file = null) {
    if (busy) return;
    const provider = selector.value;
    if (provider === 'off') { message('Choose an enhancer first.', true); return; }
    const providers = provider === 'compare' ? ['deepfilternet','resemble','clearvoice'] : [provider];
    busy = true; updateButtons(); const current = ++token;
    message('Preparing enhancement… First use may download model weights.'); results.replaceChildren();
    try {
      let options;
      const settings = {providers, path:source, strength:Number(strength.value)/100, normalize:el('enhance-normalize').checked};
      if (file) {
        const data = new FormData(); data.append('file',file); data.append('provider',provider);
        // A JSON list is not used for ordinary upload forms; compare is sent below.
        data.delete('provider'); for (const id of providers) data.append('providers',id);
        data.append('strength',String(settings.strength)); data.append('normalize',settings.normalize ? '1' : '0');
        options = {method:'POST',body:data};
      } else options = {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)};
      const response = await fetch('/api/enhance',options), payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not start enhancement');
      activeJob = payload.job;
      let previous = '';
      while (current === token) {
        await new Promise(resolve => setTimeout(resolve,1200));
        const check = await fetch(payload.status_url), job = await check.json();
        if (!check.ok) throw new Error(job.error || 'Could not read enhancement progress');
        message(job.message || job.state, job.state === 'error');
        const fingerprint = JSON.stringify([job.results,job.errors,job.state]);
        if (fingerprint !== previous) { render(job); previous = fingerprint; }
        if (['done','error','cancelled'].includes(job.state)) break;
      }
    } catch (error) { message(error.message, true); }
    finally { if (current === token) { busy = false; activeJob = null; updateButtons(); } }
  }
  el('enhance-cancel').addEventListener('click', async () => { if (!activeJob) return; try { await fetch('/api/enhance/'+activeJob+'/cancel',{method:'POST'}); message('Cancelling enhancement…'); } catch (error) { message(error.message,true); } });
  el('enhance-last').addEventListener('click', () => {
    originalVoice = originalVoice || lastVoice;
    if (originalVoice?.path) start(originalVoice.lossless_path || originalVoice.path);
  });
  el('enhance-existing').addEventListener('click', () => {
    const file = el('enhance-file').files[0], path = el('enhance-path').value.trim();
    if (!file && !path) { message('Choose an audio/video file or paste its local path.', true); return; }
    originalVoice = null; start(path,file || null);
  });
  window.voiceEnhancement = { generated(payload) {
    originalVoice = payload; results.replaceChildren(); el('download-audio').textContent = 'Download MP3';
    if (selector.value !== 'off') setTimeout(() => start(payload.lossless_path || payload.path),0);
    else updateButtons();
  }};
  fetch('/api/enhancers').then(r => r.json()).then(data => {
    if (!data.enhancers.every(item => item.runtime_installed)) { el('enhancer-availability').textContent = 'Enhancer setup is not finished. Run Setup Voice Enhancers.bat if installation is not already running.'; return; }
    const ready = data.enhancers.filter(item => item.state === 'ready').length;
    el('enhancer-availability').textContent = ready ? ready + ' enhancement model(s) prepared. Original and enhanced versions are saved separately.' : 'First use downloads the selected model. Processing stays on this PC; CPU enhancement can take several minutes.';
  }).catch(() => {});
  updateButtons();
})();
