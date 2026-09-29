"""Integration safety gaps: tracking, concurrent writers and abrupt termination."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SOURCE))
import aidev
import ownership
import terrain_provider


class RemovalSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def put(self, name, raw):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def owned(self, name='.terrain/aidev.json', raw=b'owned'):
        self.put(name, raw)
        ownership.record_file(self.root, 'terrain', name, None, raw)

    def test_tracked_json_container_survives_last_member_removal(self):
        name = '.codex/dev-capabilities.json'
        self.put(name, b'{"schema_version":1,"capabilities":{"symbol_semantics":["serena"]}}')
        ownership.record_json_members(self.root, 'core', name, None, {'/capabilities/symbol_semantics': ['serena']})
        subprocess.run(['git', '-C', str(self.root), 'add', name], check=True)
        index = (self.root / '.git/index').read_bytes()
        self.assertEqual(ownership.remove(self.root)['status'], 'REMOVED')
        self.assertEqual(json.loads((self.root / name).read_bytes()), {'schema_version': 1, 'capabilities': {}})
        self.assertEqual((self.root / '.git/index').read_bytes(), index)

    def test_concurrent_ledger_change_before_first_write_is_preserved(self):
        self.owned()
        original = ownership._classify
        replacement = b'{"user":"concurrent ledger bytes"}'
        def classify(root, entry):
            result = original(root, entry)
            self.put(ownership.LEDGER, replacement)
            return result
        with patch.object(ownership, '_classify', side_effect=classify):
            result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'ERROR')
        self.assertFalse(result['writes'])
        self.assertEqual((self.root / '.terrain/aidev.json').read_bytes(), b'owned')
        self.assertEqual((self.root / ownership.LEDGER).read_bytes(), replacement)

    def test_concurrent_ledger_change_after_mutation_stops_without_overwrite(self):
        self.owned()
        original = ownership.RemovalJournal.changed
        replacement = b'{"user":"changed after unlink"}'
        def changed(journal, name):
            original(journal, name)
            self.put(ownership.LEDGER, replacement)
        with patch.object(ownership.RemovalJournal, 'changed', changed):
            result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'ERROR')
        self.assertTrue(result['writes'])
        self.assertEqual((self.root / ownership.LEDGER).read_bytes(), replacement)
        self.assertEqual((Path(result['recovery_backup']) / 'before/.terrain/aidev.json').read_bytes(), b'owned')
        self.assertEqual(result['pending_action']['path'], '.terrain/aidev.json')

    def test_legacy_managed_block_change_after_classification_is_preserved(self):
        self.put('AGENTS.md', aidev.CODE_GUIDANCE.encode())
        original = ownership._legacy
        changed = aidev.CODE_GUIDANCE.replace('## aidev', '## User aidev').encode()
        def legacy(root, terrain_only):
            result = original(root, terrain_only)
            self.put('AGENTS.md', changed)
            return result
        with patch.object(ownership, '_legacy', side_effect=legacy):
            result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'ERROR')
        self.assertFalse(result['writes'])
        self.assertEqual((self.root / 'AGENTS.md').read_bytes(), changed)

    def test_tree_concurrent_child_change_preserves_new_bytes_and_recovery(self):
        self.put('graphify-out/a.json', b'a')
        self.put('graphify-out/b.json', b'b')
        ownership.record_tree(self.root, 'core', 'graphify-out', False, component='core.graphify')
        original = ownership.RemovalJournal.changed
        modified = []
        def changed(journal, name):
            original(journal, name)
            if not modified:
                other = next((self.root / 'graphify-out').iterdir())
                other.write_bytes(b'user concurrent edit')
                modified.append(other)
        with patch.object(ownership.RemovalJournal, 'changed', changed):
            result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'ERROR')
        self.assertEqual(modified[0].read_bytes(), b'user concurrent edit')
        recovery = Path(result['recovery_backup'])
        self.assertEqual((recovery / 'before/graphify-out/a.json').read_bytes(), b'a')
        self.assertEqual((recovery / 'before/graphify-out/b.json').read_bytes(), b'b')
        self.assertEqual(ownership.remove(self.root)['status'], 'REMOVED_WITH_PRESERVED')
        self.assertEqual(modified[0].read_bytes(), b'user concurrent edit')

    def test_process_exit_keeps_pending_journal_and_retry_chain(self):
        self.owned()
        script = """import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import ownership
ownership._save=lambda *args: os._exit(77)
ownership.remove(Path(sys.argv[2]))
"""
        process = subprocess.run([sys.executable, '-B', '-c', script, str(SOURCE), str(self.root)])
        self.assertEqual(process.returncode, 77)
        pointer = (self.root / ownership.PROGRESS).read_bytes()
        recovery = Path(json.loads(pointer)['recovery_backup'])
        journal = json.loads((recovery / 'journal.json').read_bytes())
        self.assertEqual(journal['status'], 'in_progress')
        self.assertEqual(journal['pending']['path'], '.terrain/aidev.json')
        self.assertEqual(journal['changed_paths'], ['.terrain/aidev.json'])
        self.assertEqual((recovery / 'before/.terrain/aidev.json').read_bytes(), b'owned')
        self.put('.terrain/aidev.json', b'user recreated after crash')
        result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'REMOVED_WITH_PRESERVED')
        self.assertEqual((self.root / '.terrain/aidev.json').read_bytes(), b'user recreated after crash')
        self.assertEqual((Path(result['recovery_backup']) / 'previous-progress.json').read_bytes(), pointer)
        self.assertEqual((recovery / 'before/.terrain/aidev.json').read_bytes(), b'owned')

    def test_invalid_ledger_rejects_init_before_provider_or_configuration_write(self):
        self.put(ownership.LEDGER, b'{"invalid":true}')
        for module, provider in ((aidev, 'foundation'), (terrain_provider.runtime, 'load_runtime')):
            with self.subTest(provider=provider), patch.object(module, provider) as invoke:
                with self.assertRaises(ownership.OwnershipError):
                    if provider == 'foundation':
                        aidev.initialize(self.root)
                    else:
                        terrain_provider.initialize(self.root)
                invoke.assert_not_called()
                self.assertEqual((self.root / ownership.LEDGER).read_bytes(), b'{"invalid":true}')
                self.assertFalse((self.root / 'AGENTS.md').exists())

    def test_unrecognized_progress_file_is_preserved_without_mutation(self):
        self.owned()
        self.put(ownership.PROGRESS, b'{"user":"notes"}')
        result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'ERROR')
        self.assertFalse(result['writes'])
        self.assertEqual((self.root / ownership.PROGRESS).read_bytes(), b'{"user":"notes"}')
        self.assertTrue((self.root / '.terrain/aidev.json').exists())

    def test_tracked_ledger_is_preserved_without_mutation(self):
        self.owned()
        subprocess.run(['git', '-C', str(self.root), 'add', '-f', ownership.LEDGER], check=True)
        before = (self.root / ownership.LEDGER).read_bytes()
        result = ownership.remove(self.root)
        self.assertEqual(result['status'], 'ERROR')
        self.assertFalse(result['writes'])
        self.assertEqual((self.root / ownership.LEDGER).read_bytes(), before)
        self.assertTrue((self.root / '.terrain/aidev.json').exists())


if __name__ == '__main__':
    unittest.main()
