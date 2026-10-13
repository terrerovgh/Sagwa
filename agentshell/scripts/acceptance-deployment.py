"""Exercise tests, immutable artifacts and health rollback on a loopback fixture."""
import datetime,json,subprocess,uuid
from pathlib import Path
from admin import request

root=Path(__file__).resolve().parents[1];task=str(uuid.uuid4());results={'task_id':task,'checks':{},'actions':[]};rules=[]
def action(operation,resource,params=None):
    raw={'action_id':str(uuid.uuid4()),'task_id':task,'operation':operation,'node':'lenlab','resource':resource,'params':params or {}}
    reply=request('/v1/actions','POST',raw);results['actions'].append({'action':raw,'reply':reply})
    result=reply.get('result',{});assert result.get('state')=='completed',reply;return result['data']
try:
    for resource,operations in [('acceptance-deploy-code',['git.worktree','git.commit','git.test','artifact.build']),('acceptance-deploy',['deploy.register','deploy.release'])]:
        rule={'rule_id':str(uuid.uuid4()),'node':'lenlab','resource':resource,'operations':operations,'enabled':True,'expires_at':(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(minutes=15)).isoformat().replace('+00:00','Z')}
        request('/v1/policy/rules','PUT',rule);rules.append(rule)
    results['checks']['baseline']=action('deploy.register','acceptance-deploy')
    tree=action('git.worktree','acceptance-deploy-code')['path']
    edit="from pathlib import Path; p=Path(%r)/'server.py'; p.write_text(p.read_text()+'\\n# Acceptance release verified through typed executor.\\n')" % tree
    subprocess.run(['ssh','terrerov@lenlab','sudo -n -u agentshell /usr/bin/python3 -'],input=edit.encode(),check=True,timeout=30)
    action('git.commit','acceptance-deploy-code',{'message':'Prepare healthy acceptance release'})
    tests=action('git.test','acceptance-deploy-code');assert tests['deployable'];results['checks']['tests']=tests
    artifact=action('artifact.build','acceptance-deploy-code');results['checks']['replicated_artifact']=artifact
    deployed=action('deploy.release','acceptance-deploy',{'artifact':artifact['artifact']});assert deployed['healthy'];results['checks']['healthy_deployment']=deployed
    edit="from pathlib import Path; p=Path(%r)/'Dockerfile'; p.write_text(p.read_text().replace('ENV HEALTHY=1','ENV HEALTHY=0'))" % tree
    subprocess.run(['ssh','terrerov@lenlab','sudo -n -u agentshell /usr/bin/python3 -'],input=edit.encode(),check=True,timeout=30)
    action('git.commit','acceptance-deploy-code',{'message':'Deliberately unhealthy image for rollback acceptance'})
    assert action('git.test','acceptance-deploy-code')['deployable']
    unhealthy=action('artifact.build','acceptance-deploy-code')
    rollback=action('deploy.release','acceptance-deploy',{'artifact':unhealthy['artifact']});assert rollback.get('rolled_back') and rollback.get('rollback_healthy');results['checks']['health_failure_rollback']=rollback
finally:
    for rule in rules:rule['enabled']=False;request('/v1/policy/rules','PUT',rule)
    (root/'evidence').mkdir(exist_ok=True);(root/'evidence/deployment.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,ensure_ascii=False,indent=2))
