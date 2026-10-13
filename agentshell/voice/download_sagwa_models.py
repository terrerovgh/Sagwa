"""Download pinned official voice assets without inference or credential logging."""
import argparse,shutil
from pathlib import Path
from huggingface_hub import snapshot_download,hf_hub_download
SPACE_REV='0d2648c4c1637eccfa8d45c7e192a0ad8d5b1fca'
REVISIONS={'hexgrad/Kokoro-82M':'f3ff3571791e39611d31c381e3a41a3af07b4987','ResembleAI/Chatterbox-Multilingual-es-mx-latam':'27e595bf2fe7be0533ca299d9afafcde08b7cca7','ResembleAI/chatterbox':'5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18'}
p=argparse.ArgumentParser();p.add_argument('engine',choices=['kokoro','chatterbox']);p.add_argument('directory',type=Path);args=p.parse_args();args.directory.mkdir(parents=True,exist_ok=True)
if args.engine=='kokoro':
    for filename in ['config.json','kokoro-v1_0.pth','voices/ef_dora.pt']:
        path=hf_hub_download('hexgrad/Kokoro-82M',filename,revision=REVISIONS['hexgrad/Kokoro-82M']);shutil.copyfile(path,args.directory/Path(filename).name)
else:
    snapshot_download('ResembleAI/Chatterbox-Multilingual-TTS-es-mx-latam',repo_type='space',revision=SPACE_REV,allow_patterns=['chatterbox/**'],local_dir=args.directory.parent/'chatterbox-code')
    for repo,filename in [('ResembleAI/chatterbox','ve.pt'),('ResembleAI/chatterbox','conds.pt'),('ResembleAI/Chatterbox-Multilingual-es-mx-latam','grapheme_mtl_merged_expanded_v1.json'),('ResembleAI/Chatterbox-Multilingual-es-mx-latam','t3_es_mx_latam.safetensors'),('ResembleAI/Chatterbox-Multilingual-es-mx-latam','s3gen_v3.pt')]:
        path=hf_hub_download(repo,filename,revision=REVISIONS[repo]);shutil.copyfile(path,args.directory/filename)
print('Downloaded official '+args.engine+' assets')
