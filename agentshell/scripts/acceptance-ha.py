"""Exercise AgentShell-only outages, restoring every stopped service in finally."""
import datetime,json,subprocess,time,uuid,urllib.error,os,re,signal,argparse
from pathlib import Path
from admin import request

root=Path(__file__).resolve().parents[1]
tuf=['ssh','-J','terrerov@tuf-1','-p','2222','root@172.22.25.125']
parser=argparse.ArgumentParser();parser.add_argument('--abrupt',action='store_true');args=parser.parse_args()
results={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checks':{},'failure_mode':'paused_gateway_and_stopped_member' if args.abrupt else 'graceful_service_stop'}
mac_etcd_pid=None;gateway_paused=False
def pause_mac_etcd():
    for domain in ['system',f'gui/{os.getuid()}']:
        info=subprocess.run(['launchctl','print',domain+'/ai.agentshell.etcd'],capture_output=True,text=True)
        match=re.search(r'\n\s*pid = (\d+)',info.stdout)
        if info.returncode==0 and match:
            pid=int(match.group(1));owner=subprocess.check_output(['ps','-o','uid=','-p',str(pid)],text=True).strip()
            if owner!=str(os.getuid()):raise RuntimeError('Unexpected etcd owner')
            os.kill(pid,signal.SIGSTOP);return pid
    raise RuntimeError('etcd PID unavailable')
def remote(command):subprocess.run(tuf+[command],check=True,timeout=30,stdout=subprocess.DEVNULL)
def wait(predicate,seconds=65):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            value=predicate()
            if value:return value
        except (OSError,urllib.error.URLError):pass
        time.sleep(2)
    raise RuntimeError('acceptance_timeout')
def leader(node):
    state=request('/v1/state');return state['authority'] if (state.get('authority') or {}).get('node')==node and state['authority']['epoch']!='pending' else None
def telemetry(gateway):
    rows=request('/v1/devices')
    return next((v for v in rows.values() if v.get('gateway')==gateway and time.time()-datetime.datetime.fromisoformat(v['received_at'].replace('Z','+00:00')).timestamp()<15),None)
try:
    if not leader('tuf-infra'):request('/v1/control/handoff','POST',{'target':'tuf-infra'})
    primary=wait(lambda:leader('tuf-infra'))
    failed_at=time.monotonic()
    if args.abrupt:
        remote('docker pause agentshell-gateway');gateway_paused=True
        remote('systemctl stop agentshell-etcd')
    else:remote('systemctl stop agentshell-gateway agentshell-etcd')
    device=wait(lambda:telemetry('mac-mini'),65 if args.abrupt else 30)
    print(json.dumps({'gateway_failover':device['gateway']}),flush=True)
    secondary=wait(lambda:leader('lenlab'))
    results['checks']['promotion_after_s']=round(time.monotonic()-failed_at,2)
    if args.abrupt:assert results['checks']['promotion_after_s']>=30,'lease_not_observed'
    results['checks']['single_member_loss']={'primary':primary,'recovery':secondary,'device_gateway':device['gateway']}
    action={'action_id':str(uuid.uuid4()),'task_id':str(uuid.uuid4()),'operation':'host.status','node':'lenlab','resource':'','params':{}}
    read=request('/v1/actions','POST',action)
    assert read['result']['state']=='completed'
    results['checks']['recovery_executor_read']=read
    try:
        request('/internal/actions','POST',{'action':{**action,'node':'mac-mini','action_id':str(uuid.uuid4())},'authority':primary})
        raise AssertionError('stale_epoch_accepted')
    except urllib.error.HTTPError as e:
        reply=json.load(e);assert reply['error']=='stale_epoch';results['checks']['old_epoch_rejected']=reply
    remote('systemctl start agentshell-etcd')
    if gateway_paused:remote('docker unpause agentshell-gateway');gateway_paused=False
    else:remote('systemctl start agentshell-gateway')
    wait(lambda:telemetry('tuf-infra'),45)
    assert leader('lenlab')
    results['checks']['tuf_returns_standby']=True
    remote('systemctl stop agentshell-etcd')
    mac_etcd_pid=pause_mac_etcd()
    mutation={**action,'node':'mac-mini','operation':'git.worktree','resource':'acceptance-code','action_id':str(uuid.uuid4())}
    try:
        request('/internal/actions','POST',{'action':mutation,'authority':secondary})
        raise AssertionError('mutation_accepted_without_quorum')
    except urllib.error.HTTPError as e:
        reply=json.load(e);assert reply['error'] in ['quorum_unavailable','leader_unavailable'];results['checks']['quorum_loss_rejects_mutation']=reply
    assert not (Path.home()/'Library/Application Support/AgentShell/state/actions'/(mutation['action_id']+'.json')).exists()
    results['checks']['quorum_loss_did_not_start_action']=True
finally:
    if mac_etcd_pid:os.kill(mac_etcd_pid,signal.SIGCONT)
    if gateway_paused:remote('docker unpause agentshell-gateway')
    remote('systemctl start agentshell-etcd agentshell-gateway')
    results['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    out=root/'evidence';out.mkdir(exist_ok=True);(out/('ha-abrupt.json' if args.abrupt else 'ha.json')).write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,ensure_ascii=False,indent=2))
