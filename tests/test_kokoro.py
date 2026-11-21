import tempfile,unittest,wave
from pathlib import Path
from unittest.mock import patch,Mock
import app
from kokoro_voice import KokoroSpeaker,KokoroResult,list_kokoro_voices

class KokoroTests(unittest.TestCase):
 def setUp(self):self.client=app.app.test_client()
 def test_list_has_twelve_unique_voices(self):
  voices=list_kokoro_voices();self.assertEqual(len(voices),12);self.assertEqual(len({v['id'] for v in voices}),12);self.assertTrue(all(v['kind']=='kokoro' for v in voices))
  self.assertEqual({v['id'] for v in voices if v['sample_url']},{'kokoro:am_michael','kokoro:am_adam'})
 def test_sample_whitelist(self):
  for voice in ('am_michael','am_adam'):
   with self.client.get('/api/kokoro-samples/'+voice) as response:self.assertEqual(response.status_code,200)
  self.assertEqual(self.client.get('/api/kokoro-samples/af_heart').status_code,404)
 def test_bad_voice_and_nan_rejected_before_loading(self):
  speaker=KokoroSpeaker()
  with self.assertRaises(ValueError):speaker.speak('hello','kokoro:unknown')
  with self.assertRaises(ValueError):speaker.speak('hello','kokoro:am_michael',float('nan'))
 def test_kokoro_dispatch_preserves_raw_and_finish_setting(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);raw=root/'kokoro-originals/raw.wav';raw.parent.mkdir();raw.write_bytes(b'raw');audio=root/'take.mp3';audio.write_bytes(b'mp3');audio.with_suffix('.wav').write_bytes(b'wav')
   speaker=Mock();speaker.speak.return_value=KokoroResult(audio,'kokoro:am_adam',1,24000,1,raw_path=raw,polished=False)
   with patch('app.OUTPUT_DIR',root),patch('app.get_kokoro',return_value=speaker),patch('app.get_speaker') as piper,patch('app._captions_for',return_value=('',None)),patch.object(app.voice_library,'record',side_effect=lambda x:x):
    response=self.client.post('/api/speak',json={'text':'hello','voice':'kokoro:am_adam','kokoro_polish':False,'remove_silence':False})
   self.assertEqual(response.status_code,200,response.get_json());data=response.get_json();self.assertEqual(data['engine'],'kokoro');self.assertFalse(data['polished']);self.assertEqual(data['raw_url'],'/outputs/kokoro-originals/raw.wav');self.assertFalse(speaker.speak.call_args.kwargs['polish']);piper.assert_not_called()

if __name__=='__main__':unittest.main()
