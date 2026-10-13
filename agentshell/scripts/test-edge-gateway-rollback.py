"""Failure injection against real installer functions; no live service changes."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('edge_deploy', Path(__file__).with_name('deploy-edge-gateways.py'))
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def archive(folder, path):
    with tarfile.open(path, 'w:gz') as tar:
        tar.add(folder, arcname='dist')


class RollbackRetry(unittest.TestCase):
    def test_mac_restored_then_remote_failure_is_retryable(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / 'app'; (app / 'dist').mkdir(parents=True)
            (app / 'dist/main.js').write_text('candidate')
            old = Path(temp) / 'old'; old.mkdir(); (old / 'main.js').write_text('baseline')
            backup = app / 'state/backups/edge-20261013T000000Z'; backup.mkdir(parents=True)
            archive(old, backup / 'dist-before.tar.gz')
            state = dict(stamp='20261013T000000Z',mac=str(backup),previous_mac_files=deploy.hashes(old))
            path = backup / 'deployment.json'; path.write_text(json.dumps(state))
            calls = []
            def remote(op, state):
                calls.append(op)
                if len(calls) == 1:
                    raise ConnectionError('Injected SSH failure after Mac restore')
                return {'code_hashes_equal':True}
            with patch.object(deploy, 'APP', app), patch.object(deploy, 'restart_mac'), \
                    patch.object(deploy, 'remote', remote), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(ConnectionError):deploy.install('rollback',path)
                self.assertEqual(deploy.hashes(app/'dist'),deploy.hashes(old))
                retained = list(app.glob('dist-retained-*')); self.assertEqual(len(retained),1)
                deploy.install('rollback',path)
                self.assertEqual(calls,['rollback','rollback'])
                self.assertEqual(list(app.glob('dist-retained-*')),retained)
                self.assertEqual((retained[0]/'main.js').read_text(),'candidate')

    def test_tuf_source_restored_but_restart_failure_can_be_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);base=root/'app';(base/'dist').mkdir(parents=True)
            (base/'dist/main.js').write_text('candidate')
            old=root/'old';old.mkdir();(old/'main.js').write_text('baseline')
            backups=root/'backups';backup=backups/'edge-20261013T000000Z';backup.mkdir(parents=True)
            archive(old,backup/'dist-before.tar.gz')
            (backup/'dist-before.sha.json').write_text(json.dumps(deploy.hashes(old)))
            state=dict(tuf=str(backup),stamp='20261013T000000Z')
            code=deploy.REMOTE.replace("'/opt/agentshell/app'",repr(str(base))).replace("'/var/lib/agentshell/backups'",repr(str(backups)))
            attempts=[]
            def restart(*args,**kwargs):
                attempts.append(args[0])
                if len(attempts)==1:raise subprocess.CalledProcessError(1,args[0])
                return subprocess.CompletedProcess(args[0],0)
            with patch('os.chown'),patch('subprocess.run',restart),contextlib.redirect_stdout(io.StringIO()):
                with patch('sys.stdin',io.StringIO(json.dumps(['rollback',state]))):
                    with self.assertRaises(subprocess.CalledProcessError):exec(code,{})
                self.assertEqual(deploy.hashes(base/'dist'),deploy.hashes(old))
                retained=list(base.glob('dist-retained-*'));self.assertEqual(len(retained),1)
                with patch('sys.stdin',io.StringIO(json.dumps(['rollback',state]))):exec(code,{})
                self.assertEqual(len(attempts),2)
                self.assertEqual(list(base.glob('dist-retained-*')),retained)

    def test_mac_restart_failure_does_not_skip_tuf_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            app=Path(temp)/'app';(app/'dist').mkdir(parents=True)
            (app/'dist/main.js').write_text('baseline')
            backup=app/'state/backups/edge-20261013T000000Z';backup.mkdir(parents=True)
            archive(app/'dist',backup/'dist-before.tar.gz')
            state=dict(stamp='20261013T000000Z',mac=str(backup),previous_mac_files=deploy.hashes(app/'dist'))
            path=backup/'deployment.json';path.write_text(json.dumps(state))
            with patch.object(deploy,'APP',app),patch.object(deploy,'restart_mac',side_effect=PermissionError()),patch.object(deploy,'remote',return_value={'code_hashes_equal':True}) as remote:
                with self.assertRaises(PermissionError):deploy.install('rollback',path)
                remote.assert_called_once_with('rollback',state)


if __name__=='__main__':unittest.main()
