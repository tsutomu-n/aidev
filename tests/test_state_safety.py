"""Regression coverage for input preservation and index receipt validation.

Git, configuration files, pickle caches and SQLite files are real disposable
fixtures. Only the separately installed analysis providers are substituted.
"""
from contextlib import closing, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import pickle
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import aidev


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mode)
            for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


class StateSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.bins = {name: name for name in aidev.PROVIDERS}
        self.enterContext(patch.object(aidev, "foundation", return_value=self.bins))
        self.enterContext(patch.object(aidev, "provider_python", return_value=Path(sys.executable)))
        self.enterContext(patch.object(aidev, "probe", side_effect=self.probe))
        self.enterContext(redirect_stdout(StringIO()))
        self.calls = []
        original = aidev.run

        def run(argv, root, **kwargs):
            name = "crg" if any(str(arg).endswith("provider_build.py") for arg in argv) else str(argv[0])
            if name not in self.bins:
                return original(argv, root, **kwargs)
            self.calls.append(name)
            if name == "serena":
                for filename in ("document_symbols.pkl", "raw_document_symbols.pkl"):
                    path = root / ".serena/cache/python" / filename
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(pickle.dumps({"answer": "symbols"}))
            elif name == "graphify":
                self.write("graphify-out/graph.json", '{"nodes":[{"id":"one"}],"edges":[]}')
            elif name == "crg":
                path = root / ".code-review-graph/graph.db"
                path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(path)) as conn:
                    conn.execute("CREATE TABLE IF NOT EXISTS nodes (id INTEGER PRIMARY KEY)")
                    conn.execute("CREATE TABLE IF NOT EXISTS edges (id INTEGER PRIMARY KEY)")
                    conn.execute("INSERT OR IGNORE INTO nodes VALUES (1)")
                    conn.commit()
                return 'AIDEV_CRG_RESULT={"status":"ok","errors":[],"warnings":[]}\n'
            return "Indexed files per language: python=1\n"
        self.enterContext(patch.object(aidev, "run", side_effect=run))

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def probe(self, bins, provider, root, languages=()):
        if provider == "graphify":
            return {"code_extensions": [".py"], "code_names": []}
        if provider == "crg":
            return {"code_extensions": [".py"], "data_dir": str(root / ".code-review-graph")}
        project = root / ".serena/project.yml"
        runtime = root / ".serena/runtime/serena_config.yml"
        return {"project": json.loads(project.read_text()) if project.exists() else
                {"project_name": root.name, "language_servers": list(languages)},
                "runtime": json.loads(runtime.read_text()) if runtime.exists() else {"projects": []}}

    def ready(self):
        self.write("code.py", "def answer(): return 42\n")
        self.assertEqual(aidev.initialize(self.root)["status"], "LOCAL_READY")
        return aidev.state_read(self.root)

    def store(self, value):
        self.write(".aidev/state.json", json.dumps(value))

    def test_healthy_receipts_are_reused_and_doctor_is_readonly(self):
        state = self.ready()
        before = snapshot(self.root)
        self.assertEqual(aidev.doctor(self.root)["status"], "LOCAL_READY")
        self.assertEqual(aidev.initialize(self.root)["indexes"], "再利用")
        self.assertEqual(self.calls, list(aidev.PROVIDERS))
        self.assertEqual(aidev.state_read(self.root), state)
        self.assertEqual(snapshot(self.root), before)

    def test_absent_legacy_metadata_remains_compatible_without_fabricated_receipts(self):
        state = self.ready()
        state.pop("index_metadata")
        self.store(state)
        before = snapshot(self.root)
        report = aidev.doctor(self.root)
        self.assertEqual(report["status"], "LOCAL_READY")
        self.assertIsNone(report["providers"]["serena"]["built_at"])
        self.assertEqual(aidev.initialize(self.root)["indexes"], "再利用")
        self.assertEqual(snapshot(self.root), before)

    def test_empty_metadata_is_not_legacy_and_is_rebuilt(self):
        state = self.ready()
        state["index_metadata"] = {}
        self.store(state)
        before = snapshot(self.root)
        self.assertEqual(aidev.doctor(self.root)["status"], "NEEDS_INIT")
        self.assertEqual(snapshot(self.root), before)
        aidev.initialize(self.root)
        self.assertEqual(self.calls.count("serena"), 2)
        self.assertEqual(aidev.doctor(self.root)["status"], "LOCAL_READY")

    def test_missing_provider_receipt_is_not_silently_accepted(self):
        state = self.ready()
        state["index_metadata"].pop("serena")
        self.store(state)
        report = aidev.doctor(self.root)
        self.assertEqual(report["status"], "NEEDS_INIT")
        self.assertEqual(report["providers"]["serena"]["status"], "NEEDS_INIT")
        self.assertEqual(report["providers"]["graphify"]["status"], "READY")

    def test_empty_provider_receipt_is_not_silently_accepted(self):
        state = self.ready()
        state["index_metadata"]["serena"] = {}
        self.store(state)
        self.assertEqual(aidev.doctor(self.root)["status"], "NEEDS_INIT")
        aidev.initialize(self.root)
        self.assertEqual(self.calls.count("serena"), 2)

    def test_malformed_metadata_container_is_rejected_without_writes(self):
        state = self.ready()
        for value in (None, [], False, "broken", 1):
            with self.subTest(value=value):
                state["index_metadata"] = value
                self.store(state)
                before = snapshot(self.root)
                with self.assertRaises(aidev.Problem):
                    aidev.doctor(self.root)
                self.assertEqual(snapshot(self.root), before)

    def test_malformed_provider_receipt_is_rejected_without_writes(self):
        state = self.ready()
        for value in (None, [], False, "broken", 1):
            with self.subTest(value=value):
                state["index_metadata"]["serena"] = value
                self.store(state)
                before = snapshot(self.root)
                with self.assertRaises(aidev.Problem):
                    aidev.doctor(self.root)
                self.assertEqual(snapshot(self.root), before)

    def test_invalid_root_or_schema_is_reported_as_problem(self):
        for value in ([], None, False, 1, "state", {"schema_version": True}, {"schema_version": 1.0}):
            with self.subTest(value=value):
                self.store(value)
                before = snapshot(self.root)
                with self.assertRaises(aidev.Problem):
                    aidev.state_read(self.root)
                self.assertEqual(snapshot(self.root), before)

    def test_invalid_artifacts_container_is_rejected(self):
        state = self.ready()
        state["artifacts"] = ["not an object"]
        self.store(state)
        with self.assertRaises(aidev.Problem):
            aidev.state_read(self.root)

    def test_metadata_match_accepts_only_absence_as_legacy(self):
        self.assertTrue(aidev.metadata_matches(None, "serena", "input", "output"))
        for value in ({}, [], False, 0, ""):
            with self.subTest(value=value):
                self.assertFalse(aidev.metadata_matches(value, "serena", "input", "output"))

    def test_malformed_graphify_container_is_reported_without_traceback_or_writes(self):
        self.ready()
        for value in ([], None, 1, "graph"):
            with self.subTest(value=value):
                self.write("graphify-out/graph.json", json.dumps(value))
                before = snapshot(self.root)
                with self.assertRaises(aidev.Problem):
                    aidev.artifacts(self.root, ["python"])
                self.assertEqual(snapshot(self.root), before)

    def test_cli_json_error_for_malformed_state_is_parseable_and_readonly(self):
        self.ready()
        self.store([])
        before = snapshot(self.root)
        output = StringIO()
        with patch.object(aidev, "repo_root", return_value=self.root), redirect_stdout(output):
            code = aidev.main(["doctor", "--json"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "ERROR")
        self.assertIs(json.loads(output.getvalue())["writes"], False)
        self.assertEqual(snapshot(self.root), before)

    def test_configuration_edit_during_planning_cannot_be_rebased_away(self):
        for filename, initial, concurrent in (
            (".codex/config.toml", '# original\nmodel="old"\n', '# user edit\nmodel="new"\n'),
            (".codex/dev-capabilities.json", '{"schema_version":1,"capabilities":{}}',
             '{"schema_version":1,"capabilities":{"custom":["custom-provider"]}}'),
            ("AGENTS.md", "# Original rules\n", "# New user rules\n"),
        ):
            with self.subTest(filename=filename):
                self.write(filename, initial)
                real_read = aidev.read
                seen = False
                def read(root, relative):
                    nonlocal seen
                    raw = real_read(root, relative)
                    if relative == filename and not seen:
                        seen = True
                        self.write(filename, concurrent)
                    return raw
                with patch.object(aidev, "read", side_effect=read):
                    changes, before, _ = aidev.plan(self.root, self.bins, [])
                unchanged = snapshot(self.root)
                with self.assertRaises(aidev.Problem):
                    aidev.apply(self.root, changes, before)
                self.assertEqual(snapshot(self.root), unchanged)
                self.assertEqual((self.root / filename).read_text(), concurrent)

    def test_new_override_after_planning_is_preserved_before_any_write(self):
        self.write("AGENTS.md", "# User rules\n")
        changes, before, _ = aidev.plan(self.root, self.bins, [])
        self.write("AGENTS.override.md", "# Newly effective rules\n")
        unchanged = snapshot(self.root)
        with self.assertRaises(aidev.Problem):
            aidev.apply(self.root, changes, before)
        self.assertEqual(snapshot(self.root), unchanged)

    def test_existing_manual_settings_are_not_claimed_by_a_noop(self):
        self.write(".codex/config.toml", "\n".join(aidev.mcp_sections().values()))
        changes, before, _ = aidev.plan(self.root, self.bins, [])
        self.assertNotIn(".codex/config.toml", changes)
        self.assertIsNotNone(before[".codex/config.toml"])

    def test_backup_records_before_hash_but_does_not_claim_a_whole_directory(self):
        original = b'# user setting\nmodel="custom"\n'
        self.write(".codex/config.toml", original.decode())
        result = aidev.initialize(self.root)
        backup = Path(result["backup"])
        receipt = json.loads((backup / "changes.json").read_text())
        entry = receipt[".codex/config.toml"]
        self.assertEqual(entry["before_sha256"], aidev.digest(original))
        self.assertEqual((backup / ".codex/config.toml").read_bytes(), original)
        self.assertIsNone(receipt["AGENTS.md"]["before_sha256"])
        self.assertNotIn(".serena", receipt)


if __name__ == "__main__":
    unittest.main()
