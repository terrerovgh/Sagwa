"""Transport-independent tests; no Muse login, network or Bluetooth required."""
import tempfile,unittest,uuid
from pathlib import Path
from server import Bridge
from musegadget.identity import Identity

class BridgeTests(unittest.TestCase):
 def setUp(self):
  self.directory=tempfile.TemporaryDirectory();self.calls=[]
  class Client:
   def request(client,command,params):self.calls.append((command,params));return {'delegates':[]}
  self.bridge=Bridge(Identity('02:00:00:00:00:01'),Path(self.directory.name),Client())
  self.task=str(uuid.uuid4());self.bridge.runs[self.task]={'task_id':self.task,'status':'running'}
 def tearDown(self):self.directory.cleanup()
 def test_unknown_and_canceled_tasks_cannot_delegate_or_return_late_answers(self):
  for command in ('agentshell.agents.submit','agentshell.agents.list','agentshell.host.status','agentshell.task.complete'):
   self.assertFalse(self.bridge.invoke(command,{'task_id':str(uuid.uuid4())})['ok'])
  self.bridge.runs[self.task]['status']='canceled'
  for command in ('agentshell.agents.submit','agentshell.task.complete'):
   self.assertFalse(self.bridge.invoke(command,{'task_id':self.task,'text':'late'})['ok'])
  self.assertEqual(self.calls,[])
 def test_muse_receives_delegate_availability_and_completes_its_own_task(self):
  self.assertTrue(self.bridge.invoke('agentshell.agents.list',{'task_id':self.task})['ok'])
  self.assertEqual(self.calls[0][1]['task_id'],self.task)
  self.assertTrue(self.bridge.invoke('agentshell.task.complete',{'task_id':self.task,'text':'Resultado integrado por Muse.'})['ok'])
  self.assertEqual(self.bridge.runs[self.task]['status'],'completed')
  self.assertFalse(self.bridge.invoke('agentshell.agents.list',{'task_id':self.task})['ok'])

 def test_unknown_submission_is_reconciled_without_replacement_when_model_changes_uuid(self):
  calls=[];original=str(uuid.uuid4())
  class Client:
   def request(client,command,params):
    calls.append((command,params.copy()))
    if command=='agentshell.agents.submit':raise TimeoutError()
    return {'task_id':params['delegate_id'],'state':'completed','output':'OK'}
  self.bridge.delegates=Client()
  params={'task_id':self.task,'request_id':original,'agent':'codex','node':'mac-mini','target':'mac-mini','capability':'conversation','goal':'Prueba'}
  first=self.bridge.invoke('agentshell.agents.submit',params)
  self.assertTrue(first['ok']);self.assertEqual(first['payload']['state'],'submission_uncertain')
  canonical=first['payload']['task_id'];self.assertNotEqual(canonical,original)
  params['request_id']=str(uuid.uuid4());second=self.bridge.invoke('agentshell.agents.submit',params)
  self.assertEqual(second['payload']['task_id'],canonical);self.assertEqual([command for command,_ in calls],['agentshell.agents.submit','agentshell.agents.status'])
  self.bridge.invoke('agentshell.agents.submit',params);self.assertEqual(len(calls),2)

 def test_one_uuid_cannot_change_a_delegate_target_and_missing_parameters_are_rejected(self):
  params={'task_id':self.task,'request_id':str(uuid.uuid4()),'agent':'codex','node':'mac-mini','target':'mac-mini','capability':'conversation','goal':'Prueba'}
  self.assertTrue(self.bridge.invoke('agentshell.agents.submit',params)['ok'])
  params['target']='tuf-infra';self.assertEqual(self.bridge.invoke('agentshell.agents.submit',params)['error'],'changed_request')
  self.assertEqual(len(self.calls),1)
  self.assertEqual(self.bridge.invoke('agentshell.agents.submit',{'task_id':self.task})['error'],'invalid_request')

 def test_model_reusing_a_uuid_in_a_new_parent_does_not_collide_with_an_old_child(self):
  params={'task_id':self.task,'request_id':str(uuid.uuid4()),'agent':'codex','node':'mac-mini','target':'mac-mini','capability':'conversation','goal':'Prueba'}
  self.bridge.invoke('agentshell.agents.submit',params)
  other=str(uuid.uuid4());self.bridge.runs[other]={'task_id':other,'status':'running'}
  params['task_id']=other;self.bridge.invoke('agentshell.agents.submit',params)
  self.assertNotEqual(self.calls[0][1]['request_id'],self.calls[1][1]['request_id'])


if __name__=='__main__':unittest.main()
