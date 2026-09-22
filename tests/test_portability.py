"""Cross-platform contracts; OS-specific cases run on their actual kernel."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest.mock import patch

import aidev
import install
import platform_support as platform


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="aidev-空白 space-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_utf8_output_and_literal_arguments(self):
        args = ['日本語 path', 'quote"value', '&whoami', '%TEMP%', '!name!']
        result = aidev.run([sys.executable, '-X', 'utf8', '-c', 'import sys,json; print(json.dumps(sys.argv[1:], ensure_ascii=False))', *args], self.root)
        self.assertEqual(json.loads(result), args)

    def test_lock_excludes_another_process_and_releases(self):
        code = 'from pathlib import Path; from platform_support import directory_lock; import sys\nwith directory_lock(Path(sys.argv[1])): pass'
        command = [sys.executable, '-B', '-c', code, str(self.root)]
        with platform.directory_lock(self.root):
            result = subprocess.run(command, cwd=install.SOURCE, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(subprocess.run(command, cwd=install.SOURCE, capture_output=True).returncode, 0)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_timeout_kills_grandchild_even_if_parent_exits(self):
        marker = self.root / 'escaped.txt'
        ready = self.root / 'ready.txt'
        child = ('import time,signal; from pathlib import Path; '
                 'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                 f'Path({str(ready)!r}).write_text("ready"); time.sleep(4); '
                 f'Path({str(marker)!r}).write_text("escaped")')
        parent = ('import subprocess,sys,time; '
                  f'subprocess.Popen([sys.executable,"-c",{child!r}]); '
                  'print("started",flush=True); time.sleep(30)')
        with self.assertRaises(aidev.Problem):
            aidev.run([sys.executable, '-c', parent], self.root, timeout=2, log=self.root / 'timeout.log')
        self.assertTrue(ready.exists(), 'grandchild must run before timeout')
        time.sleep(3)
        self.assertFalse(marker.exists())
        self.assertIn('started', (self.root / 'timeout.log').read_text(encoding='utf-8'))

    def test_process_launch_failure_becomes_problem_and_keeps_log(self):
        log = self.root / 'launch.log'
        with patch.object(aidev, 'child_process', side_effect=OSError('job assignment denied')):
            with self.assertRaisesRegex(aidev.Problem, 'job assignment denied'):
                aidev.run(['provider'], self.root, log=log)
        self.assertTrue(log.is_file())

    def test_safe_path_rejects_absolute_and_parent_paths(self):
        for path in (str(self.root / 'outside'), '../outside'):
            with self.assertRaises(aidev.Problem):
                aidev.safe_path(self.root, path)

    @unittest.skipUnless(platform.WINDOWS, 'requires native Windows')
    def test_windows_junction_is_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        repo = self.root / 'repo'
        repo.mkdir()
        junction = repo / '.codex'
        subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(junction), str(outside)], check=True, capture_output=True)
        try:
            with self.assertRaises(aidev.Problem):
                aidev.safe_path(repo, '.codex/config.toml')
        finally:
            junction.rmdir()
        self.assertEqual(list(outside.iterdir()), [])

    def test_mcp_paths_roundtrip_through_toml(self):
        records = {p: {'command': 'C:\\Tools 日本語 🐍\\' + p + '.exe', 'python': 'C:\\Tools 日本語 🐍\\python.exe'} for p in aidev.PROVIDERS}
        bins = aidev.ProviderBins(records)
        for p, section in aidev.mcp_sections(bins).items():
            self.assertEqual(tomllib.loads(section)['mcp_servers'][p]['command'], bins[p])


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.config = self.root / 'host/foundation.json'
        self.pythons = {}
        for p, (name, _) in aidev.PROVIDERS.items():
            folder = self.root / p / ('Scripts' if platform.WINDOWS else 'bin')
            folder.mkdir(parents=True)
            python = folder / ('python.exe' if platform.WINDOWS else 'python')
            python.write_bytes(b'python fixture')
            (folder / (name + ('.exe' if platform.WINDOWS else ''))).write_bytes(b'cli fixture')
            self.pythons[p] = python
        self.stack = self.enterContext(ExitStack())
        self.stack.enter_context(patch.object(aidev, 'data_home', return_value=self.config.parent))
        self.stack.enter_context(patch.object(aidev, 'check_provider_version'))
        def run(argv, root):
            distribution = argv[-1]
            return {'serena-agent': '1.7.0', 'graphifyy': '0.9.55', 'code-review-graph': '2.3.8'}[distribution]
        self.stack.enter_context(patch.object(aidev, 'run', side_effect=run))

    def test_setup_preview_never_approves_or_writes(self):
        result = aidev.setup_foundation(self.pythons)
        self.assertEqual(result['status'], 'PLAN')
        self.assertFalse(result['approved'])
        self.assertFalse(self.config.exists())

    def test_approved_registration_and_explicit_python(self):
        aidev.setup_foundation(self.pythons, approve=True)
        bins = aidev.registered_foundation(self.root / 'repo', self.config)
        self.assertEqual(aidev.provider_python(bins, 'crg'), self.pythons['crg'])
        self.assertFalse(aidev.setup_foundation(self.pythons, approve=True)['writes'])

    def test_changed_executable_and_repo_local_execution_are_rejected(self):
        aidev.setup_foundation(self.pythons, approve=True)
        with self.assertRaisesRegex(aidev.Problem, 'Repo内'):
            aidev.registered_foundation(self.root, self.config)
        self.pythons['crg'].write_bytes(b'changed')
        with self.assertRaisesRegex(aidev.Problem, '変更'):
            aidev.registered_foundation(self.root / 'repo', self.config)

    def test_unapproved_registration_is_rejected(self):
        result = aidev.setup_foundation(self.pythons)
        self.config.parent.mkdir()
        self.config.write_text(json.dumps(result), encoding='utf-8')
        with self.assertRaisesRegex(aidev.Problem, '承認'):
            aidev.registered_foundation(self.root / 'repo', self.config)

    def test_malformed_registration_is_rejected(self):
        self.config.parent.mkdir()
        for data in ([], {'schema_version': True}, {'schema_version': 1, 'approved': True, 'providers': []}):
            self.config.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaises(aidev.Problem):
                aidev.registered_foundation(self.root / 'repo', self.config)

    def test_replacement_requires_flag_and_keeps_original_bytes(self):
        aidev.setup_foundation(self.pythons, approve=True)
        raw = self.config.read_bytes()
        self.pythons['crg'].write_bytes(b'new version of interpreter')
        with self.assertRaisesRegex(aidev.Problem, '--replace'):
            aidev.setup_foundation(self.pythons, approve=True)
        self.assertEqual(self.config.read_bytes(), raw)
        aidev.setup_foundation(self.pythons, approve=True, replace=True)
        self.assertEqual(next(self.config.parent.glob('foundation.backup-*.json')).read_bytes(), raw)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='aidev-install 日本語-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        for name in install.FILES:
            shutil.copyfile(install.SOURCE / name, self.source / name)
        self.target = self.root / 'app'
        self.entry = self.target / 'bin/aidev.cmd' if platform.WINDOWS else self.root / 'bin/aidev'
        self.stack = self.enterContext(ExitStack())
        for key, value in [('SOURCE', self.source), ('TARGET', self.target), ('ENTRY', self.entry)]:
            self.stack.enter_context(patch.object(install, key, value))
        original_which = shutil.which
        self.stack.enter_context(patch.object(install.shutil, 'which', side_effect=lambda name: None if name == 'aidev' else original_which(name)))

    def test_install_upgrade_and_changed_files_preserved(self):
        first = install.install()
        output = subprocess.check_output([sys.executable, '-B', str(first / 'aidev.py'), '--version'], text=True)
        self.assertEqual(output.strip(), 'aidev ' + aidev.VERSION)
        output = subprocess.check_output([str(self.entry), '--version'], text=True)
        self.assertEqual(output.strip(), 'aidev ' + aidev.VERSION)
        self.assertEqual(install.install(upgrade=True), first)
        (self.source / 'README.md').write_text('upgrade fixture', encoding='utf-8')
        second = install.install(upgrade=True)
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_dir())
        self.assertEqual(install.active_release(), second)
        (second / 'aidev.py').write_text('# user changed\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '変更'):
            install.install(upgrade=True)
        self.assertEqual((second / 'aidev.py').read_text(), '# user changed\n')

    @unittest.skipIf(platform.WINDOWS, '0.1.1 installer was Unix-only')
    def test_upgrade_from_four_file_release(self):
        with patch.object(install, 'FILES', ('aidev.py', 'provider_probe.py', 'provider_build.py', 'README.md')):
            first = install.install()
        second = install.install(upgrade=True)
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())
        self.assertEqual(install.active_release(), second)
        output = subprocess.check_output([str(self.entry), '--version'], text=True)
        self.assertEqual(output.strip(), 'aidev ' + aidev.VERSION)

    def test_foreign_command_is_not_replaced(self):
        self.entry.parent.mkdir(parents=True)
        self.entry.write_text('user command', encoding='utf-8')
        with self.assertRaises(ValueError):
            install.install(upgrade=True)
        self.assertEqual(self.entry.read_text(), 'user command')

    def legacy_fixture(self):
        self.target.mkdir()
        self.entry.parent.mkdir()
        for name in install.LEGACY_HASHES:
            shutil.copy2(self.source / name, self.target / name)
        expected = install.hashes(self.target, install.LEGACY_HASHES)
        self.stack.enter_context(patch.object(install, 'LEGACY_HASHES', expected))
        self.entry.symlink_to(self.target / 'aidev.py')
        return expected

    @unittest.skipIf(platform.WINDOWS, 'legacy layout is Unix-only')
    def test_legacy_upgrade_retains_files_and_links(self):
        expected = self.legacy_fixture()
        release = install.install(upgrade=True)
        self.assertEqual(self.entry.resolve(), release / 'aidev.py')
        for name in install.FILES:
            self.assertEqual((self.target / name).resolve(), release / name)
        saved = [p for p in (self.target / 'releases').iterdir() if p != release]
        self.assertEqual(len(saved), 1)
        self.assertEqual(install.hashes(saved[0], expected), expected)
        self.assertEqual(len(list(self.target.glob('.aidev-link-backup-*'))), 3)

    @unittest.skipIf(platform.WINDOWS, 'legacy layout is Unix-only')
    def test_legacy_changed_file_or_helper_conflict_preserved(self):
        self.legacy_fixture()
        original = (self.target / 'README.md').read_bytes()
        (self.target / 'README.md').write_text('user changed')
        with self.assertRaisesRegex(ValueError, '変更'):
            install.install(upgrade=True)
        self.assertEqual((self.target / 'README.md').read_text(), 'user changed')
        (self.target / 'README.md').write_bytes(original)
        (self.target / 'terrain_runtime.py').write_text('foreign helper')
        before = install.entry_record()
        with self.assertRaisesRegex(ValueError, '管理path'):
            install.install(upgrade=True)
        self.assertEqual(install.entry_record(), before)
        self.assertEqual((self.target / 'terrain_runtime.py').read_text(), 'foreign helper')

    @unittest.skipIf(platform.WINDOWS, 'legacy layout is Unix-only')
    def test_legacy_interrupted_helper_publication_resumes(self):
        self.legacy_fixture()
        original = Path.symlink_to
        def fail(path, target, *args, **kwargs):
            if path == self.target / 'provider_probe.py':
                raise OSError('fixture publication failure')
            return original(path, target, *args, **kwargs)
        with patch.object(Path, 'symlink_to', fail), self.assertRaises(OSError):
            install.install(upgrade=True)
        self.assertEqual(install.read_journal()['phase'], 'entry-published')
        release = install.install()
        self.assertEqual(install.active_release(), release)
        self.assertIsNone(install.read_journal())
        for name in install.FILES:
            self.assertEqual((self.target / name).resolve(), release / name)

    @unittest.skipIf(platform.WINDOWS, 'legacy layout is Unix-only')
    def test_legacy_concurrent_change_after_entry_is_preserved(self):
        self.legacy_fixture()
        original = install.write_journal
        def race(record):
            original(record)
            if record['phase'] == 'entry-published':
                (self.target / 'README.md').write_text('concurrent edit')
        with patch.object(install, 'write_journal', race), self.assertRaisesRegex(ValueError, '管理path'):
            install.install(upgrade=True)
        with self.assertRaisesRegex(ValueError, '管理path'):
            install.install()
        self.assertEqual((self.target / 'README.md').read_text(), 'concurrent edit')
        self.assertEqual(install.read_journal()['phase'], 'entry-published')

    def test_windows_layout_without_symlinks(self):
        entry = self.target / 'bin/aidev.cmd'
        with patch.object(install, 'WINDOWS', True), patch.object(install, 'ENTRY', entry):
            release = install.install()
            self.assertEqual(install.active_release(), release)
            self.assertFalse(any(p.is_symlink() for p in self.target.rglob('*')))
            launcher = entry.read_text(encoding='utf-8')
            self.assertIn('chcp 65001', launcher)
            self.assertIn(str(Path(sys.executable).resolve()), launcher)
            self.assertNotIn('py -3', launcher)
            entry.write_bytes(entry.read_bytes() + b'REM user edit\r\n')
            with self.assertRaisesRegex(ValueError, '変更'):
                install.install(upgrade=True)

    def test_windows_launcher_escapes_percent_in_fixed_python_path(self):
        release = self.target / 'releases' / ('a' * 20)
        python = self.root / '100% safe' / 'python.exe'
        launcher = install.windows_launcher(release, {'executable': str(python)})
        self.assertIn(str(python).replace('%', '%%').encode('utf-8'), launcher)

    @unittest.skipUnless(platform.WINDOWS, 'requires native Windows cmd execution')
    def test_windows_cmd_launcher_uses_fixed_python_not_path_or_py(self):
        # Real Python and launcher paths exercise cmd quoting. No packages are
        # downloaded, and no installed launcher or production source is edited.
        python_home = self.root / 'Python 日本語 & (space) !'
        subprocess.run([sys.executable, '-X', 'utf8', '-B', '-m', 'venv', '--without-pip',
                        str(python_home)], check=True, capture_output=True, timeout=60)
        python = python_home / 'Scripts/python.exe'
        target = self.root / 'app 日本語 & (space) !'
        entry = target / 'bin/aidev.cmd'
        installer = (
            'import install,sys; from pathlib import Path; '
            'install.SOURCE=Path(sys.argv[1]); install.TARGET=Path(sys.argv[2]); '
            'install.ENTRY=Path(sys.argv[3]); install.install(upgrade=len(sys.argv)>4)'
        )
        install_command = [str(python), '-X', 'utf8', '-B', '-c', installer,
                           str(self.source), str(target), str(entry)]
        subprocess.run(install_command, cwd=Path(install.__file__).parent,
                       check=True, capture_output=True, timeout=30)
        fake_bin = self.root / 'fake path'
        fake_bin.mkdir()
        (self.root / 'py.cmd').write_bytes(b'@echo off\r\necho DECOY_PY\r\nexit /b 73\r\n')
        (fake_bin / 'python.cmd').write_bytes(b'@echo off\r\necho DECOY_PYTHON\r\nexit /b 74\r\n')
        cmd = Path(os.environ['SystemRoot']) / 'System32/cmd.exe'
        env = dict(os.environ)
        env['PATH'] = str(fake_bin) + os.pathsep + str(cmd.parent)
        env['PATHEXT'] = '.COM;.EXE;.BAT;.CMD'

        def run_cmd(command):
            # Pass a cmd command line directly: list2cmdline's C quoting is not
            # cmd quoting. /s removes just the outer pair surrounding command.
            return subprocess.run(f'"{cmd}" /d /v:off /s /c "{command}"', executable=str(cmd),
                                  cwd=self.root, env=env, capture_output=True, text=True,
                                  encoding='utf-8', errors='strict', timeout=30)

        # Prove that name-based lookup really would select the decoys.
        for command, code, marker in [('py', 73, 'DECOY_PY'), ('python', 74, 'DECOY_PYTHON')]:
            control = run_cmd(command)
            self.assertEqual(control.returncode, code, control.stderr)
            self.assertEqual(control.stdout.strip(), marker)
        result = run_cmd(f'"{entry}" --version')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'aidev ' + aidev.VERSION)

        # Install a reporting payload from disposable source using the same real
        # installer. Version output alone cannot identify the running Python.
        (self.source / 'aidev.py').write_text(
            'import json,sys\n'
            'print(json.dumps({"executable":sys.executable,"version":list(sys.version_info[:3]),'
            '"args":sys.argv[1:]}))\n'
            'raise SystemExit(37)\n', encoding='utf-8')
        subprocess.run([*install_command, '--upgrade'], cwd=Path(install.__file__).parent,
                       check=True, capture_output=True, timeout=30)
        args = ['日本語 argument', 'a&b', '(parentheses)', '!literal!']
        result = run_cmd(f'"{entry}" ' + ' '.join(f'"{arg}"' for arg in args))
        self.assertEqual(result.returncode, 37, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(Path(report['executable']).resolve(), python.resolve())
        self.assertEqual(report['version'], list(sys.version_info[:3]))
        self.assertEqual(report['args'], args)
        self.assertNotIn('DECOY_', result.stdout + result.stderr)

    def test_pre_lock_foreign_entry_is_preserved(self):
        marker = b'user command\n'
        original_lock = install.directory_lock
        from contextlib import contextmanager
        @contextmanager
        def race(path):
            self.entry.write_bytes(marker)
            with original_lock(path):
                yield
        with patch.object(install, 'directory_lock', race), self.assertRaisesRegex(ValueError, '管理外'):
            install.install()
        self.assertEqual(self.entry.read_bytes(), marker)

    def test_initial_failure_with_owned_journal_retries_normally(self):
        original = (self.source / 'aidev.py').read_bytes()
        (self.source / 'aidev.py').write_bytes(b'invalid syntax !\n')
        with self.assertRaises(SyntaxError):
            install.install()
        self.assertTrue((self.target / install.JOURNAL).is_file())
        (self.source / 'aidev.py').write_bytes(original)
        release = install.install()
        self.assertEqual(install.active_release(), release)
        self.assertFalse((self.target / install.JOURNAL).exists())

    def test_unowned_partial_release_is_not_adopted(self):
        (self.target / 'releases' / 'partial').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, '所有記録'):
            install.install()


if __name__ == '__main__':
    unittest.main()
