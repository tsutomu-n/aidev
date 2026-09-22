"""Isolated context policy and recovery contracts; never invokes a model."""
from pathlib import Path
import copy
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import aidev
import terrain_runtime as runtime
import terrain_provider as provider
from tools import context_supervisor as supervisor


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve(); self.exe = self.root/('acp.exe' if runtime.WINDOWS else 'acp'); self.exe.write_text('fake'); self.exe.chmod(0o700)
        self.manifest = self.root/'qualification.json'
        self.record = {'schema_version':1,'engine':{'path':str(self.exe),'sha256':runtime.file_hash(self.exe)},'node':{'path':str(self.exe),'sha256':runtime.file_hash(self.exe)},'mode': runtime.CONTEXT_MODE, 'acp_sha256': runtime.file_hash(self.exe),
            'engine_sha256': runtime.file_hash(self.exe),
            'gates':dict.fromkeys(('protocol','codex_policy','os_deny','mcp_startup','recovery'),'PASS'),
            'files':{str(self.exe):runtime.file_hash(self.exe)},
            'mcp':{'command':str(self.exe),'args':[str(self.exe)],'enabled':True,'env':{'npm_config_offline':'true'}}}
    def qualify(self):
        self.manifest.write_text(json.dumps(self.record))
        self.enterContext(patch.object(runtime,'CONTEXT_QUALIFICATION',self.manifest))
        self.enterContext(patch.object(runtime,'CONTEXT_QUALIFICATION_SHA256',runtime.file_hash(self.manifest)))
    def test_old_and_unverified_refused_before_any_execution(self):
        with patch.object(runtime,'CONTEXT_QUALIFICATION',self.manifest), patch.object(runtime,'execute') as run, patch.object(runtime,'check_version') as version:
            with self.assertRaisesRegex(aidev.Problem,'未検証ACP'):
                runtime.setup(self.exe,self.exe,approve=True,root=self.root/'repo')
            run.assert_not_called();version.assert_not_called()
    def test_pinned_qualification_missing_modified_dependency_and_wrong_acp(self):
        self.qualify();runtime.verify_context_capability(self.exe)
        self.exe.write_text('changed')
        with self.assertRaises(aidev.Problem):runtime.verify_context_capability(self.exe)
        self.exe.write_text('fake');self.manifest.write_text('{}')
        with self.assertRaisesRegex(aidev.Problem,'hash'):runtime.verify_context_capability(self.exe)
    def test_blocked_gate_cannot_launch(self):
        self.record['gates']['os_deny']='BLOCKED';self.qualify()
        with self.assertRaisesRegex(aidev.Problem,'未完了'):runtime.verify_context_capability(self.exe)
    def test_missing_mcp_stops_before_bootstrap(self):
        self.record['files'][str(self.root/'missing')]='0'*64;self.qualify()
        with patch.object(runtime,'execute') as run:
            with self.assertRaises(aidev.Problem):
                with runtime.terrain_environment(self.root/'repo',self.root/'registry',{'path':str(self.exe),'codex':{'path':str(self.exe)},'codex_home':str(self.root)}):pass
            run.assert_not_called()
    def test_overlay_preserves_other_mcp_and_rechecks_each_launch(self):
        self.qualify()
        overlay={'mcp_servers':{'other':{'command':'untouched'},'chrome-devtools':{'env':{'KEEP':'yes'}}},'model':'untouched'}
        with patch.dict(os.environ,{'CODEX_CONFIG':json.dumps(overlay)}):
            with runtime.terrain_environment(self.root/'repo',self.root/'registry',{'path':str(self.exe),'codex':{'path':str(self.exe)},'codex_home':str(self.root)}) as (env,home):
                result=json.loads(env['CODEX_CONFIG']);self.assertEqual(result['model'],'untouched');self.assertEqual(result['mcp_servers']['other'],overlay['mcp_servers']['other']);self.assertEqual(result['mcp_servers']['chrome-devtools']['env']['KEEP'],'yes');self.assertEqual(env['INITIAL_AGENT_MODE'],runtime.CONTEXT_MODE)


@unittest.skipUnless(sys.platform=='linux','Linux isolated supervisor')
class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def run_child(self,code,grace=10):
        result=supervisor.run_owned([sys.executable,'-B','-c',code],self.root,os.environ.copy(),self.root/'log',self.root/'result.json',timeout=.5,grace=grace)
        self.assertEqual(json.loads((self.root/'result.json').read_text()),result)
        self.assertFalse(result['cleanup']['remaining']);return result
    def test_graceful_owner_restores_pair(self):
        code=f'''import sys,time
from pathlib import Path
sys.path.insert(0,{str(Path(provider.__file__).parent)!r})
import terrain_provider as p
root=Path.cwd();(root/'.terrain/agent').mkdir(parents=True)
try: time.sleep(60)
except KeyboardInterrupt:
 p.recover_context(root,{{p.CONTEXT:b'old',p.CONTEXT_META:b'meta'}},'fixture')
 raise SystemExit(130)
'''
        result=self.run_child(code);self.assertEqual(result['cleanup']['method'],'cooperative-SIGINT');self.assertEqual((self.root/provider.CONTEXT).read_bytes(),b'old')

    def test_recovery_interrupts_owned_receiver_instead_of_wrapper(self):
        receiver = self.root / 'receiver.py'
        receiver.write_text('''import signal, time
from pathlib import Path
def interrupted(signum, frame):
    Path('received').write_text('SIGINT')
    raise SystemExit(130)
signal.signal(signal.SIGINT, interrupted)
Path('ready').touch()
time.sleep(60)
''')
        argv = [sys.executable, '-B', str(receiver)]
        wrapper = [sys.executable, '-B', '-c',
                   'import subprocess,sys; sys.exit(subprocess.call(sys.argv[1:]))', *argv]
        selected = {}

        def recovery_target(known):
            matches = []
            for pid, ticks in known.items():
                try:
                    args = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')
                except OSError:
                    continue
                if [os.fsdecode(arg) for arg in args if arg] == argv:
                    matches.append((pid, ticks))
            self.assertEqual(len(matches), 1)
            selected['pid'], selected['start_ticks'] = matches[0]
            return selected['pid']

        result = supervisor.run_owned(
            wrapper, self.root, os.environ.copy(), self.root / 'log', self.root / 'result.json',
            timeout=3, grace=2, recovery_target=recovery_target)
        self.assertTrue((self.root / 'ready').is_file())
        self.assertEqual((self.root / 'received').read_text(), 'SIGINT')
        cleanup = result['cleanup']
        self.assertNotEqual(cleanup['wrapper_pid'], selected['pid'])
        self.assertEqual(cleanup['recovery_target_pid'], selected['pid'])
        self.assertEqual(cleanup['recovery_target_start_ticks'], selected['start_ticks'])
        self.assertEqual(cleanup['method'], 'cooperative-SIGINT')
        self.assertEqual(result['exit_code'], 130)
        self.assertEqual(result['remaining'], [])
    def test_grace_expiry_kills_separate_group_child(self):
        code="import subprocess,sys,signal,time; signal.signal(signal.SIGINT,signal.SIG_IGN); subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGINT,signal.SIG_IGN); signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'],start_new_session=True); time.sleep(60)"
        started=time.monotonic();r=self.run_child(code);self.assertGreaterEqual(time.monotonic()-started,10);self.assertEqual(r['cleanup']['method'],'forced-TERM-KILL');self.assertGreaterEqual(len(r['observed']),2)
    def test_repeated_interrupt_is_recorded_during_grace(self):
        def interrupt():time.sleep(.7);os.kill(os.getpid(),signal.SIGINT)
        t=threading.Thread(target=interrupt);t.start()
        try:r=self.run_child('import signal,time;signal.signal(signal.SIGINT,signal.SIG_IGN);time.sleep(60)',grace=1)
        finally:t.join()
        self.assertEqual(r['cleanup']['repeat_interrupts'],1)
    def test_pid_reuse_and_signal_failure(self):
        report={'signals':[],'stop_errors':[]}
        supervisor.signal_owned(os.getpid(),'wrong-start',signal.SIGKILL,report);self.assertEqual(report['signals'],[])
        with patch.object(supervisor.ctypes,'CDLL',side_effect=OSError(1,'denied')):
            supervisor.signal_owned(os.getpid(),supervisor.identity(os.getpid())[0],signal.SIGINT,report)
        self.assertEqual(report['stop_errors'][0]['errno'],1)
    def test_failed_pidfd_open_never_closes_negative_fd(self):
        report={'signals':[],'stop_errors':[]}
        with patch.object(supervisor.ctypes,'CDLL') as libc, patch.object(supervisor.os,'close') as close:
            libc.return_value.pidfd_open.return_value=-1
            with patch.object(supervisor.ctypes,'get_errno',return_value=1):
                supervisor.signal_owned(os.getpid(),supervisor.identity(os.getpid())[0],signal.SIGINT,report)
            close.assert_not_called()
        self.assertEqual(report['stop_errors'][0]['errno'],1)

    def test_partial_pair_and_concurrent_writer_preserved(self):
        (self.root/'.terrain/agent').mkdir(parents=True)
        pair={provider.CONTEXT:b'old',provider.CONTEXT_META:b'meta'}
        (self.root/provider.CONTEXT).write_bytes(b'partial')
        with self.assertRaises(aidev.Problem):provider.recover_context(self.root,pair,'fixture')
        self.assertEqual((self.root/provider.CONTEXT).read_bytes(),b'partial')
        (self.root/provider.CONTEXT).unlink()
        actual=provider.safe_path
        def race(root,name):
            p=actual(root,name)
            if name==provider.CONTEXT_META:
                t=threading.Thread(target=lambda:p.write_bytes(b'concurrent'));t.start();t.join()
            return p
        with patch.object(provider,'safe_path',side_effect=race):
            with self.assertRaises(aidev.Problem):provider.recover_context(self.root,pair,'fixture')
        self.assertEqual((self.root/provider.CONTEXT_META).read_bytes(),b'concurrent')
