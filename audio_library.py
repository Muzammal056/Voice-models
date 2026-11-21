"""Persistent original voiceover history for source selection and restoration."""
from __future__ import annotations
import hashlib,json,os,re,tempfile,threading,wave
from pathlib import Path
from urllib.parse import quote

class VoiceLibrary:
    def __init__(self,folder:Path,index:Path,aliases=()):
        self.folder=Path(folder).resolve();self.index=Path(index);self.aliases=set(aliases)|{'clone'};self.lock=threading.RLock()
    def _load(self):
        try:
            records=json.loads(self.index.read_text(encoding='utf-8'))
            return records if isinstance(records,list) else []
        except (OSError,ValueError):return []
    def _valid(self,record):
        try:
            path=Path(record['path']).resolve()
            return path.is_relative_to(self.folder) and path.is_file()
        except (KeyError,TypeError,OSError):return False
    def record(self,payload):
        item=dict(payload);path=Path(item['path']).resolve()
        if not path.is_relative_to(self.folder) or not path.is_file():raise ValueError('Voice history only accepts existing output files.')
        item.update(id=hashlib.sha256(str(path).lower().encode()).hexdigest()[:20],created=path.stat().st_mtime,kind='generated')
        with self.lock:
            records=[r for r in self._load() if r.get('id')!=item['id'] and self._valid(r)]
            records=sorted([item]+records,key=lambda r:r.get('created',0),reverse=True)[:100]
            self.index.parent.mkdir(parents=True,exist_ok=True)
            fd,name=tempfile.mkstemp(prefix='.voice-history-',suffix='.json',dir=self.index.parent)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as out:json.dump(records,out,ensure_ascii=False,indent=2)
                os.replace(name,self.index)
            finally:Path(name).unlink(missing_ok=True)
        return item
    def _legacy(self):
        paths=sorted((p for p in self.folder.glob('*') if p.suffix.lower() in ('.mp3','.wav','.m4a','.flac')),key=lambda p:p.stat().st_mtime,reverse=True)
        seen=set();records=[]
        for path in paths:
            stem=path.stem
            if stem in seen:continue
            if re.search(r'-(?:original|deepfilternet|resemble|clearvoice(?:_sr)?)-[0-9a-f]{8}(?:$|-)',stem,re.I):continue
            if stem.startswith(('speech-with-hiss','uploaded-voice','music-','sfx-')) or '-silence' in stem:continue
            paired=path.with_suffix('.srt')
            if not paired.is_file() and not any(re.search(r'-'+re.escape(alias)+r'(?:-|$)',stem,re.I) for alias in self.aliases):continue
            seen.add(stem)
            mp3=path.with_suffix('.mp3');path=mp3 if mp3.is_file() else path
            duration=0;rate=0
            try:
                import av
                with av.open(str(path)) as audio:
                    stream=audio.streams.audio[0];duration=float(audio.duration/av.time_base) if audio.duration else float((stream.duration or 0)*stream.time_base);rate=stream.rate or 0
            except Exception:pass
            wav=path.with_suffix('.wav');srt=paired.read_text(encoding='utf-8',errors='replace') if paired.is_file() else ''
            records.append({'id':hashlib.sha256(str(path.resolve()).lower().encode()).hexdigest()[:20],'name':path.name,'path':str(path.resolve()),'url':'/outputs/'+quote(path.name,safe=''),'lossless_path':str(wav.resolve()) if wav.is_file() else None,'duration':duration,'sample_rate':rate,'speed':1,'srt':srt,'srt_path':str(paired) if paired.is_file() else None,'text':' '.join(line.strip() for line in srt.splitlines() if line.strip() and not line.strip().isdigit() and '-->' not in line),'voice':'saved voice','kind':'recovered','created':path.stat().st_mtime})
            if len(records)>=40:break
        return records
    def recent(self,limit=30):
        with self.lock:
            stored=[r for r in self._load() if self._valid(r)]
            by_path={str(Path(r['path']).resolve()).lower():r for r in stored}
            for item in self._legacy():by_path.setdefault(str(Path(item['path']).resolve()).lower(),item)
            return sorted(by_path.values(),key=lambda r:r.get('created',0),reverse=True)[:limit]
