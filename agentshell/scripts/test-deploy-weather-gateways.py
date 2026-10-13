"""Isolated config/code rollback tests. Never uses real files, SSH or supervisors."""
import importlib.util,json,tempfile,unittest,os,hashlib,subprocess,sys
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('weather_deploy',Path(__file__).with_name('deploy-weather-gateways.py'))
deploy=importlib.util.module_from_spec(spec);spec.loader.exec_module(deploy)
class ConfigTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.app=Path(self.temp.name)/'app';(self.app/'private').mkdir(parents=True);self.backup=self.app/'state/backups/edge-20261013T153000Z';self.backup.mkdir(parents=True)
  self.cfg=self.app/'private/config.json';self.original=b'{"node_id":"mac-mini","secret_file":"/private/reference-only","preserve":{"nested":true}}\n';self.cfg.write_bytes(self.original);self.cfg.chmod(0o600)
  self.state={'mac':str(self.backup),'tuf':'/var/lib/agentshell/backups/edge-20261013T153000Z'}
  self.app_patch=patch.object(deploy,'APP',self.app);self.app_patch.start()
  self.remote_patch=patch.object(deploy,'config_remote',side_effect=RuntimeError('Real network blocked'));self.remote=self.remote_patch.start()
 def tearDown(self):self.remote_patch.stop();self.app_patch.stop();self.temp.cleanup()
 def prepare(self):
  self.remote.side_effect=None;self.remote.return_value={'before_sha256':'mock','candidate_sha256':'mock'}
  deploy.prepare_weather_configs(self.state);self.remote.side_effect=RuntimeError('Real network blocked')
 def test_apply_rollback_preserves_all_other_fields_and_exact_bytes(self):
  self.prepare();deploy.set_weather_config('mac','apply',self.state);data=json.loads(self.cfg.read_bytes());self.assertEqual(data['weather'],deploy.WEATHER);del data['weather'];self.assertEqual(data,json.loads(self.original));self.assertEqual(self.cfg.stat().st_mode&0o777,0o600)
  deploy.set_weather_config('mac','rollback',self.state);self.assertEqual(self.cfg.read_bytes(),self.original)
 def test_repeat_same_transition_is_idempotent(self):
  self.prepare()
  for _ in range(2):deploy.set_weather_config('mac','apply',self.state)
  for _ in range(2):deploy.set_weather_config('mac','rollback',self.state)
  self.assertEqual(self.cfg.read_bytes(),self.original)
 def test_external_edit_refused(self):
  self.prepare();foreign=b'{"node_id":"foreign"}';self.cfg.write_bytes(foreign)
  for op in ['apply','rollback']:
   with self.assertRaisesRegex(RuntimeError,'outside'):deploy.set_weather_config('mac',op,self.state)
   self.assertEqual(self.cfg.read_bytes(),foreign)
 def test_corrupt_candidate_refused_before_write(self):
  self.prepare();(self.backup/'config-weather.json').write_text('{}')
  with self.assertRaisesRegex(RuntimeError,'backup differs'):deploy.set_weather_config('mac','apply',self.state)
  self.assertEqual(self.cfg.read_bytes(),self.original)
 def test_failed_atomic_replace_preserves_original_and_cleans_temp(self):
  self.prepare()
  with patch.object(deploy.os,'replace',side_effect=OSError('Injected replace failure')):
   with self.assertRaises(OSError):deploy.set_weather_config('mac','apply',self.state)
  self.assertEqual(self.cfg.read_bytes(),self.original);self.assertFalse(list(self.cfg.parent.glob('.sagwa-weather-*')))
 def test_symlink_refused(self):
  self.prepare();self.cfg.unlink();target=self.cfg.parent/'target.json';target.write_bytes(self.original);self.cfg.symlink_to(target)
  with self.assertRaisesRegex(RuntimeError,'symlink'):deploy.set_weather_config('mac','apply',self.state)
  self.assertEqual(target.read_bytes(),self.original)
 def test_unknown_operation_refused(self):
  self.prepare()
  with self.assertRaisesRegex(RuntimeError,'operation'):deploy.set_weather_config('mac','typo',self.state)
 def test_private_backups_and_restoration_hashes(self):
  self.prepare();before=self.backup/'config-before.json';self.assertEqual(before.read_bytes(),self.original);self.assertEqual(before.stat().st_mode&0o777,0o600);self.assertEqual(hashlib.sha256(before.read_bytes()).hexdigest(),self.state['mac_config']['before_sha256'])
 def test_tuf_network_failure_cannot_write_local_config(self):
  self.prepare()
  with self.assertRaisesRegex(RuntimeError,'blocked'):deploy.set_weather_config('tuf','apply',self.state)
  self.assertEqual(self.cfg.read_bytes(),self.original)
 def test_import_is_passive(self):
  self.assertEqual(self.cfg.read_bytes(),self.original);self.remote.assert_not_called()
 def remote_fixture(self,op,expected=None):
  # Execute the production remote config body with only its two absolute path
  # literals redirected to this temporary fixture. No SSH, services or keys.
  body=deploy.CONFIG_REMOTE.replace("'/opt/agentshell/private/config.json'",repr(str(self.cfg))).replace("'/var/lib/agentshell/backups'",repr(str(self.backup.parent)))
  result=subprocess.run([sys.executable,'-c',body],input=json.dumps([op,str(self.backup),deploy.WEATHER,expected]),text=True,capture_output=True)
  return result
 def test_remote_body_exact_roundtrip_with_fixture_paths(self):
  result=self.remote_fixture('prepare');self.assertEqual(result.returncode,0,result.stderr);expected=json.loads(result.stdout)
  result=self.remote_fixture('apply',expected);self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(self.cfg.read_bytes())['weather'],deploy.WEATHER)
  result=self.remote_fixture('rollback',expected);self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(self.cfg.read_bytes(),self.original)
 def test_remote_body_refuses_foreign_config(self):
  result=self.remote_fixture('prepare');self.assertEqual(result.returncode,0,result.stderr);expected=json.loads(result.stdout)
  foreign=b'{"node_id":"other"}';self.cfg.write_bytes(foreign);result=self.remote_fixture('apply',expected);self.assertNotEqual(result.returncode,0);self.assertEqual(self.cfg.read_bytes(),foreign)
if __name__=='__main__':unittest.main(verbosity=2)
