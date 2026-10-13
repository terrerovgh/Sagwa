"""Package PPM output from the production LVGL renderer; no UI redrawing."""
import datetime
import hashlib
import html
import json
import argparse
from pathlib import Path
from PIL import Image

workspace = Path(__file__).resolve().parents[4]
edge = workspace / 'agentshell/edge-firmware'
gallery = workspace / 'agentshell/evidence/sagwa-v2/edge-ui-gallery'
labels = ['Principal', 'Menú', 'Herramientas', 'Preferencias', 'Modos', 'Agentes',
          'Destinos', 'Tarea reciente', 'Sensores', 'Voz', 'Mascota', 'Enrutamiento',
          'Lectura ampliada', 'Cancelar', 'Autorizar', 'Cámara', 'Plugin de notas',
          'Enfoque', 'Telemetría', 'Noche', 'Centinela', 'Terminal', 'Multimedia',
          'Asistente', 'Entorno', 'Recuperación', 'Enfoque · listo', 'Enfoque · activo', 'Enfoque · pausa', 'Enfoque · terminado']
names = ['home', 'menu', 'tools', 'settings', 'skins', 'agents', 'destinations',
         'tasks', 'sensors', 'voice', 'pet-settings', 'routing', 'reading', 'cancel',
         'approval', 'camera-preview', 'plugin-notes', 'mode-focus', 'mode-telemetry',
         'mode-night', 'mode-sentinel', 'mode-terminal', 'mode-multimedia',
         'mode-assistant', 'mode-weather', 'mode-recovery', 'focus-ready', 'focus-running', 'focus-paused', 'focus-completed']
parser = argparse.ArgumentParser()
parser.add_argument('--render-log', default='ui-host-render.log')
parser.add_argument('--output', type=Path, default=gallery)
args = parser.parse_args()
gallery = args.output.resolve()
labels.append('Historial local')
names.append('local-history')
labels += ['Clima · pronóstico vigente', 'Clima · dato vencido']
names += ['mode-weather-current', 'mode-weather-stale']
render_log = edge / args.render_log
if 'PASS: 33 LVGL screens and 21 actual LVGL pointer gestures' not in render_log.read_text():
    raise SystemExit('Render/gesture test has not passed')
items = []
for name, label in zip(names, labels):
    ppm = gallery / (name + '.ppm')
    png = gallery / (name + '.png')
    with Image.open(ppm) as image:
        assert image.size == (320, 240)
        image.save(png)
    items.append(dict(name=name, label=label, file=png.name,
                      sha256=hashlib.sha256(png.read_bytes()).hexdigest(), size=png.stat().st_size))
sources = ['components/sagwa_edge/graphics.cpp', 'components/sagwa_edge/core.cpp',
           'components/sagwa_edge/rig_assets.c', 'components/sagwa_edge/fonts/inter16.c',
           'components/sagwa_edge/include/diagnostics.hpp',
           'components/sagwa_edge/include/weather.hpp',
           'tests/ui-host/host.cpp', 'tests/ui-host/lv_conf.h']
manifest = dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                renderer='Production graphics.cpp + LVGL 9.4 RGB565 software rendering',
                size=[320, 240], hardware_verified=False,
                fixtures=['synthetic sensors, host availability, approval and response text',
                          'generated checkerboard camera image; no real photo',
                          'simulated ticks/pointer gestures; no ESP32, SPI/DMA or audio measurement'],
                gesture_tests=21, focus_flow_tested=True, approval_flow_tested=True,
                local_history_privacy_tested=True,
                render_log_sha256=hashlib.sha256(render_log.read_bytes()).hexdigest(),
                sources={s:hashlib.sha256((edge/s).read_bytes()).hexdigest() for s in sources}, screens=items)
(gallery / 'gallery.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
cards = ''.join('<figure><button data-index="'+str(i)+'"><img src="'+item['file']+'" alt="'+html.escape(item['label'])+'"></button><figcaption>'+html.escape(item['label'])+'</figcaption></figure>' for i,item in enumerate(items))
options = ''.join('<option value="'+str(i)+'">'+html.escape(item['label'])+'</option>' for i,item in enumerate(items))
page = '''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Sagwa · vistas LVGL</title>
<style>:root{color-scheme:dark;font:16px system-ui;background:#000;color:#fff}body{max-width:1080px;margin:auto;padding:24px}h1{font-size:24px;font-weight:600}p{max-width:760px;line-height:1.5;color:#c4c4c4}a{color:#fff}button,select{background:#000;color:#fff;border:1px solid #454545;border-radius:12px;min-height:44px;padding:8px 16px;font:inherit}button{cursor:pointer}nav{display:flex;gap:12px;justify-content:center;margin:16px 0}#large{display:block;width:min(100%,640px);height:auto;margin:auto}#caption{text-align:center;color:#fff}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:24px;margin-top:40px}figure{margin:0}figure button{border:0;padding:0;display:block;width:100%}figure img{display:block;width:100%;height:auto}figcaption{padding:12px 0;color:#ccc}button:focus-visible,select:focus-visible{outline:2px solid #fff;outline-offset:4px}</style>
<h1>Sagwa · vistas del firmware</h1><p>Estas 30 pantallas proceden del renderizador LVGL real del candidato 0.3.0. Los textos, sensores, disponibilidad y foto son datos de prueba. Esta vista permite revisar el diseño; todavía no confirma rendimiento, audio ni funcionamiento físico del CoreS3.</p><nav><button id="prev" aria-label="Anterior">‹</button><select id="choice" aria-label="Pantalla">''' + options + '''</select><button id="next" aria-label="Siguiente">›</button></nav><img id="large" src="home.png" alt="Principal"><p id="caption">Principal · 320 × 240</p><p><a href="gallery.json">Manifiesto y hashes</a> · Gestos simulados en LVGL: 17 pruebas aprobadas. En el dispositivo: borde izquierdo abre menú o vuelve; derecho abre herramientas; superior abre preferencias; tocar el texto abre lectura; acariciar a Sagwa no activa el micrófono.</p><div class="grid">''' + cards + '''</div><script>const screens=''' + json.dumps(items,ensure_ascii=False) + ''';let selected=0;const choice=document.querySelector('#choice'),large=document.querySelector('#large');function show(i){selected=(i+screens.length)%screens.length;const s=screens[selected];choice.value=selected;large.src=s.file;large.alt=s.label;document.querySelector('#caption').textContent=s.label+' · 320 × 240';}choice.onchange=()=>show(Number(choice.value));document.querySelector('#prev').onclick=()=>show(selected-1);document.querySelector('#next').onclick=()=>show(selected+1);document.querySelectorAll('[data-index]').forEach(b=>b.onclick=()=>{show(Number(b.dataset.index));large.scrollIntoView({behavior:'smooth',block:'center'});});document.addEventListener('keydown',e=>{if(e.target.tagName==='SELECT')return;if(e.key==='ArrowRight')show(selected+1);if(e.key==='ArrowLeft')show(selected-1);});</script></html>'''
(gallery / 'index.html').write_text(page.replace('30 pantallas', f'{len(items)} pantallas').replace('17 pruebas', '21 pruebas'))
print(f'Packaged {len(items)} real LVGL screens and a local gallery')
