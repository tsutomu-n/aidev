"""Repository removal contracts using disposable Git repositories."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import ownership


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class RemoveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def put(self, name, raw):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def test_owned_file_dry_run_is_read_only_and_remove_is_idempotent(self):
        self.put('.aidev/state.json', b'owned')
        ownership.record_file(self.root, 'core', '.aidev/state.json', None, b'owned')
        before = (self.root / '.aidev/ownership.json').read_bytes()
        result = ownership.remove(self.root, dry_run=True)
        self.assertEqual(result['status'], 'REMOVE_READY')
        self.assertEqual(before, (self.root / '.aidev/ownership.json').read_bytes())
        self.assertTrue((self.root / '.aidev/state.json').exists())
        self.assertEqual(ownership.remove(self.root)['status'], 'REMOVED')
        self.assertFalse((self.root / '.aidev/state.json').exists())
        self.assertEqual(ownership.remove(self.root)['status'], 'NOT_INSTALLED')

    def test_interrupted_restore_resumes_after_origin_written(self):
        self.put('.serena/project.yml', b'owned')
        self.put('.aidev/backups/one/.serena/project.yml', b'origin')
        ownership.record_file(self.root, 'core', '.serena/project.yml', b'origin', b'owned', '.aidev/backups/one/.serena/project.yml', component='core.serena')
        self.put('.serena/project.yml', b'origin')  # process stopped after restore, before ledger update
        self.assertEqual(ownership.remove(self.root)['status'], 'REMOVED')
        self.assertEqual((self.root / '.serena/project.yml').read_bytes(), b'origin')

    def test_modified_file_is_preserved_with_ledger(self):
        self.put('.aidev/state.json', b'owned')
        ownership.record_file(self.root, 'core', '.aidev/state.json', None, b'owned')
        self.put('.aidev/state.json', b'user')
        result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'REMOVED_WITH_PRESERVED')
        self.assertEqual((self.root / '.aidev/state.json').read_bytes(), b'user')
        self.assertTrue((self.root / '.aidev/ownership.json').exists())

    def test_block_subtraction_preserves_outside_edits(self):
        block = b'<!-- aidev:code-intelligence:start -->\nowned\n<!-- aidev:code-intelligence:end -->'
        self.put('AGENTS.md', b'prefix\n' + block + b'\nsuffix\n')
        ownership.record_block(self.root, 'core', 'AGENTS.md', '<!-- aidev:code-intelligence:start -->', '<!-- aidev:code-intelligence:end -->', block)
        self.put('AGENTS.md', b'user prefix\n' + block + b'\nsuffix\n')
        self.assertEqual(ownership.remove(self.root)['status'], 'REMOVED')
        self.assertIn(b'user prefix', (self.root / 'AGENTS.md').read_bytes())
        self.assertNotIn(b'owned', (self.root / 'AGENTS.md').read_bytes())

    def test_crlf_managed_block_preserves_surrounding_bytes(self):
        block = b'# aidev:core:.gitignore:start\r\nowned\r\n# aidev:core:.gitignore:end'
        self.put('.gitignore', b'user\r\n' + block + b'\r\nend\r\n')
        ownership.record_block(self.root, 'core', '.gitignore', '# aidev:core:.gitignore:start', '# aidev:core:.gitignore:end', block)
        self.assertEqual(ownership.remove(self.root)['status'], 'REMOVED')
        self.assertEqual((self.root / '.gitignore').read_bytes(), b'user\r\n\r\nend\r\n')

    def test_reencoded_managed_block_is_preserved(self):
        block = b'<!-- aidev:code-intelligence:start -->\nowned\n<!-- aidev:code-intelligence:end -->'
        self.put('AGENTS.md', block + b'\n')
        ownership.record_block(self.root, 'core', 'AGENTS.md', '<!-- aidev:code-intelligence:start -->',
                               '<!-- aidev:code-intelligence:end -->', block)
        rewritten = (block + b'\nUser note\n').replace(b'\n', b'\r\n')
        self.put('AGENTS.md', rewritten)
        result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'REMOVED_WITH_PRESERVED')
        self.assertEqual((self.root / 'AGENTS.md').read_bytes(), rewritten)

    def test_json_members_preserve_user_keys(self):
        self.put('.codex/dev-capabilities.json', b'{"capabilities":{"symbol_semantics":["serena"],"user":1}}\n')
        ownership.record_json_members(self.root, 'core', '.codex/dev-capabilities.json', None, {'/capabilities/symbol_semantics': ['serena']})
        result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'REMOVED')
        data = json.loads((self.root / '.codex/dev-capabilities.json').read_bytes())
        self.assertEqual(data['capabilities'], {'user': 1})

    def test_terrain_only_remove_leaves_core_block_and_file(self):
        core = b'<!-- aidev:code-intelligence:start -->core<!-- aidev:code-intelligence:end -->'
        terrain = b'<!-- aidev:terrain:start -->terrain<!-- aidev:terrain:end -->'
        self.put('AGENTS.md', core + b'\n' + terrain)
        ownership.record_block(self.root, 'core', 'AGENTS.md', '<!-- aidev:code-intelligence:start -->', '<!-- aidev:code-intelligence:end -->', core)
        ownership.record_block(self.root, 'terrain', 'AGENTS.md', '<!-- aidev:terrain:start -->', '<!-- aidev:terrain:end -->', terrain)
        self.put('.aidev/state.json', b'core')
        self.put('.terrain/aidev.json', b'terrain')
        ownership.record_file(self.root, 'core', '.aidev/state.json', None, b'core')
        ownership.record_file(self.root, 'terrain', '.terrain/aidev.json', None, b'terrain')
        self.assertEqual(ownership.remove(self.root, terrain_only=True)['status'], 'REMOVED')
        self.assertIn(core, (self.root / 'AGENTS.md').read_bytes())
        self.assertNotIn(terrain, (self.root / 'AGENTS.md').read_bytes())
        self.assertTrue((self.root / '.aidev/state.json').exists())
        self.assertFalse((self.root / '.terrain/aidev.json').exists())

    def test_large_generated_file_uses_streaming_hash(self):
        self.put('.terrain/agent/repomix.md', b'x' * (21 * 1024 * 1024))
        ownership.record_generated_file(self.root, 'terrain', '.terrain/agent/repomix.md', None, component='terrain.local')
        plan = ownership.remove(self.root, dry_run=True, terrain_only=True)
        self.assertEqual(plan['status'], 'REMOVE_READY')
        self.assertEqual(ownership.remove(self.root, terrain_only=True)['status'], 'REMOVED')
        self.assertFalse((self.root / '.terrain/agent/repomix.md').exists())

    def test_tree_with_unknown_child_or_tracked_file_is_preserved(self):
        self.put('graphify-out/graph.json', b'owned')
        ownership.record_tree(self.root, 'core', 'graphify-out', False, component='core.graphify')
        self.put('graphify-out/user.txt', b'user')
        self.assertEqual(ownership.remove(self.root)['status'], 'REMOVED_WITH_PRESERVED')
        self.assertTrue((self.root / 'graphify-out/graph.json').exists())

    def test_reinit_does_not_claim_user_child(self):
        self.put('graphify-out/graph.json', b'first')
        ownership.record_tree(self.root, 'core', 'graphify-out', False, component='core.graphify')
        self.put('graphify-out/notes.md', b'user notes')
        before = ownership._tree(self.root, 'graphify-out')
        self.put('graphify-out/graph.json', b'second')
        ownership.record_tree(self.root, 'core', 'graphify-out', False, component='core.graphify', before_identity=before)
        result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'REMOVED_WITH_PRESERVED')
        self.assertEqual((self.root / 'graphify-out/notes.md').read_bytes(), b'user notes')

    def test_modified_guidance_is_rejected_before_reinit(self):
        import aidev
        self.put('AGENTS.md', aidev.CODE_GUIDANCE.encode())
        ownership.record_block(self.root, 'core', 'AGENTS.md', aidev.CODE_START, aidev.CODE_END, aidev.CODE_GUIDANCE.encode())
        edited = aidev.CODE_GUIDANCE.replace('## aidev コード調査', '## user edited')
        self.put('AGENTS.md', edited.encode())
        with self.assertRaises(aidev.Problem):
            aidev.code_guidance(edited.encode(), self.root, 'AGENTS.md')
        self.assertEqual((self.root / 'AGENTS.md').read_bytes(), edited.encode())

    def test_shared_guidance_removes_each_block_without_resurrection(self):
        import aidev
        import terrain_provider
        for order in (('core', 'terrain'), ('terrain', 'core')):
            with self.subTest(order=order):
                with tempfile.TemporaryDirectory() as folder:
                    root = Path(folder).resolve()
                    subprocess.run(['git', 'init', '-q', str(root)], check=True)
                    blocks = {'core': (aidev.CODE_START, aidev.CODE_END, aidev.CODE_GUIDANCE.encode()),
                              'terrain': (terrain_provider.START, terrain_provider.END, terrain_provider.GUIDANCE.encode())}
                    path = root / 'AGENTS.md'
                    for scope in order:
                        before = path.read_bytes() if path.exists() else None
                        start, end, block = blocks[scope]
                        after = (before or b'') + block + b'\n'
                        path.write_bytes(after)
                        backup = None
                        if before is not None:
                            backup = f'.aidev/{scope}/backups/one/AGENTS.md' if scope == 'terrain' else '.aidev/backups/one/AGENTS.md'
                            if scope == 'terrain':
                                backup = '.aidev/terrain/backups/one/AGENTS.md'
                            saved = root / backup
                            saved.parent.mkdir(parents=True, exist_ok=True)
                            saved.write_bytes(before)
                        ownership.record_block(root, scope, 'AGENTS.md', start, end, block,
                                               origin_existed=before is not None, before=before, backup=backup)
                    path.write_bytes(path.read_bytes() + b'user note\n')
                    self.assertEqual(ownership.remove(root, terrain_only=True)['status'], 'REMOVED')
                    self.assertIn(aidev.CODE_GUIDANCE.encode(), path.read_bytes())
                    self.assertNotIn(terrain_provider.GUIDANCE.encode(), path.read_bytes())
                    self.assertIn(b'user note', path.read_bytes())
                    self.assertEqual(ownership.remove(root)['status'], 'REMOVED')
                    self.assertNotIn(aidev.CODE_GUIDANCE.encode(), path.read_bytes())
                    self.assertIn(b'user note', path.read_bytes())

    def test_retained_local_child_keeps_git_ignore(self):
        marker = '# aidev:core:.gitignore:start'
        block = (marker + '\n/.aidev/\n# aidev:core:.gitignore:end').encode()
        self.put('.gitignore', block + b'\n')
        ownership.record_block(self.root, 'core', '.gitignore', marker, '# aidev:core:.gitignore:end', block, origin_existed=False)
        self.put('.aidev/private.txt', b'user data')
        before = subprocess.run(['git', 'check-ignore', '-q', '--', '.aidev/private.txt'], cwd=self.root).returncode
        result = ownership.remove(self.root)
        after = subprocess.run(['git', 'check-ignore', '-q', '--', '.aidev/private.txt'], cwd=self.root).returncode
        self.assertEqual((before, after), (0, 0))
        self.assertEqual(result['status'], 'REMOVED_WITH_PRESERVED')
        self.assertEqual((self.root / '.aidev/private.txt').read_bytes(), b'user data')

    def test_forged_managed_hash_cannot_delete_application_file(self):
        self.put('.aidev/state.json', b'owned')
        ownership.record_file(self.root, 'core', '.aidev/state.json', None, b'owned')
        data = json.loads((self.root / '.aidev/ownership.json').read_bytes())
        original = data['components']['core']['entries'].pop('file:.aidev/state.json')
        for name in ('src/business.py', 'README.md'):
            self.put(name, b'owned')
            forged = {**original, 'path': name}
            data['components']['core']['entries']['file:' + name] = forged
            self.put('.aidev/ownership.json', json.dumps(data).encode())
            self.assertEqual(ownership.remove(self.root)['status'], 'ERROR')
            self.assertEqual((self.root / name).read_bytes(), b'owned')
            del data['components']['core']['entries']['file:' + name]

    def test_partial_write_reports_writes_and_keeps_unfinished_receipt(self):
        self.put('.aidev/state.json', b'core')
        self.put('.terrain/aidev.json', b'terrain')
        ownership.record_file(self.root, 'core', '.aidev/state.json', None, b'core')
        ownership.record_file(self.root, 'terrain', '.terrain/aidev.json', None, b'terrain')
        with patch.object(ownership, '_save', side_effect=OSError('fixture interruption')):
            result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'ERROR')
        self.assertTrue(result['writes'])
        self.assertFalse((self.root / '.terrain/aidev.json').exists())
        self.assertTrue((self.root / '.aidev/ownership.json').exists())

    def test_interrupted_tree_delete_reports_partial_write(self):
        self.put('graphify-out/one.json', b'one')
        self.put('graphify-out/two.json', b'two')
        ownership.record_tree(self.root, 'core', 'graphify-out', False, component='core.graphify')
        original = Path.unlink
        removed = []
        def interrupt(path, *args, **kwargs):
            if path.parent == self.root / 'graphify-out':
                if removed:
                    raise OSError('fixture concurrent writer')
                removed.append(path.name)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', interrupt):
            result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'ERROR')
        self.assertTrue(result['writes'])
        self.assertEqual(len(removed), 1)
        self.assertTrue((self.root / '.aidev/ownership.json').exists())

    def test_hardlink_and_symlink_tree_are_preserved(self):
        self.put('.aidev/state.json', b'owned')
        ownership.record_file(self.root, 'core', '.aidev/state.json', None, b'owned')
        (self.root / 'other.txt').hardlink_to(self.root / '.aidev/state.json')
        self.put('graphify-out/graph.json', b'graph')
        ownership.record_tree(self.root, 'core', 'graphify-out', False, component='core.graphify')
        (self.root / 'graphify-out/link').symlink_to('graph.json')
        result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'REMOVED_WITH_PRESERVED')
        self.assertTrue((self.root / '.aidev/state.json').exists())
        self.assertTrue((self.root / 'graphify-out/link').is_symlink())

    def test_invalid_ledger_and_link_never_delete(self):
        self.put('.aidev/state.json', b'owned')
        ownership.record_file(self.root, 'core', '.aidev/state.json', None, b'owned')
        (self.root / '.aidev/state.json').unlink()
        (self.root / '.aidev/state.json').symlink_to('elsewhere')
        self.assertEqual(ownership.remove(self.root)['status'], 'REMOVED_WITH_PRESERVED')
        self.assertTrue((self.root / '.aidev/state.json').is_symlink())
        data = json.loads((self.root / '.aidev/ownership.json').read_bytes())
        data['repo_path'] = '/elsewhere'
        self.put('.aidev/ownership.json', json.dumps(data).encode())
        self.assertEqual(ownership.remove(self.root, dry_run=True)['status'], 'ERROR')

    def test_legacy_never_infers_directory_from_path(self):
        self.put('graphify-out/graph.json', b'owned')
        self.put('.aidev/state.json', b'{}')
        result = ownership.remove(self.root, dry_run=True)
        self.assertEqual(result['status'], 'REMOVE_PARTIAL')
        self.assertTrue((self.root / 'graphify-out/graph.json').exists())

class CliRemoveTests(unittest.TestCase):
    setUp = RemoveTests.setUp
    put = RemoveTests.put
    def test_remove_rejects_force(self):
        entry = Path(__file__).resolve().parents[1] / 'src/aidev.py'
        for command in (['remove', '--force'], ['terrain', 'remove', '--force']):
            run = subprocess.run([sys.executable, '-B', str(entry), *command], cwd=self.root, capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertIn('unrecognized arguments', run.stderr)

    def test_cli_dry_run_does_not_need_provider(self):
        self.put('.aidev/state.json', b'owned')
        ownership.record_file(self.root, 'core', '.aidev/state.json', None, b'owned')
        before = (self.root / '.aidev/ownership.json').read_bytes()
        entry = Path(__file__).resolve().parents[1] / 'src/aidev.py'
        run = subprocess.run([sys.executable, '-B', str(entry), 'remove', '--dry-run', '--json'], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)['status'], 'REMOVE_READY')
        self.assertEqual((self.root / '.aidev/ownership.json').read_bytes(), before)

    def test_legacy_two_blocks_in_one_file(self):
        import aidev
        import terrain_provider
        self.put('AGENTS.md', aidev.CODE_GUIDANCE.encode() + b'\n' + terrain_provider.GUIDANCE.encode())
        self.assertEqual(ownership.remove(self.root)['status'], 'REMOVED')
        self.assertNotIn(b'aidev:', (self.root / 'AGENTS.md').read_bytes())

    def test_tracked_derived_tree_is_preserved(self):
        self.put('graphify-out/graph.json', b'owned')
        ownership.record_tree(self.root, 'core', 'graphify-out', False, component='core.graphify')
        subprocess.run(['git', '-C', str(self.root), 'add', '-f', 'graphify-out/graph.json'], check=True)
        result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'REMOVED_WITH_PRESERVED')
        self.assertTrue((self.root / 'graphify-out/graph.json').exists())

    def test_tracked_new_file_and_guidance_path_are_preserved(self):
        self.put('.terrain/aidev.json', b'owned')
        ownership.record_file(self.root, 'terrain', '.terrain/aidev.json', None, b'owned')
        block = b'<!-- aidev:code-intelligence:start -->owned<!-- aidev:code-intelligence:end -->'
        self.put('AGENTS.md', block + b'\n')
        ownership.record_block(self.root, 'core', 'AGENTS.md', '<!-- aidev:code-intelligence:start -->',
                               '<!-- aidev:code-intelligence:end -->', block, origin_existed=False)
        subprocess.run(['git', '-C', str(self.root), 'add', '-f', '.terrain/aidev.json', 'AGENTS.md'], check=True)
        result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'REMOVED_WITH_PRESERVED')
        self.assertEqual((self.root / '.terrain/aidev.json').read_bytes(), b'owned')
        self.assertEqual((self.root / 'AGENTS.md').read_bytes(), b'\n')
        self.assertTrue((self.root / '.aidev/ownership.json').exists())

    def test_legacy_exact_guidance_only(self):
        import aidev
        self.put('AGENTS.md', b'user\n' + aidev.CODE_GUIDANCE.encode() + b'\n')
        self.put('.aidev/state.json', b'{}')
        plan = ownership.remove(self.root, dry_run=True)
        self.assertEqual(plan['status'], 'REMOVE_PARTIAL')
        self.assertTrue(any(a['action'] == 'SAFE_SUBTRACT' for a in plan['actions']))
        self.assertEqual(ownership.remove(self.root)['status'], 'REMOVED_WITH_PRESERVED')
        self.assertEqual((self.root / 'AGENTS.md').read_bytes(), b'user\n\n')
