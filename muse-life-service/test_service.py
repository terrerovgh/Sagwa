import io
import json
import os
import unittest
from unittest.mock import patch
from PIL import Image
import app

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.client=app.app.test_client()
        self.headers={'Authorization':'Bearer '+app.TOKEN}
        app.cache.clear()
        app.cancelled_before.clear()
    def test_authentication(self):
        self.assertEqual(self.client.post('/tts',json={'text':'hola'}).status_code,401)
        self.assertEqual(self.client.get('/health').status_code,200)
    def test_cache_and_stale(self):
        app.remember('test',1,lambda:{'x':1})
        self.assertEqual(app.remember('test',1,lambda:None)['x'],1)
        stamp,value=app.cache['test']; app.cache['test']=(stamp-10,value)
        def broken(): raise ValueError()
        self.assertTrue(app.remember('test',1,broken)['stale'])
    def test_weather_scenes(self):
        for code,day,scene in [(0,1,'sun'),(0,0,'night'),(61,1,'rain'),(73,1,'snow'),(3,1,'cloud')]:
            app.cache.clear()
            with patch.object(app,'location',return_value={'latitude':1,'longitude':1,'city':'Test','approximate':True}), patch.object(app,'get_json',return_value={'current':{'weather_code':code,'is_day':day,'temperature_2m':24,'wind_speed_10m':5},'current_units':{}}):
                self.assertEqual(app.weather()['scene'],scene)
    def test_news_fallback_and_photo(self):
        result=app.news({})
        self.assertFalse(result['image_available'])
        im=Image.new('RGB',(640,480),'blue');raw=io.BytesIO();im.save(raw,format='JPEG')
        with patch.object(app,'download',return_value=(raw.getvalue(),'image/jpeg','https://example.com/photo')):
            result=app.news({'image_url':'https://example.com/photo','reference':True})
            self.assertTrue(result['reference'])
            path=app.CACHE/result['image_url'].rsplit('/',1)[1]
            with Image.open(path) as picture:self.assertEqual(picture.size,(320,240))
    def test_ascii_and_speech_filter(self):
        text='Hola mundo.\n```\n / | \\ \n```\n[Una noticia](https://example.com)'
        self.assertEqual(app.spoken(text),'Hola mundo.\nUna noticia')
        self.assertEqual(app.context({'topic':'astronomia','ascii':' * --o-- *'})['ascii'],' * --o-- *')
    def test_private_urls_rejected(self):
        for url in ['http://127.0.0.1/a','http://192.168.4.34/a','file:///etc/passwd']:
            with self.assertRaises(ValueError): app.public_url(url)
    def test_camera_sizes(self):
        self.assertEqual(self.client.post('/camera',data=b'bad',headers=self.headers).status_code,400)
        result=self.client.post('/camera',data=b'\x00\xf8'*(320*240),headers=self.headers)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['format'],'jpeg-base64')
    def test_cancel_and_device_reboot(self):
        self.client.post('/cancel',json={'generation':20,'session':'old'},headers=self.headers)
        result=self.client.post('/tts',json={'text':'Hola mundo','generation':19,'session':'old'},headers=self.headers)
        self.assertEqual(result.status_code,409)
        # A newly booted session begins at generation 1 independently.
        self.assertNotIn('new',app.cancelled_before)
    def test_text_limit(self):
        result=self.client.post('/tts',json={'text':'palabra '*5000},headers=self.headers)
        self.assertEqual(result.status_code,400)
    def test_bitcoin_chart(self):
        with patch.object(app,'get_json',side_effect=[{'error':[],'result':{'XXBTZUSD':{'c':['100']}}},{'error':[],'result':{'XXBTZUSD':[[int(app.time.time())-200,0,0,0,'90'],[int(app.time.time())-50,0,0,0,'100']],'last':1}}]):
            result=app.bitcoin();self.assertEqual(result['price'],100);self.assertEqual(len(result['ascii'].splitlines()),7)

if __name__=='__main__':unittest.main()
