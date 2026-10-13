"""Build a complete local Noto index from downloaded Google and Unicode metadata."""
from pathlib import Path
import json,xml.etree.ElementTree as ET,hashlib
root=Path(__file__).resolve().parents[1];p=root/'assets/noto/catalog'
raw=(p/'emojis_data.js').read_text();data=json.loads(raw.split('=',1)[1].strip().rstrip(';'))
def key(s):return s.replace('\ufe0f','').replace('\ufe0e','')
annotations={}
for lang in ['es','en']:
 for suffix in ['', '-derived']:
  for node in ET.parse(p/(lang+suffix+'.xml')).iter('annotation'):
   cp=key(node.attrib['cp']);value=(node.text or '').strip();a=annotations.setdefault(cp,{}).setdefault(lang,{})
   if node.attrib.get('type')=='tts':a['name']=value
   else:a['keywords']=value.split(' | ')
# Domain vocabulary supplements the full multilingual catalog; it is not a shortlist.
aliases={'1f4bb':['programar','programacion','codigo','software','Codex','OpenCode'],
 '1f433':['Docker','contenedores'], '1f916':['agente','inteligencia artificial','Hermes','Muse'],
 '2699':['infraestructura','configuracion','servicio','servidor'], '1f4e1':['Tailscale','red','internet','conexion'],
 '1f512':['credencial','clave','certificado','seguridad'], '1f9ea':['pruebas','tests'], '1f4be':['copia de seguridad','backup'],
 '1f680':['desplegar','deployment','publicar'], '1f50b':['bateria','energia'], '1f91d':['delegar','colaborar','equipo'],
 '1f3e0':['casa','hogar'], '1f375':['te','té','infusion'], '1fad6':['tetera','preparar te','preparar té']}
out=[]
for item in data:
 code=item['rgi'];a=annotations.get(key(item['char']),{});es=a.get('es',{});en=a.get('en',{})
 renderable=code not in ['0023','002a','20e3','fe82b'] and not (len(code)==5 and 0x1f1e6<=int(code,16)<=0x1f1ff)
 asset_id=code
 if code.startswith('1f471_200d_2640_1f3'):asset_id='1f471_'+code.split('_')[-1]+'_200d_2640'
 out.append({'renderable':renderable,'asset_id':asset_id,'id':code,'char':item['char'],'name':es.get('name') or item.get('cldrName') or item['name'],'english':en.get('name') or item.get('cldrName') or item['name'],'keywords':es.get('keywords',[])+en.get('keywords',[])+aliases.get(code,[]),'category':item['category'],'animated':bool(item.get('hasGfontsAnim'))})
(root/'assets/noto/catalog.json').write_text(json.dumps(out,ensure_ascii=False,separators=(',',':'))+'\n')
(p/'sources.json').write_text(json.dumps({'google_catalog_url':'https://googlefonts.github.io/noto-emoji-files/data/emojis_data.js','google_catalog_sha256':hashlib.sha256((p/'emojis_data.js').read_bytes()).hexdigest(),'cldr_version':'release-48','cldr_base':'https://raw.githubusercontent.com/unicode-org/cldr/release-48/common/','count':len(out),'animated':sum(x['animated'] for x in out),'files':{x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in p.glob('*.xml')}},indent=2)+'\n')
print(json.dumps({'catalog':len(out),'spanish_names':sum(bool(annotations.get(key(x['char']),{}).get('es',{}).get('name')) for x in out)}))
