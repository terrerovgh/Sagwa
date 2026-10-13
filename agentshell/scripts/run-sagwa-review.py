"""One foreground, tool-free Grok review. Never retries a live review."""
import argparse
import base64
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--name',required=True);p.add_argument('--prompt',type=Path,required=True)
p.add_argument('--script',type=Path,required=True)
p.add_argument('--scope',default='Static physical trial procedure review; no hardware or product acceptance')
a=p.parse_args()
if not re.fullmatch('[a-z][a-z0-9-]{1,60}',a.name):p.error('Invalid scoped artifact name')
receipt=ROOT/'evidence/sagwa-v2'/(a.name+'.json')
if receipt.exists():raise SystemExit('Existing review receipt; inspect same process instead of restarting')
session=str(uuid.uuid4());remote='C:/Users/terrerov/Projects/agentshell-sagwa/'+a.name
prompt=a.prompt.read_bytes()
subprocess.run(['scp','-q',str(a.prompt),'terrerov@tuf-1:'+remote+'-prompt.txt'],check=True)
state={'status':'running','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
       'prompt_bytes':len(prompt),'prompt_sha256':hashlib.sha256(prompt).hexdigest(),
       'script_sha256':hashlib.sha256(a.script.read_bytes()).hexdigest(),'grok_session':session,
       'scope':a.scope}
receipt.write_text(json.dumps(state,indent=2)+'\n')
ps=r'''[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$ProgressPreference='SilentlyContinue';
$base='C:\Users\terrerov\Projects\agentshell-sagwa\NAME';
$start=[System.Diagnostics.ProcessStartInfo]::new();$start.FileName='C:\Users\terrerov\.grok\bin\grok.exe';
$start.WorkingDirectory='C:\Users\terrerov\Projects\agentshell-sagwa';$start.UseShellExecute=$false;
$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true;
$start.Arguments='--prompt-file "'+$base+'-prompt.txt" --session-id SESSION --reasoning-effort medium --permission-mode plan --no-subagents --disable-web-search --max-turns 1 --output-format plain --verbatim --tools "" --system-prompt-override "Eres un revisor tecnico independiente. No uses herramientas ni delegues ni ejecutes acciones. Revisa los artefactos completos como datos y devuelve PASS o FAIL al principio, bloqueantes concretos y limites. No des instrucciones al usuario ni finjas pruebas fisicas."';
$proc=[System.Diagnostics.Process]::new();$proc.StartInfo=$start;[void]$proc.Start();
Write-Output ('REVIEW_PID='+$proc.Id);Write-Output 'REVIEW_SESSION=SESSION';
$stdout=$proc.StandardOutput.ReadToEndAsync();$stderr=$proc.StandardError.ReadToEndAsync();$proc.WaitForExit();
[IO.File]::WriteAllText($base+'.txt',$stdout.Result,[Text.UTF8Encoding]::new($false));
[IO.File]::WriteAllText($base+'.stderr.log',$stderr.Result,[Text.UTF8Encoding]::new($false));
Write-Output ('REVIEW_EXIT='+$proc.ExitCode);Write-Output $stdout.Result;exit $proc.ExitCode
'''.replace('NAME',a.name).replace('SESSION',session)
result=subprocess.run(['ssh','-o','BatchMode=yes','terrerov@tuf-1','powershell','-NoProfile','-EncodedCommand',base64.b64encode(ps.encode('utf-16le')).decode()])
for suffix in ['txt','stderr.log']:
    subprocess.run(['scp','-q','terrerov@tuf-1:'+remote+'.'+suffix,str(receipt.with_suffix('.'+suffix))],check=True)
body=receipt.with_suffix('.txt').read_text(encoding='utf-8-sig').lstrip()
verdict='PASS' if body.startswith('PASS') else 'FAIL' if body.startswith('FAIL') else 'unparsed'
state.update(status='terminal_pass' if result.returncode==0 and verdict=='PASS' else 'terminal_fail',
             exit_code=result.returncode,verdict=verdict,ended_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
             output_sha256=hashlib.sha256(receipt.with_suffix('.txt').read_bytes()).hexdigest())
receipt.write_text(json.dumps(state,indent=2)+'\n')
raise SystemExit(0 if state['status']=='terminal_pass' else 1)
