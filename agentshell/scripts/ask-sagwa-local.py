"""Text-only local model probe. No tools, provider fallback or device actions."""
import argparse
import json
import sys
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('--text', help='Prefer stdin for private prompts.')
args = parser.parse_args()
text = args.text if args.text is not None else sys.stdin.read(8193)
if not text.strip() or len(text) > 8192:
    raise SystemExit('invalid_text')
model = 'docker.io/ai/qwen3:4b-instruct-2507-q4_K_M'
payload = {'model': model, 'messages': [
    {'role': 'system', 'content': 'Te llamas Sagwa. Eres una mascota virtual, amable y concisa. Responde en español con cinco a diez palabras. No tienes acceso a equipos ni herramientas. No afirmes haber realizado acciones.'},
    {'role': 'user', 'content': text}], 'max_tokens': 128,
    'temperature': 0.2, 'stream': False}
request = urllib.request.Request(
    'http://127.0.0.1:12434/engines/llama.cpp/v1/chat/completions',
    json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
# Do not send local prompts through an environment-configured HTTP proxy.
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(request, timeout=30) as response:
    body = response.read(131073)
    if len(body) > 131072:
        raise SystemExit('response_too_large')
    data = json.loads(body)
    result = data['choices'][0]['message'].get('content')
    if not isinstance(result, str) or not result.strip():
        raise SystemExit('empty_model_response')
    print(result)
