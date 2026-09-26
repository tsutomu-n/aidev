import importlib.util
from contextlib import closing
import json
import os
import pickle
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SOURCE))
spec = importlib.util.spec_from_file_location("aidev", SOURCE / "aidev.py")
aidev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aidev)


def snapshot(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode) for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


class InitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.bins = {name: name for name in aidev.PROVIDERS}
        self.patchers = [patch.object(aidev, "foundation", return_value=self.bins), patch.object(aidev, "probe", side_effect=self.probe), patch.object(aidev, "provider_python", return_value=Path(sys.executable))]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def write(self, name, value):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value)

    def probe(self, bins, provider, root, languages=()):
        if provider == "graphify":
            return {"code_extensions": sorted(aidev.CODE_EXTENSIONS | {".json", ".sql", ".sh"}), "code_names": ["pyproject.toml"]}
        if provider == "crg":
            return {"data_dir": str(root / ".code-review-graph"), "code_extensions": sorted(aidev.CODE_EXTENSIONS)}
        project = root / ".serena/project.yml"
        runtime = root / ".serena/runtime/serena_config.yml"
        return {"project": json.loads(project.read_text()) if project.exists() else {"project_name": root.name, "language_servers": list(languages)},
                "runtime": json.loads(runtime.read_text()) if runtime.exists() else {"projects": []}}

    def fake_build(self, fail=None):
        original = aidev.run
        calls = []

        def run(argv, root, **kwargs):
            provider = str(argv[0])
            if any(str(arg).endswith("provider_build.py") for arg in argv):
                provider = "crg"
            if provider not in self.bins:
                return original(argv, root, **kwargs)
            calls.append(provider)
            if provider == fail:
                raise aidev.Problem("test build failed")
            if provider == "serena":
                languages = json.loads((root / ".serena/project.yml").read_text())["language_servers"]
                for language in languages:
                    folder = root / ".serena/cache" / language
                    folder.mkdir(parents=True, exist_ok=True)
                    for name in ("document_symbols.pkl", "raw_document_symbols.pkl"):
                        (folder / name).write_bytes(pickle.dumps({"test": "symbols"}))
            if provider == "graphify":
                self.write("graphify-out/graph.json", '{"nodes":[{"id":"one"}],"edges":[]}')
            if provider == "crg":
                (root / ".code-review-graph").mkdir(exist_ok=True)
                with closing(sqlite3.connect(root / ".code-review-graph/graph.db")) as conn:
                    conn.execute("CREATE TABLE IF NOT EXISTS nodes (id INTEGER PRIMARY KEY)")
                    conn.execute("CREATE TABLE IF NOT EXISTS edges (id INTEGER PRIMARY KEY)")
                    conn.execute("INSERT OR IGNORE INTO nodes VALUES (1)")
                    conn.commit()
                return 'AIDEV_CRG_RESULT={"status":"ok","errors":[],"warnings":[]}\n'
            return "Indexed files per language: python=1\n"
        return patch.object(aidev, "run", side_effect=run), calls

    def test_dry_run_preserves_every_file(self):
        self.write("code.py", "x = 1\n")
        before = snapshot(self.root)
        result = aidev.initialize(self.root, dry_run=True)
        self.assertEqual(result["status"], "PLAN")
        self.assertEqual(snapshot(self.root), before)

    def test_empty_then_code_then_idempotent_and_doctor_readonly(self):
        result = aidev.initialize(self.root)
        self.assertEqual(result["status"], "WAITING_FOR_CODE")
        self.write("code.py", "def answer(): return 42\n")
        build, calls = self.fake_build()
        with build:
            result = aidev.initialize(self.root)
            self.assertEqual(result["status"], "LOCAL_READY")
            before = snapshot(self.root)
            self.assertEqual(aidev.doctor(self.root)["status"], "LOCAL_READY")
            self.assertEqual(snapshot(self.root), before)
            aidev.initialize(self.root)
            self.assertEqual(calls, ["serena", "graphify", "crg"])
            self.assertEqual(snapshot(self.root), before)

    def test_conflict_is_detected_before_any_write(self):
        self.write(".codex/config.toml", '[mcp_servers.serena]\ncommand="custom"\n')
        before = snapshot(self.root)
        with self.assertRaisesRegex(aidev.Problem, "衝突"):
            aidev.initialize(self.root)
        self.assertEqual(snapshot(self.root), before)

    def test_user_configuration_and_backup_are_preserved(self):
        text = '# user comment\nmodel = "custom-model"\n'
        self.write(".codex/config.toml", text)
        self.write(".gitignore", "# existing\nmy-output/\n")
        result = aidev.initialize(self.root)
        self.assertTrue((self.root / ".codex/config.toml").read_text().startswith(text))
        self.assertEqual((Path(result["backup"]) / ".codex/config.toml").read_text(), text)
        self.assertTrue((self.root / ".gitignore").read_text().startswith("# existing\nmy-output/\n"))

    def test_code_guidance_preserves_user_rules_and_is_idempotent(self):
        original = "# User rules\nKeep this instruction.\n"
        self.write("AGENTS.md", original)
        self.write("code.py", "def answer(): return 42\n")
        build, _ = self.fake_build()
        with build:
            result = aidev.initialize(self.root)
            text = (self.root / "AGENTS.md").read_text()
            self.assertTrue(text.startswith(original))
            self.assertEqual(text.count(aidev.CODE_START), 1)
            for name in ("Serena", "Graphify", "CRG"):
                self.assertIn(name, text)
            self.assertEqual((Path(result["backup"]) / "AGENTS.md").read_text(), original)
            aidev.initialize(self.root)
            self.assertEqual((self.root / "AGENTS.md").read_text(), text)

    def test_invalid_code_guidance_marker_stops_before_write(self):
        self.write("AGENTS.md", aidev.CODE_START + "\npartial\n")
        before = snapshot(self.root)
        with self.assertRaisesRegex(aidev.Problem, "AGENTS管理marker"):
            aidev.initialize(self.root)
        self.assertEqual(snapshot(self.root), before)

    def test_nonempty_override_receives_guidance_without_touching_agents(self):
        self.write("AGENTS.md", "# Existing root rules\n")
        self.write("AGENTS.override.md", "# Effective override\n")
        self.write("code.py", "def answer(): return 42\n")
        build, _ = self.fake_build()
        with build:
            result = aidev.initialize(self.root)
            self.assertEqual((self.root / "AGENTS.md").read_text(), "# Existing root rules\n")
            content = (self.root / "AGENTS.override.md").read_text()
            self.assertTrue(content.startswith("# Effective override\n"))
            self.assertEqual(content.count(aidev.CODE_START), 1)
            self.assertEqual((Path(result["backup"]) / "AGENTS.override.md").read_text(), "# Effective override\n")
            aidev.initialize(self.root)
            self.assertEqual((self.root / "AGENTS.override.md").read_text(), content)

    def test_empty_override_uses_agents(self):
        self.write("AGENTS.override.md", " \n")
        self.write("code.py", "def answer(): return 42\n")
        build, _ = self.fake_build()
        with build:
            aidev.initialize(self.root)
        self.assertEqual((self.root / "AGENTS.override.md").read_text(), " \n")
        self.assertIn(aidev.CODE_START, (self.root / "AGENTS.md").read_text())

    def test_explicit_disabled_policy_is_not_overwritten(self):
        self.write(".codex/dev-capabilities.json", json.dumps({"schema_version": 1, "capabilities": {"symbol_semantics": []}}))
        before = snapshot(self.root)
        with self.assertRaisesRegex(aidev.Problem, "衝突"):
            aidev.initialize(self.root)
        self.assertEqual(snapshot(self.root), before)

    def test_symlink_does_not_write_outside_repo(self):
        with tempfile.TemporaryDirectory() as outside:
            try:
                (self.root / ".codex").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                    self.skipTest("Windows symlink privilege unavailable; junction tested separately")
                raise
            with self.assertRaisesRegex(aidev.Problem, "symlink"):
                aidev.initialize(self.root)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_existing_serena_user_log_link_is_preserved(self):
        if aidev.WINDOWS:
            self.skipTest("Serena user-log symlink exception is Ubuntu-only")
        with tempfile.TemporaryDirectory() as home:
            logs = Path(home) / ".serena/logs"
            logs.mkdir(parents=True)
            link = self.root / ".serena/runtime/logs"
            link.parent.mkdir(parents=True)
            try:
                link.symlink_to(logs, target_is_directory=True)
            except OSError as exc:
                if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                    self.skipTest("Windows symlink privilege unavailable")
                raise
            self.write("code.py", "def answer(): return 42\n")
            build, _ = self.fake_build()
            with patch.object(aidev.Path, "home", return_value=Path(home)):
                self.assertEqual(aidev.initialize(self.root, dry_run=True)["status"], "PLAN")
                self.assertEqual(aidev.doctor(self.root)["status"], "NEEDS_INIT")
                with build:
                    self.assertEqual(aidev.initialize(self.root)["status"], "LOCAL_READY")
                self.assertEqual(aidev.doctor(self.root)["status"], "LOCAL_READY")
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), logs)
            self.assertEqual(list(logs.iterdir()), [])

    def test_other_serena_log_link_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            link = self.root / ".serena/runtime/logs"
            link.parent.mkdir(parents=True)
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                    self.skipTest("Windows symlink privilege unavailable")
                raise
            with self.assertRaisesRegex(aidev.Problem, "リンクを含む既存解析状態"):
                aidev.initialize(self.root, dry_run=True)

    def test_tracked_artifact_is_not_untracked(self):
        self.write("graphify-out/graph.json", "{}")
        subprocess.run(["git", "-C", str(self.root), "add", "graphify-out/graph.json"], check=True)
        before = snapshot(self.root)
        with self.assertRaisesRegex(aidev.Problem, "追跡済み"):
            aidev.initialize(self.root)
        self.assertEqual(snapshot(self.root), before)

    def test_git_ignored_tracked_source_is_excluded(self):
        self.write("private.py", "x = 1\n")
        subprocess.run(["git", "-C", str(self.root), "add", "private.py"], check=True)
        self.write(".gitignore", "private.py\n")
        self.assertEqual(aidev.sources(self.root), [])

    def test_provider_zero_exit_partial_failure_is_not_pass(self):
        self.write("code.py", "def f(): return 1\n")
        original = aidev.run
        def run(argv, root, **kwargs):
            return "Failed to index 1 files" if argv[0] == "serena" else original(argv, root, **kwargs)
        with patch.object(aidev, "run", side_effect=run), self.assertRaisesRegex(aidev.Problem, "一部ファイル"):
            aidev.initialize(self.root)
        self.assertEqual(aidev.state_read(self.root)["status"], "FAILED")

    def test_update_structured_error_cannot_be_reported_as_success(self):
        self.write("main.py", "def f(): return 1\n")
        build, _ = self.fake_build()
        with build:
            aidev.initialize(self.root)
        self.write("main.py", "def f(): return 2\n")
        build, _ = self.fake_build()
        with build:
            fake = aidev.run
            def run(argv, root, **kwargs):
                if any(str(x).endswith("provider_build.py") for x in argv):
                    return 'AIDEV_CRG_RESULT={"status":"ok","errors":[{"file":"main.py","error":"parse failed"}]}\n'
                return fake(argv, root, **kwargs)
            with patch.object(aidev, "run", side_effect=run), self.assertRaisesRegex(aidev.Problem, "未完了"):
                aidev.initialize(self.root)
        self.assertEqual(aidev.state_read(self.root)["status"], "FAILED")

    def test_ignore_negation_does_not_expose_backups(self):
        self.write(".gitignore", "\n".join(aidev.GIT_EXCLUDES) + "\n!/.aidev/\n!/.aidev/**\n")
        self.write(".codex/config.toml", "# original config\n")
        result = aidev.initialize(self.root)
        backup = Path(result["backup"]) / ".codex/config.toml"
        ignored = subprocess.run(["git", "-C", str(self.root), "check-ignore", "--no-index", "-q", str(backup)])
        self.assertEqual(ignored.returncode, 0)
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.root), "ls-files", "--others", "--exclude-standard", ".aidev"]), b"")

    def test_mts_and_provider_only_extensions_trigger_refresh(self):
        self.write("main.py", "def f(): return 1\n")
        self.write("module.mts", "export const x = 1;\n")
        self.write("schema.sql", "CREATE TABLE one (id INTEGER);\n")
        self.write("pyproject.toml", '[project]\nname="sample"\n')
        self.write("launch", '#!/bin/sh\necho one\n')
        build, calls = self.fake_build()
        with build:
            aidev.initialize(self.root)
            for filename, content in [("module.mts", "export const x = 2;\n"), ("schema.sql", "CREATE TABLE two (id INTEGER);\n"), ("pyproject.toml", '[project]\nname="changed"\n'), ("launch", '#!/bin/sh\necho two\n')]:
                self.write(filename, content)
                self.assertEqual(aidev.doctor(self.root)["status"], "NEEDS_INIT")
                self.assertEqual(aidev.initialize(self.root)["status"], "LOCAL_READY")
        self.assertEqual(calls.count("graphify"), 5)

    def test_missing_or_corrupt_serena_cache_is_rebuilt(self):
        self.write("main.py", "def f(): return 1\n")
        build, calls = self.fake_build()
        cache = self.root / ".serena/cache/python/document_symbols.pkl"
        with build:
            aidev.initialize(self.root)
            cache.unlink()
            self.assertEqual(aidev.doctor(self.root)["status"], "NEEDS_INIT")
            aidev.initialize(self.root)
            cache.write_bytes(b"invalid pickle")
            self.assertEqual(aidev.doctor(self.root)["status"], "NEEDS_INIT")
            aidev.initialize(self.root)
            self.assertEqual(aidev.doctor(self.root)["status"], "LOCAL_READY")
        self.assertEqual(calls.count("serena"), 3)

    def test_timeout_keeps_latest_output_in_log(self):
        log = self.root / "timeout.log"
        with self.assertRaisesRegex(aidev.Problem, "中断"):
            aidev.run([sys.executable, "-c", 'import time; print("started", flush=True); time.sleep(5)'], self.root, timeout=.3, log=log)
        self.assertIn("started", log.read_text())

    def test_partial_failure_records_failed_and_rerun_recovers(self):
        self.write("code.py", "def f(): return 1\n")
        build, _ = self.fake_build(fail="graphify")
        with build, self.assertRaises(aidev.Problem):
            aidev.initialize(self.root)
        self.assertEqual(aidev.state_read(self.root)["status"], "FAILED")
        build, _ = self.fake_build()
        with build:
            self.assertEqual(aidev.initialize(self.root)["status"], "LOCAL_READY")

    def test_source_change_is_stale_even_with_same_size_and_mtime(self):
        self.write("code.py", "def f(): return 1\n")
        build, _ = self.fake_build()
        with build:
            aidev.initialize(self.root)
        times = (self.root / "code.py").stat()
        self.write("code.py", "def f(): return 2\n")
        os.utime(self.root / "code.py", ns=(times.st_atime_ns, times.st_mtime_ns))
        self.assertEqual(aidev.doctor(self.root)["status"], "NEEDS_INIT")

    def test_graph_change_with_same_count_is_stale(self):
        self.write("code.py", "def f(): return 1\n")
        build, _ = self.fake_build()
        with build:
            aidev.initialize(self.root)
        self.write("graphify-out/graph.json", '{"nodes":[{"id":"other"}],"edges":[]}')
        self.assertEqual(aidev.doctor(self.root)["status"], "NEEDS_INIT")

    def test_subdirectory_is_rejected(self):
        (self.root / "src").mkdir()
        with self.assertRaisesRegex(aidev.Problem, "Repoルート"):
            aidev.repo_root(self.root / "src")

    def test_lock_prevents_parallel_init_without_state_file(self):
        before = snapshot(self.root)
        with aidev.lock(self.root), self.assertRaisesRegex(aidev.Problem, "別のaidev"):
            with aidev.lock(self.root):
                pass
        self.assertEqual(snapshot(self.root), before)

    def test_concurrent_configuration_edit_is_preserved(self):
        self.write(".gitignore", "original\n")
        changes, before, _ = aidev.plan(self.root, self.bins, [])
        self.write(".gitignore", "user edit\n")
        with self.assertRaisesRegex(aidev.Problem, "変更されました"):
            aidev.apply(self.root, changes, before)
        self.assertEqual((self.root / ".gitignore").read_text(), "user edit\n")
        self.assertFalse((self.root / ".codex").exists())


if __name__ == "__main__":
    unittest.main()
