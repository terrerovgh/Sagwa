"""Fetch immutable Hugging Face revisions, then record all model hashes."""
import hashlib,json,sys,urllib.request
from pathlib import Path
from huggingface_hub import snapshot_download,hf_hub_download
root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
def revision(repo):
    with urllib.request.urlopen('https://huggingface.co/api/models/'+repo,timeout=20) as r: return json.load(r)['sha']
lock=root/'models.lock.json'
if lock.exists(): pins=json.loads(lock.read_text())['revisions']
else: pins={r:revision(r) for r in ['Systran/faster-whisper-base','rhasspy/piper-voices']}
snapshot_download('Systran/faster-whisper-base',revision=pins['Systran/faster-whisper-base'],local_dir=root/'whisper-base',allow_patterns=['model.bin','config.json','tokenizer.json','vocabulary.json','vocabulary.txt','preprocessor_config.json'])
for suffix in ['onnx','onnx.json']:
    source=hf_hub_download('rhasspy/piper-voices',filename='es/es_MX/ald/medium/es_MX-ald-medium.'+suffix,revision=pins['rhasspy/piper-voices'])
    (root/('es_MX-ald-medium.'+suffix)).write_bytes(Path(source).read_bytes())
hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and '.cache' not in p.parts and p!=lock}
lock.write_text(json.dumps({'revisions':pins,'sha256':hashes},indent=2)+'\n');print('Models downloaded and hashed:',len(hashes))
