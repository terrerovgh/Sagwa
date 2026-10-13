"""Host-owned executor for the single disposable acceptance container."""
import re,subprocess,sys
name='agentshell-acceptance'
artifact=sys.argv[1]
if not re.fullmatch(r'sha256:[a-f0-9]{64}',artifact):raise SystemExit('invalid_artifact')
def run(args):return subprocess.run(['docker',*args],check=True,capture_output=True,text=True)
run(['image','inspect',artifact])
prior=subprocess.run(['docker','inspect','--format','{{index .Config.Labels "agentshell.fixture"}}',name],capture_output=True,text=True)
if prior.returncode==0:
    if prior.stdout.strip()!='deployment-acceptance':raise SystemExit('unmanaged_container')
    run(['rm','-f',name])
run(['run','-d','--name',name,'--label','agentshell.fixture=deployment-acceptance','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=32','--memory=64m','--cpus=0.5','--publish','127.0.0.1:9460:8080',artifact])
print('Isolated acceptance container replaced.')
