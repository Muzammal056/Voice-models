import tempfile,unittest,wave
from pathlib import Path
from unittest.mock import patch,Mock
import app
from kokoro_voice import KokoroSpeaker,KokoroResult,list_kokoro_voices

class KokoroTests(unittest.TestCase):
 def setUp(self):self.client=app.app.test_client()
 def test_list_has_two_unique_voices(self):
  voices=list_kokoro_voices();self.assertEqual(len(voices),2);self.assertEqual(len({v['id'] for v in voices}),2);self.assertTrue(all(v['kind']=='kokoro' for v in voices))
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
   with patch('app.OUTPUT_DIR',root),patch('app.get_kokoro',return_value=speaker),patch('app.get_cloner') as cloner,patch('app._captions_for',return_value=('',None)),patch.object(app.voice_library,'record',side_effect=lambda x:x):
    response=self.client.post('/api/speak',json={'text':'hello','voice':'kokoro:am_adam','kokoro_polish':False})
   self.assertEqual(response.status_code,200,response.get_json());data=response.get_json();self.assertEqual(data['engine'],'kokoro');self.assertFalse(data['polished']);self.assertEqual(data['raw_url'],'/outputs/kokoro-originals/raw.wav');self.assertFalse(speaker.speak.call_args.kwargs['polish']);self.assertFalse(speaker.speak.call_args.kwargs['remove_silence']);cloner.assert_not_called()

class SpeechTextTests(unittest.TestCase):
 def test_document_wraps_do_not_split_words_or_phrases(self):
  from kokoro_text import speech_paragraphs
  self.assertEqual(speech_paragraphs('He reconstructed the infra-\nstructure.\nDr. Smith paid $12.50.'),['He reconstructed the infrastructure. Dr. Smith paid $12.50.'])
 def test_real_paragraphs_and_compound_words_remain(self):
  from kokoro_text import speech_paragraphs
  self.assertEqual(speech_paragraphs('A state-of-the-art idea.\n\nAn independent test.'),['A state-of-the-art idea.','An independent test.'])

if __name__=='__main__':unittest.main()
