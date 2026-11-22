import io,os,tempfile,unittest,wave
from pathlib import Path
from unittest.mock import patch
import app
from audio_library import VoiceLibrary

class VoiceHistoryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.folder=self.root/'outputs';self.folder.mkdir();self.library=VoiceLibrary(self.folder,self.root/'voices.json',{'lessac'})
 def tearDown(self):self.temp.cleanup()
 def audio(self,name):
  path=self.folder/name
  with wave.open(str(path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0\0'*1600)
  return path
 def test_generation_survives_new_library_instance(self):
  path=self.audio('my-voice.wav');item=self.library.record({'path':str(path),'name':path.name,'duration':.1,'url':'/outputs/'+path.name,'text':'Original narration'})
  restored=VoiceLibrary(self.folder,self.root/'voices.json').recent()
  self.assertEqual(restored[0]['id'],item['id']);self.assertEqual(restored[0]['text'],'Original narration')
 def test_recovers_last_original_not_latest_enhancement(self):
  original=self.audio('original-lessac.wav');original.with_suffix('.srt').write_text('1\n00:00:00,000 --> 00:00:00,100\nOriginal narration.\n')
  enhanced=self.audio('original-lessac-deepfilternet-1234abcd.wav');os.utime(enhanced,(original.stat().st_mtime+5,original.stat().st_mtime+5))
  items=self.library.recent();self.assertEqual(len(items),1);self.assertEqual(items[0]['name'],original.name);self.assertEqual(items[0]['text'],'Original narration.')
 def test_duplicate_wav_mp3_and_deleted_items(self):
  path=self.audio('valid-lessac.wav');self.library.record({'path':str(path),'name':path.name});self.library.record({'path':str(path),'name':path.name})
  self.assertEqual(len(self.library.recent()),1);path.unlink();self.assertEqual(self.library.recent(),[])
 def test_special_filename_has_safe_preview_url(self):
  path=self.audio('voice #1.wav');path.with_suffix('.srt').write_text('1\n00:00:00,000 --> 00:00:00,100\nVoice\n')
  self.assertIn('%23',self.library.recent()[0]['url'])

class StudioRoutesTests(unittest.TestCase):
 def setUp(self):self.client=app.app.test_client()
 def test_video_creation_removed_and_audio_cues_preserved(self):
  for path,method in (('/api/footage','post'),('/api/footage/plan','post'),('/api/footage/keys','get'),('/api/footage/keys','post'),('/api/story','post')):
   self.assertEqual(getattr(self.client,method)(path).status_code,404,path)
  for path in ('/api/music','/api/sfx','/api/cues'):
   self.assertEqual(self.client.post(path).status_code,404)
  presets=self.client.get('/api/voices').get_json();self.assertTrue(presets['default'].startswith('kokoro:'));self.assertFalse(any(v.get('kind')=='piper' for v in presets['voices']))
  html=self.client.get('/').get_data(as_text=True)
  for element in ('mode-video','layout-video','video-form','voice-build-video','goto-video','pixabay-key','pexels-key','mode-music','mode-sfx','layout-music','layout-sfx'):
   self.assertNotIn('id="'+element+'"',html)
  for element in ('layout-voice','layout-enhance','layout-transcribe','layout-silence','kokoro-polish'):
   self.assertIn('id="'+element+'"',html)
 def test_empty_model_selection_is_not_silently_changed(self):
  response=self.client.post('/api/enhance',json={'path':__file__,'providers':[]});self.assertEqual(response.status_code,400)
 def test_new_file_forwards_exactly_two_checked_models(self):
  with tempfile.TemporaryDirectory() as folder,patch('app.UPLOAD_DIR',Path(folder)),patch('app.enhancement.start',return_value='two-model-job') as start:
   response=self.client.post('/api/enhance',data={'file':(io.BytesIO(b'RIFFtest'),'new voice #1.wav'),'providers':['deepfilternet','clearvoice'],'strength':'.5'})
   self.assertEqual(response.status_code,202);self.assertEqual(start.call_args.args[1],['deepfilternet','clearvoice']);self.assertTrue(start.call_args.args[0].is_file());start.call_args.args[0].unlink()
 def test_voice_history_endpoint_has_explicit_latest(self):
  with patch.object(app.voice_library,'recent',return_value=[{'id':'first','name':'latest.wav'}]):
   data=self.client.get('/api/voice-history').get_json();self.assertEqual(data['latest']['id'],'first')

if __name__=='__main__':unittest.main()
