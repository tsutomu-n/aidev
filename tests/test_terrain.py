"""Terrain contracts using disposable Git repos; no authentication or downloads."""
from contextlib import ExitStack
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import aidev
import install
import terrain_provider as provider
import terrain_runtime as runtime


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file() and '.git' not in p.relative_to(root).parts}


def context(root, slug='fixture'):
    body = '\n\n'.join('## ' + title + '\n\n' + '日本語の説明。' * 40 for title in ('Project Overview', 'Architecture', 'Module Map', 'Core Flows', 'Tech Stack', 'System Boundaries', 'Code Map Index'))
    aidev.atomic(root / provider.CONTEXT, ('---\nsource: .\n---\n\n' + body).encode())
    aidev.atomic(root / provider.CONTEXT_META, aidev.js({'project': slug, 'output_file': 'context.md', 'repo_path': '.', 'section_count': 7, 'char_count': len(body), 'baseline_git_head': aidev.git(root, 'rev-parse', 'HEAD').strip()}).encode())


class TerrainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='terrain 日本語 space-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'repo'
        self.root.mkdir()
        aidev.git(self.root, 'init', '--quiet')
        (self.root / 'code.py').write_text('def strategy(): return 1\n')
        aidev.git(self.root, 'add', 'code.py')
        aidev.git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=test@example.test', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture')
        self.binary = self.base / ('terrain.exe' if runtime.WINDOWS else 'terrain')
        self.binary.write_bytes(b'fake runtime')
        self.binary.chmod(0o700)
        self.record = {'schema_version': 1, 'approved': True, 'upstream_sha': runtime.TERRAIN_UPSTREAM_SHA, 'patch_sha256': runtime.patch_hash(), 'terrain': {'path': str(self.binary), 'sha256': runtime.file_hash(self.binary), 'version': '0.9.5', 'verified_behavior': True}}
        self.host = self.base / 'host'
        aidev.atomic(self.host / 'terrain/foundation.json', aidev.js(self.record).encode())
        self.enterContext(patch.object(runtime, 'data_home', return_value=self.host))
        self.calls = []
        self.enterContext(patch.object(runtime, 'invoke', side_effect=self.invoke))
        self.acp_calls = []
        self.enterContext(patch.object(runtime, 'preflight_acp', side_effect=lambda *args: self.acp_calls.append('preflight') or str(self.binary)))

    def invoke(self, binary, root, registry, args, timeout=600, log=None, acp=None):
        self.calls.append(list(args))
        if args[:2] == ['assets', 'register']:
            aidev.atomic(registry, aidev.js({'projects': [{'slug': args[-1], 'repo_path': str(root)}]}).encode())
        elif args[0] == 'scan' or args[:2] == ['assets', 'pack-agent']:
            body = (root / 'code.py').read_text()
            aidev.atomic(root / provider.PACK, ('### code.py (1 lines)\n' + body).encode())
            aidev.atomic(root / provider.PACK_META, aidev.js({'project': args[-1], 'repo_path': '.', 'output_file': 'repomix.md', 'total_files': 1, 'baseline_git_head': aidev.git(root, 'rev-parse', 'HEAD').strip()}).encode())
        elif args[:2] == ['assets', 'agent-context']:
            self.assertTrue(acp)
            context(root, args[-2])
        elif args[0] == 'tools':
            return (root / (provider.CONTEXT if args[1] == 'read-context' else provider.PACK)).read_text()
        else:
            self.fail(str(args))
        return '{}'

    def init(self, **kwargs):
        return provider.initialize(self.root, slug='fixture', **kwargs)

    def test_dry_run_and_doctor_write_nothing_and_never_spawn(self):
        before = snapshot(self.base)
        self.assertEqual(self.init(dry_run=True)['status'], 'PLAN')
        self.assertEqual(provider.doctor(self.root)['status'], 'TERRAIN_INVALID')
        self.assertEqual(snapshot(self.base), before)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.acp_calls, [])

    def test_idempotent_and_context_gating(self):
        self.assertEqual(self.init()['context'], 'not-built')
        self.assertEqual(self.acp_calls, [])
        calls = len(self.calls)
        self.assertEqual(self.init()['indexes'], 'reused')
        self.assertEqual(len(self.calls), calls)
        self.assertEqual((self.root / 'AGENTS.md').read_text().count(provider.START), 1)
        self.assertEqual(self.init(build_context=True)['context'], 'built')
        calls = len(self.calls)
        self.assertEqual(self.init(build_context=True)['context'], 'reused')
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(len(self.acp_calls), 1)
        self.assertEqual(provider.doctor(self.root)['status'], 'TERRAIN_READY')

    def test_dirty_staged_untracked_and_ignored(self):
        self.init()
        self.assertEqual(provider.doctor(self.root)['status'], 'TERRAIN_READY_CONTEXT_NOT_BUILT')
        (self.root / 'code.py').write_text('def strategy(): return 2\n')
        self.assertEqual(provider.doctor(self.root)['status'], 'TERRAIN_NEEDS_REFRESH')
        self.assertEqual(self.init(refresh=True)['indexes'], 'built')
        aidev.git(self.root, 'add', 'code.py')
        self.assertEqual(provider.doctor(self.root)['status'], 'TERRAIN_NEEDS_REFRESH')
        (self.root / 'code.py').write_text('def strategy(): return 3\n')
        self.assertEqual(provider.doctor(self.root)['status'], 'TERRAIN_NEEDS_REFRESH')
        self.init(refresh=True)
        (self.root / 'new.txt').write_text('input')
        self.assertEqual(provider.doctor(self.root)['status'], 'TERRAIN_NEEDS_REFRESH')
        self.init(refresh=True)
        (self.root / '.gitignore').write_text('/.aidev/\nignored/\n')
        self.init(refresh=True)
        (self.root / 'ignored').mkdir()
        (self.root / 'ignored/huge.txt').write_text('excluded')
        self.assertEqual(provider.doctor(self.root)['status'], 'TERRAIN_READY_CONTEXT_NOT_BUILT')

    def test_refresh_preserves_stale_context_then_builds_once(self):
        self.init(build_context=True)
        old = (self.root / provider.CONTEXT).read_bytes()
        (self.root / 'code.py').write_text('changed')
        self.assertEqual(self.init(refresh=True)['context'], 'stale')
        self.assertEqual((self.root / provider.CONTEXT).read_bytes(), old)
        self.assertEqual(provider.doctor(self.root)['status'], 'TERRAIN_NEEDS_CONTEXT_REFRESH')
        self.assertEqual(self.init(refresh=True, build_context=True)['context'], 'built')
        self.assertEqual(len(self.acp_calls), 2)

    def test_source_changes_during_run_do_not_commit_state(self):
        original = self.invoke
        def change(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[3][0] == 'scan':
                (self.root / 'code.py').write_text('concurrent edit')
            return result
        with patch.object(runtime, 'invoke', side_effect=change):
            with self.assertRaisesRegex(aidev.Problem, 'source'):
                self.init()
        self.assertFalse((self.root / provider.STATE).exists())
        self.assertEqual((self.root / 'code.py').read_text(), 'concurrent edit')
        self.assertEqual(self.init()['indexes'], 'built')

    def test_agents_preservation_and_backup(self):
        original = b'# User rules\nkeep these bytes\n'
        (self.root / 'AGENTS.md').write_bytes(original)
        self.init()
        self.assertTrue((self.root / 'AGENTS.md').read_bytes().startswith(original))
        backups = list((self.root / '.aidev/terrain/backups').glob('*/AGENTS.md'))
        self.assertEqual(backups[0].read_bytes(), original)
        text = (self.root / 'AGENTS.md').read_text().replace('derived navigation/index', 'old guidance')
        (self.root / 'AGENTS.md').write_text(text)
        self.init()
        self.assertNotIn('old guidance', (self.root / 'AGENTS.md').read_text())

    def test_manual_guidance_never_claimed(self):
        original = '# Rules\n\n## Terrain Knowledge Layer\nmanual instructions\n'
        (self.root / 'AGENTS.md').write_text(original)
        self.assertEqual(self.init()['agents_guidance'], 'existing-manual')
        self.assertEqual((self.root / 'AGENTS.md').read_text(), original)

    def test_registry_isolation_between_real_worktrees(self):
        self.init(build_context=True)
        other = self.base / 'other'
        aidev.git(self.root, 'worktree', 'add', '--detach', str(other), 'HEAD')
        (other / 'code.py').write_text('def other_strategy(): return 9\n')
        provider.initialize(other, slug='fixture', build_context=True)
        self.assertNotEqual((self.root / provider.REGISTRY).read_bytes(), (other / provider.REGISTRY).read_bytes())
        args = argparse.Namespace(tool='grep-pack', pattern='strategy', context=2, limit=20)
        self.assertNotEqual(provider.read_tool(self.root, args), provider.read_tool(other, args))
        self.assertEqual(provider.doctor(self.root)['status'], 'TERRAIN_READY')
        self.assertEqual(provider.doctor(other)['status'], 'TERRAIN_READY')

    def test_tracked_local_artifacts_rejected(self):
        self.init()
        aidev.git(self.root, 'add', '-f', provider.PACK)
        self.assertEqual(provider.doctor(self.root)['status'], 'TERRAIN_INVALID')
        with self.assertRaisesRegex(aidev.Problem, '追跡'):
            self.init()

    def test_openapi_valid_preserved_ignored_rejected(self):
        self.init()
        (self.root / 'docs').mkdir()
        (self.root / 'docs/openapi.yaml').write_text('openapi: 3.0.0')
        aidev.atomic(self.root / '.terrain/interfaces/health.md', b'---\nsource: docs/openapi.yaml\n---\nhealth')
        self.assertEqual(provider.provenance_check(self.root), [])
        (self.root / '.gitignore').write_text('/.aidev/\ndocs/\n')
        self.assertEqual(provider.doctor(self.root)['status'], 'TERRAIN_INVALID')
        self.assertTrue((self.root / '.terrain/interfaces/health.md').is_file())

    def test_context_count_unicode_and_other_checkout_paths(self):
        self.init(build_context=True)
        meta = json.loads((self.root / provider.CONTEXT_META).read_text())
        for key in ('section_count', 'char_count'):
            bad = dict(meta, **{key: meta[key] + 1})
            (self.root / provider.CONTEXT_META).write_text(json.dumps(bad))
            self.assertTrue(provider.context_check(self.root))
        (self.root / provider.CONTEXT_META).write_text(json.dumps(meta))
        for path in (str(self.root), '/home/another/checkout', 'C:\\Users\\other\\repo'):
            context(self.root)
            with (self.root / provider.CONTEXT).open('a') as stream:
                stream.write('\n' + path)
            self.assertTrue(any('absolute' in issue for issue in provider.context_check(self.root)))

    def test_legacy_migration_never_calls_llm(self):
        self.invoke(self.binary, self.root, self.root / provider.REGISTRY, ['scan', self.root, '--slug', 'fixture'])
        context(self.root)
        (self.root / 'AGENTS.md').write_text('## Terrain Knowledge Layer\nmanual')
        calls = len(self.calls)
        result = self.init(build_context=True)
        self.assertTrue(result['migration'])
        self.assertEqual(self.acp_calls, [])
        self.assertEqual(result['context'], 'stale')
        self.assertEqual(self.init(build_context=True)['context'], 'built')

    def test_clean_legacy_migration_reuses_assets(self):
        (self.root / 'AGENTS.md').write_text('## Terrain Knowledge Layer\nmanual rules\n')
        aidev.git(self.root, 'add', 'AGENTS.md')
        aidev.git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=test@example.test', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'guidance')
        self.invoke(self.binary, self.root, self.root / provider.REGISTRY, ['scan', self.root, '--slug', 'fixture'])
        context(self.root)
        before = (self.root / provider.CONTEXT).read_bytes()
        result = self.init(build_context=True)
        self.assertEqual(result['indexes'], 'reused')
        self.assertEqual(result['context'], 'reused')
        self.assertEqual(self.acp_calls, [])
        self.assertEqual(before, (self.root / provider.CONTEXT).read_bytes())

    def test_runtime_modified_unapproved_or_repo_local_rejected(self):
        self.assertEqual(runtime.load_runtime(self.root), self.record)
        self.binary.write_bytes(b'changed')
        with self.assertRaisesRegex(aidev.Problem, '変更'):
            runtime.load_runtime(self.root)
        self.binary.write_bytes(b'fake runtime')
        self.record['approved'] = False
        aidev.atomic(self.host / 'terrain/foundation.json', aidev.js(self.record).encode())
        with self.assertRaisesRegex(aidev.Problem, '承認'):
            runtime.load_runtime(self.root)
        with self.assertRaisesRegex(aidev.Problem, 'Repo内'):
            runtime.safe_absolute(self.binary, self.base, True)

    def test_setup_plan_no_execution_replace_and_version(self):
        with patch.object(runtime, 'check_version') as version, patch.object(runtime, 'behavioral_smoke', return_value={'fixture': 'PASS'}):
            before = snapshot(self.base)
            self.assertEqual(runtime.setup(self.binary, root=self.root)['status'], 'PLAN')
            version.assert_not_called()
            self.assertEqual(snapshot(self.base), before)
            with self.assertRaisesRegex(aidev.Problem, '--replace'):
                runtime.setup(self.binary, approve=True, root=self.root)
            result = runtime.setup(self.binary, approve=True, replace=True, root=self.root)
            self.assertEqual(result['status'], 'REGISTERED')
            self.assertTrue(list((self.host / 'terrain').glob('foundation.backup-*.json')))
        with patch.object(runtime, 'execute', return_value='terrain 0.9.4'):
            with self.assertRaisesRegex(aidev.Problem, 'version'):
                runtime.check_version(self.binary, '0.9.5')

    def test_secret_input_links_and_slug_change_rejected(self):
        (self.root / '.gitignore').write_text('!.env\n')
        (self.root / '.env').write_text('fake-secret')
        with self.assertRaisesRegex(aidev.Problem, 'ignore'):
            self.init()
        (self.root / '.env').unlink()
        self.init()
        with self.assertRaisesRegex(aidev.Problem, 'slug'):
            provider.initialize(self.root, slug='other')
        other = self.base / 'outside'
        other.write_text('preserve')
        (self.root / 'linked.py').hardlink_to(other)
        with self.assertRaisesRegex(aidev.Problem, 'hardlink'):
            self.init()

    def test_install_requires_download_and_bundle_contains_all_files(self):
        before = snapshot(self.base)
        with patch.object(runtime, 'execute', side_effect=AssertionError('must not execute')):
            self.assertEqual(runtime.install()['status'], 'PLAN')
        self.assertEqual(snapshot(self.base), before)
        for name in ('terrain_runtime.py', 'terrain_provider.py', 'terrain-0.9.5-aidev.patch', 'TERRAIN.md'):
            self.assertIn(name, install.FILES)

    def test_doctor_after_init_is_read_only_even_with_broken_context(self):
        self.init(build_context=True)
        before = snapshot(self.base)
        with patch.object(runtime, 'invoke', side_effect=AssertionError('doctor spawn')), patch.object(runtime, 'execute', side_effect=AssertionError('doctor spawn')):
            self.assertEqual(provider.doctor(self.root)['status'], 'TERRAIN_READY')
        self.assertEqual(snapshot(self.base), before)

    def test_ignore_barrier_user_bytes_are_backed_up(self):
        original = b"# user's local rules\nignored-file\n"
        aidev.atomic(self.root / '.aidev/.gitignore', original)
        self.init()
        self.assertTrue((self.root / '.aidev/.gitignore').read_bytes().startswith(original))
        backups = list((self.root / '.aidev/terrain/backups').glob('*/.aidev/.gitignore'))
        self.assertEqual(backups[0].read_bytes(), original)

    def test_unchanged_refresh_writes_nothing(self):
        self.init()
        before = snapshot(self.base)
        self.assertFalse(self.init(refresh=True)['writes'])
        self.assertEqual(before, snapshot(self.base))

    def test_missing_pack_after_scan_uses_one_fallback(self):
        original = self.invoke
        def no_pack(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[3][0] == 'scan':
                (self.root / provider.PACK).unlink()
            return result
        with patch.object(runtime, 'invoke', side_effect=no_pack):
            self.init()
        self.assertEqual(sum(c[:2] == ['assets', 'pack-agent'] for c in self.calls), 1)

    def test_unsafe_pack_is_rejected_before_acp(self):
        original = self.invoke
        def unsafe_pack(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[3][0] == 'scan' or args[3][:2] == ['assets', 'pack-agent']:
                with (self.root / provider.PACK).open('a') as stream:
                    stream.write('\n### .env (1 lines)\nfake secret')
            return result
        with patch.object(runtime, 'invoke', side_effect=unsafe_pack):
            with self.assertRaisesRegex(aidev.Problem, 'disallowed'):
                self.init(build_context=True)
        self.assertFalse(self.acp_calls)
        self.assertFalse((self.root / provider.STATE).exists())

    def test_process_environment_isolated_and_literal_arguments(self):
        actual_home = os.environ.get('HOME')
        actual_registry = os.environ.get('TERRAIN_REGISTRY_FILE')
        with runtime.terrain_environment(self.root, self.root / provider.REGISTRY, str(self.binary)) as (env, home):
            self.assertNotEqual(env['HOME'], actual_home)
            self.assertEqual(env['TERRAIN_REGISTRY_FILE'], str(self.root / provider.REGISTRY))
            self.assertEqual(env['INITIAL_AGENT_MODE'], 'read-only')
            self.assertEqual(env['TERRAIN_ACP_BINARY'], str(self.binary))
            settings = json.loads((home / '.terrain/settings.json').read_text())
            self.assertFalse(settings['acp']['auto_approve'])
            values = ['日本語 path', 'a&b', 'C:\\Program Files\\Agent']
            output = runtime.execute([sys.executable, '-X', 'utf8', '-c', 'import json,sys; print(json.dumps(sys.argv[1:]))', *values], home, env)
            self.assertEqual(json.loads(output), values)
        self.assertFalse(home.exists())
        self.assertEqual(os.environ.get('HOME'), actual_home)
        self.assertEqual(os.environ.get('TERRAIN_REGISTRY_FILE'), actual_registry)

    @unittest.skipIf(runtime.WINDOWS, 'POSIX nested process group; Windows uses Job Object')
    def test_timeout_kills_acp_with_separate_process_group(self):
        import time
        ready = self.base / 'ready'
        escaped = self.base / 'escaped'
        child = ('import os,signal,time; from pathlib import Path; os.setsid(); '
                 'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
                 f'Path({str(ready)!r}).write_text("ready"); time.sleep(3); '
                 f'Path({str(escaped)!r}).write_text("escaped")')
        parent = 'import subprocess,sys,time; ' + f'subprocess.Popen([sys.executable,"-c",{child!r}]); time.sleep(30)'
        with self.assertRaises(aidev.Problem):
            runtime.execute([sys.executable, '-c', parent], self.base, timeout=1, log=self.base / 'timeout.log')
        self.assertTrue(ready.is_file())
        time.sleep(3)
        self.assertFalse(escaped.exists())

    def test_stale_context_does_not_block_current_pack_tools(self):
        self.init(build_context=True)
        (self.root / 'code.py').write_text('changed')
        self.init(refresh=True)
        args = argparse.Namespace(tool='grep-pack', pattern='changed', context=2, limit=20)
        self.assertIn('changed', provider.read_tool(self.root, args))
        with self.assertRaises(aidev.Problem):
            provider.read_tool(self.root, argparse.Namespace(tool='read-context'))

    def test_cli_help_and_invalid_flags(self):
        for args in (['terrain'], ['terrain', 'init'], ['terrain', 'refresh'], ['terrain', 'doctor'], ['terrain', 'tools', 'grep-pack']):
            result = subprocess.run([sys.executable, '-B', str(install.SOURCE / 'aidev.py'), *args, '--help'], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, '-B', str(install.SOURCE / 'aidev.py'), 'terrain', 'init', '--allow-llm'], capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
