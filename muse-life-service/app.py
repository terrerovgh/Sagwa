"""LAN companion for Muse: no SDK credential or conversation persistence."""
import base64
import hashlib
import hmac
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from flask import Flask, jsonify, request, send_file
from PIL import Image, ImageOps
import requests
from piper import PiperVoice
from waitress import serve

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
TOKEN = os.environ.get('MUSE_LIFE_TOKEN', '')
PUBLIC = os.environ.get('MUSE_PUBLIC_URL', 'http://192.168.4.64:8765').rstrip('/')
CACHE = Path(os.environ.get('MUSE_CACHE', '/cache'))
CACHE.mkdir(parents=True, exist_ok=True)
voice = None
voice_lock = threading.Lock()
cache_lock = threading.Lock()
cache = {}
cancelled_before = {}

@app.before_request
def authenticate():
    if request.path == '/health' or request.path.startswith('/assets/'):
        return None
    supplied = request.headers.get('Authorization', '')
    if not TOKEN or not hmac.compare_digest(supplied, 'Bearer ' + TOKEN):
        return jsonify(error='unauthorized'), 401

@app.errorhandler(Exception)
def failed(error):
    # No request bodies, credentials, or private upstream URLs in logs.
    app.logger.warning('request failed: %s', type(error).__name__)
    return jsonify(error='resource_unavailable', detail=str(error)[:160]), 503

@app.get('/health')
def health():
    return jsonify(ok=True, voice='es_MX-ald-medium', ready=voice is not None)

def remember(key, ttl, load):
    with cache_lock:
        old = cache.get(key)
        if old and time.time() - old[0] < ttl:
            return dict(old[1], age_s=round(time.time() - old[0], 1), stale=False)
    try:
        value = load()
        with cache_lock:
            cache[key] = (time.time(), value)
        return dict(value, age_s=0, stale=False)
    except Exception:
        if old:
            return dict(old[1], age_s=round(time.time() - old[0], 1), stale=True)
        raise

def get_json(url, **kwargs):
    response = requests.get(url, timeout=(5, 15), **kwargs)
    response.raise_for_status()
    return response.json()

def location(city=None):
    def load():
        saved = CACHE/'location.json'
        if not city and saved.exists() and time.time()-saved.stat().st_mtime < 86400:
            return json.loads(saved.read_text())
        if city:
            data = get_json('https://geocoding-api.open-meteo.com/v1/search', params={'name': city, 'count': 1, 'language': 'es'})
            matches = data.get('results', [])
            if not matches:
                raise ValueError('No se encontró el lugar; indica ciudad y país.')
            item = matches[0]
            return dict(latitude=item['latitude'], longitude=item['longitude'], city=item['name'], country=item.get('country'), approximate=False, source='Open-Meteo geocoding')
        item = get_json('https://ipwho.is/')
        if not item.get('success'):
            raise ValueError('Ubicación no disponible; pregunta la ciudad.')
        value = {**{k: item.get(k) for k in ('latitude', 'longitude', 'city', 'country')}, 'approximate': True, 'source': 'ipwho.is (IP pública de casa)'}
        saved.write_text(json.dumps(value))
        return value
    return remember(('location', city), 86400, load)

WEATHER = {
    'sun': ['     \\ | /', '   -- (o) --', '     / | \\'],
    'night': ['        .   *', '     . (    .', '        `--  *'],
    'cloud': ['      .--.', '   .-(    ).', '  (___.__)__)'],
    'rain': ['      .--.', '   .-(    ).', '  (___.__)__)', '    / / / /'],
    'snow': ['      .--.', '   .-(    ).', '  (___.__)__)', '    *  *  *'],
}

def weather(city=None):
    loc = location(city)
    def load():
        item = get_json('https://api.open-meteo.com/v1/forecast', params={'latitude': loc['latitude'], 'longitude': loc['longitude'], 'current': 'temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m', 'timezone': 'auto'})
        current = item['current']
        code = current['weather_code']
        scene = 'snow' if code in (71,73,75,77,85,86) else 'rain' if code >= 51 else 'cloud' if code in (2,3,45,48) else 'sun' if current['is_day'] else 'night'
        return dict(topic='weather', location=loc, current=current, units=item['current_units'], scene=scene, ascii='\n'.join(WEATHER[scene]), frames=['\n'.join(WEATHER[scene]), '\n'.join(WEATHER[scene]).replace('/ / / /',' / / / ').replace('*  *  *','  *  * ').replace('(o)','(O)')], title=f"{loc['city']} {'~IP' if loc['approximate'] else ''}"[:38], data=f"{current['temperature_2m']} C | {current['wind_speed_10m']} km/h\nOpen-Meteo {time.strftime('%H:%M UTC',time.gmtime())}", source='Open-Meteo', queried_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    return remember(('weather', loc['latitude'], loc['longitude']), 300, load)

def spark(values, width=36, height=7):
    values = [values[min(len(values)-1, int(i * len(values) / width))] for i in range(width)]
    lo, hi = min(values), max(values)
    ys = [round((v-lo) / (hi-lo or 1) * (height-1)) for v in values]
    return '\n'.join(''.join('*' if y == height-1-row else ' ' for y in ys) for row in range(height))

def bitcoin():
    def load():
        ticker = get_json('https://api.kraken.com/0/public/Ticker', params={'pair': 'XBTUSD'})
        ohlc = get_json('https://api.kraken.com/0/public/OHLC', params={'pair': 'XBTUSD', 'interval': 15, 'since': int(time.time())-86400})
        if ticker['error'] or ohlc['error']:
            raise ValueError('Kraken no disponible')
        t = next(iter(ticker['result'].values()))
        rows = next(v for k,v in ohlc['result'].items() if k != 'last')
        prices = [float(row[4]) for row in rows if int(row[0]) >= time.time()-86400]
        if not prices:
            raise ValueError('Kraken sin histórico')
        price = float(t['c'][0])
        change = (price / prices[0] - 1) * 100
        stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        return dict(topic='bitcoin', scene='bitcoin', title='BITCOIN | BTC/USD | 24 h', data=f"${price:,.2f}  {change:+.2f}%\nKraken {time.strftime('%H:%M UTC',time.gmtime())}", price=price, change_pct_24h=change, series=[{'time':row[0], 'price':float(row[4])} for row in rows], ascii=spark(prices), source='Kraken', queried_at=stamp)
    return remember('bitcoin', 60, load)

def public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,80,443):
        raise ValueError('URL pública http(s) requerida')
    if any(not ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme=='https' else 80))):
        raise ValueError('No se permiten direcciones internas')
    return url

def download(url, maximum=4*1024*1024):
    for _ in range(5):
        public_url(url)
        response = requests.get(url, timeout=(5,12), stream=True, allow_redirects=False, headers={'User-Agent': 'MuseCoreS3/1.0'})
        if response.is_redirect:
            url = urljoin(url, response.headers['Location'])
            response.close()
            continue
        response.raise_for_status()
        result = bytearray()
        for chunk in response.iter_content(16384):
            result.extend(chunk)
            if len(result) > maximum:
                response.close()
                raise ValueError('Recurso demasiado grande')
        mime = response.headers.get('Content-Type', '')
        response.close()
        return bytes(result), mime, url
    raise ValueError('Demasiadas redirecciones')

def asset(raw):
    Image.MAX_IMAGE_PIXELS = 20000000
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert('RGB')
    im = ImageOps.contain(im, (320,160))
    canvas = Image.new('RGB', (320,240), 'black')
    canvas.paste(im, ((320-im.width)//2, (160-im.height)//2+20))
    ident = secrets.token_hex(24)
    canvas.save(CACHE / (ident + '.jpg'), quality=82)
    # Capability URLs expire and never contain the shared authentication key.
    for file in CACHE.glob('*.jpg'):
        if time.time() - file.stat().st_mtime > 3600:
            file.unlink(missing_ok=True)
    return PUBLIC + '/assets/' + ident + '.jpg'

@app.get('/assets/<name>')
def assets(name):
    if not re.fullmatch(r'[a-f0-9]{48}\.jpg', name):
        return jsonify(error='not_found'), 404
    file = CACHE / name
    if not file.exists() or time.time() - file.stat().st_mtime > 3600:
        return jsonify(error='expired'), 404
    return send_file(file, mimetype='image/jpeg')

def news(params):
    image = params.get('image_url')
    thematic = bool(params.get('reference', False))
    article = params.get('article_url')
    if not image and article:
        try:
            raw, _, _ = download(article, 1024*1024)
            html = raw.decode('utf-8', errors='replace')
            from html.parser import HTMLParser
            class MetaParser(HTMLParser):
                found = None
                def handle_starttag(self, tag, attrs):
                    attrs = dict(attrs)
                    if tag == 'meta' and attrs.get('property', attrs.get('name')) in ('og:image', 'twitter:image'):
                        self.found = attrs.get('content')
            parser = MetaParser(); parser.feed(html)
            if parser.found:
                image = urljoin(article, parser.found)
        except Exception:
            pass
    result = dict(topic='news', scene='news', title='NOTICIA' if not thematic else 'IMAGEN DE REFERENCIA', source=article, queried_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    if image:
        try:
            raw, mime, _ = download(image)
            if not mime.startswith('image/'):
                raise ValueError('El recurso no es una imagen')
            result.update(image_url=asset(raw), reference=thematic, data='Referencia temática' if thematic else 'Imagen del artículo')
            return result
        except Exception:
            pass
    return dict(result, ascii='  .----------------.\n  |    NOTICIAS     |\n  | === ===  ===   |\n  | === ===  ===   |\n  `----------------\'', data='Sin imagen disponible', image_available=False)

def context(params):
    topic = str(params.get('topic', 'general')).lower()
    if topic in ('weather','tiempo','clima'):
        return weather(params.get('city'))
    if topic in ('bitcoin','btc'):
        return bitcoin()
    if topic in ('news','noticia','noticias'):
        return news(params)
    return dict(topic=topic, scene='general', title=str(params.get('title', topic))[:38], ascii=str(params.get('ascii', '     .------.\n     | o  o |\n     |  --  |\n     `------\''))[:1600], data='Muse')

@app.post('/context')
def get_context():
    return jsonify(context(request.get_json(force=True)))

@app.post('/scene')
def scene():
    params = request.get_json(force=True)
    text = (str(params.get('question','')) + ' ' + str(params.get('text',''))).lower()
    # Convenience only; Muse should call context.get before making factual claims.
    if re.search(r'bitcoin|\bbtc\b', text):
        return jsonify(bitcoin())
    if re.search(r'\b(clima|pronóstico|weather)\b|tiempo en', text):
        return jsonify(weather(params.get('city')))
    urls = re.findall(r'https?://[^\s)<>]+', str(params.get('text','')))
    if urls and re.search(r'noticia|news|artículo', text):
        return jsonify(news({'article_url':urls[0]}))
    return jsonify(scene='general', title='MUSE', data='')

@app.post('/camera')
def camera():
    width = int(request.args.get('width', 320))
    height = int(request.args.get('height', 240))
    raw = request.get_data()
    if width != 320 or height != 240 or len(raw) != width*height*2:
        return jsonify(error='invalid_rgb565_frame'), 400
    rgb = bytearray(width*height*3)
    for i in range(width*height):
        value = raw[2*i] | raw[2*i+1] << 8
        rgb[3*i:3*i+3] = bytes((((value>>11)&31)*255//31, ((value>>5)&63)*255//63, (value&31)*255//31))
    im = Image.frombytes('RGB',(width,height),bytes(rgb))
    output = io.BytesIO(); im.save(output, format='JPEG', quality=78)
    return jsonify(format='jpeg-base64', data_base64=base64.b64encode(output.getvalue()).decode())

def spoken(text):
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[*_#`]', '', text)
    # Do not pronounce standalone ASCII drawings.
    return '\n'.join(line for line in text.splitlines() if re.search(r'[A-Za-záéíóúñÁÉÍÓÚÑ]{3}', line)).strip()

@app.post('/cancel')
def cancel():
    global cancelled_before
    params=request.get_json(force=True)
    session=str(params.get('session','default'))[:64]
    if len(cancelled_before)>256: cancelled_before.clear()
    cancelled_before[session]=max(cancelled_before.get(session,0),int(params.get('generation',0)))
    return jsonify(ok=True)

@app.post('/tts')
def tts():
    global voice
    params = request.get_json(force=True)
    text = spoken(str(params.get('text','')))
    session=str(params.get('session','default'))[:64]
    generation=int(params.get('generation',cancelled_before.get(session,0)))
    if generation < cancelled_before.get(session,0):
        return jsonify(error='cancelled'),409
    if len(text) > 32768:
        return jsonify(error='text_too_long'), 400
    if not text:
        return jsonify(error='no_spoken_text'), 422
    with voice_lock:
        if generation < cancelled_before.get(session,0):
            return jsonify(error='cancelled'),409
        if voice is None:
            voice = PiperVoice.load('/voices/es_MX-ald-medium.onnx')
        with tempfile.TemporaryDirectory() as directory:
            wav = Path(directory)/'speech.wav'
            import wave
            with wave.open(str(wav), 'wb') as out:
                # Piper emits sentence chunks into the same WAV, bounding synthesis RAM.
                first=True
                for chunk in voice.synthesize(text):
                    if generation < cancelled_before.get(session,0):
                        return jsonify(error='cancelled'),409
                    if first:
                        out.setframerate(chunk.sample_rate); out.setsampwidth(chunk.sample_width); out.setnchannels(chunk.sample_channels); first=False
                    out.writeframes(chunk.audio_int16_bytes)
            mp3 = Path(directory)/'speech.mp3'
            subprocess.run(['ffmpeg','-v','error','-i',str(wav),'-ar','16000','-ac','1','-b:a','48k','-f','mp3',str(mp3)], check=True, timeout=180)
            result = mp3.read_bytes()
    return app.response_class(result, mimetype='audio/mpeg', headers={'Cache-Control':'no-store'})

if __name__ == '__main__':
    if not TOKEN:
        raise SystemExit('MUSE_LIFE_TOKEN required')
    voice = PiperVoice.load('/voices/es_MX-ald-medium.onnx')
    serve(app, host='0.0.0.0', port=8765, threads=4, channel_timeout=190)
