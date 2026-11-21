import io,unittest,threading,tempfile,sys,time
from pathlib import Path
import enhancement
from unittest.mock import patch
import app
class EnhancementRoutes(unittest.TestCase):
 def setUp(self):self.client=app.app.test_client()
 def test_interface_and_status(self):
  response=self.client.get('/');self.assertEqual(response.status_code,200)
  self.assertIn(b'Compare the three enhancers',response.data)
  result=self.client.get('/api/enhancers').get_json()
  self.assertEqual({m['id'] for m in result['enhancers']},{'deepfilternet','resemble','clearvoice','clearvoice_sr'})
 def test_invalid_source_and_provider(self):
  self.assertEqual(self.client.post('/api/enhance',json={}).status_code,400)
  self.assertEqual(self.client.post('/api/enhance',json={'path':__file__,'providers':['unknown']}).status_code,400)
  self.assertEqual(self.client.post('/api/enhance',json={'path':__file__,'providers':['deepfilternet'],'strength':'nan'}).status_code,400)
 def test_upload_compare_forwards_every_provider(self):
  with patch('app.enhancement.start',return_value='test-job') as run:
   response=self.client.post('/api/enhance',data={'file':(io.BytesIO(b'RIFFtest'),'voice.wav'),'providers':['deepfilternet','resemble','clearvoice'],'strength':'.5','normalize':'0'})
   self.assertEqual(response.status_code,202)
   self.assertEqual(run.call_args.args[1],['deepfilternet','resemble','clearvoice'])
   self.assertEqual(run.call_args.kwargs['strength'],.5)
   self.assertFalse(run.call_args.kwargs['normalize'])
   run.call_args.args[0].unlink(missing_ok=True)
 def test_cancellation_stops_its_worker(self):
  event=threading.Event();timer=threading.Timer(.2,event.set);timer.start()
  with tempfile.TemporaryDirectory() as folder:
   before=time.monotonic()
   with self.assertRaises(enhancement.Cancelled):enhancement._run([sys.executable,'-c','import time;time.sleep(10)'],Path(folder)/'worker.log',event)
   self.assertLess(time.monotonic()-before,3)
  timer.join()
 def test_missing_job(self):self.assertEqual(self.client.get('/api/enhance/nonexistent').status_code,404)
if __name__=='__main__':unittest.main()
