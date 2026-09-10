#!/usr/bin/env python3
"""Ubuntu用のrepo-localコード解析初期化。Python 3.11+ / 標準ライブラリ。"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import fcntl
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import pickletools
import re
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import tomllib

VERSION = "0.1.1"
BUNDLE_DIR = Path(__file__).resolve().parent
PROVIDERS = {"serena": ("serena", "1.7.0"), "graphify": ("graphify", "0.9.55"), "crg": ("code-review-graph", "2.3.8")}
CAPS = {"symbol_semantics": ["serena"], "architecture_relationships": ["graphify"], "change_impact": ["crg"]}
LANGUAGES = {".py": "python", ".pyi": "python", ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript", ".js": "typescript", ".jsx": "typescript", ".mjs": "typescript", ".cjs": "typescript"}
CODE_EXTENSIONS = set(LANGUAGES) | {".go", ".rs", ".java", ".c", ".cpp", ".h", ".cs", ".rb", ".php", ".swift", ".kt", ".vue", ".svelte"}
EXCLUDES = [".git/", ".aidev/", ".codex/", ".serena/", "graphify-out/", ".code-review-graph/", "node_modules/", ".venv/", "venv/", "__pycache__/", ".next/", "dist/", "build/", "vendor/", ".env", ".env.*", "*.pem", "*.key", "credentials.*", "secrets.*"]
GIT_EXCLUDES = ["/.aidev/", "/graphify-out/", "/.code-review-graph/", "/.serena/runtime/", "/.serena/cache/", "/.serena/memories/", "/.serena/logs/", "/.serena/project.local.yml"]
SERENA_TOOLS = ["initial_instructions", "activate_project", "get_current_config", "get_symbols_overview", "find_symbol", "find_referencing_symbols", "find_implementations", "find_declaration", "get_diagnostics_for_file", "list_memories", "read_memory", "onboarding", "write_memory", "replace_symbol_body", "rename_symbol", "insert_after_symbol", "insert_before_symbol"]
CRG_TOOLS = ["list_graph_stats_tool", "query_graph_tool", "get_impact_radius_tool", "get_review_context_tool", "get_minimal_context_tool", "detect_changes_tool", "build_or_update_graph_tool"]
NEXT = "Repoルートから新規Codexセッションを開き、標準の信頼確認後に /mcp と定義・参照・影響照会を確認してください。"


class Problem(Exception):
    pass


def js(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def env_for(root):
    env = os.environ.copy()
    # Do not inject repository Python modules into installed CLI processes.
    for name in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(name, None)
    env.update(SERENA_HOME=str(root / ".serena/runtime"), CRG_PARSE_WORKERS="2", GRAPHIFY_NO_TIPS="1")
    return env


def run(argv, root, timeout=30, log=None):
    """No shell; terminate the entire child process group on timeout/interruption."""
    with tempfile.TemporaryFile() as output:
        interrupted = False
        with subprocess.Popen([str(x) for x in argv], cwd=root, env=env_for(root), stdin=subprocess.DEVNULL,
                              stdout=output, stderr=subprocess.STDOUT, start_new_session=True) as proc:
            try:
                code = proc.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                interrupted = True
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
        output.seek(0)
        raw = output.read()
    if log is not None:
        atomic(log, raw)
    if interrupted:
        detail = f" ログ: {log}" if log else ""
        raise Problem(f"処理を中断しました: {Path(str(argv[0])).name}（上限 {timeout} 秒）。再実行できます。{detail}")
    if code:
        # Provider messages can contain code or configuration; keep logs local.
        detail = f"。ログ: {log}" if log else ""
        raise Problem(f"{Path(str(argv[0])).name} が終了コード {code} で失敗{detail}")
    return raw.decode("utf-8", errors="replace")


def git(root, *args):
    return run(["git", "-c", "core.fsmonitor=false", *args], root)


def repo_root(cwd):
    try:
        root = Path(git(cwd, "rev-parse", "--show-toplevel").strip()).resolve()
    except Problem:
        raise Problem("Git Repoを確認できません。対象Repoルートで実行してください（新規Repoは先に git init）。") from None
    if root != cwd.resolve():
        raise Problem(f"Repoルートで実行してください: {root}")
    return root


def safe_path(root, relative):
    path = root / relative
    current = root
    for part in Path(relative).parts:
        if part in ("..", "/"):
            raise Problem("Repo外のpathは使用できません")
        current /= part
        if current.is_symlink():
            raise Problem(f"symlinkの設定・出力先は変更しません: {current}")
    if path.exists() and path.is_file() and path.stat().st_nlink > 1:
        raise Problem(f"hardlinkの設定は変更しません: {path}")
    return path


def read(root, relative):
    p = safe_path(root, relative)
    if not p.exists():
        return None
    if not p.is_file():
        raise Problem(f"通常ファイルではありません: {p}")
    if p.stat().st_size > 2_000_000:
        raise Problem(f"設定ファイルが大きすぎます: {p}")
    return p.read_bytes()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, tmp = tempfile.mkstemp(prefix=".aidev-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def excluded(path):
    parts = Path(path).parts
    return any((pattern[:-1] in parts if pattern.endswith("/") else
                any(fnmatch.fnmatchcase(part, pattern) for part in parts)) for pattern in EXCLUDES)


def sources(root, rules=None):
    rules = {"extensions": CODE_EXTENSIONS, "names": set()} if rules is None else rules
    paths = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
    ignored_tracked = set(git(root, "ls-files", "--cached", "--ignored", "--exclude-standard", "-z").split("\0"))
    out = []
    for relative in sorted(set(paths)):
        if not relative or relative in ignored_tracked or excluded(relative):
            continue
        suffix = Path(relative).suffix.lower()
        named_code = Path(relative).name.lower() in rules["names"]
        if suffix and suffix not in rules["extensions"] and not named_code:
            continue
        p = safe_path(root, relative)
        if p.is_file():
            if not suffix and not named_code:
                with p.open("rb") as stream:
                    if stream.read(2) != b"#!":
                        continue
            out.append(relative)
    return out


def fingerprint(root, files):
    h = hashlib.sha256()
    relevant = list(files) + [".gitignore", ".graphifyignore", ".code-review-graphignore", ".serena/project.yml", ".serena/runtime/serena_config.yml"]
    for relative in sorted(set(relevant)):
        p = safe_path(root, relative)
        if p.is_file():
            h.update(os.fsencode(relative) + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def foundation(root):
    for name in ("CRG_REPO_ROOT", "CRG_DATA_DIR", "CRG_HOME", "GRAPHIFY_OUT", "GRAPHIFY_FORCE"):
        if os.environ.get(name):
            raise Problem(f"{name} の環境overrideがあります。現在のshellで解除してから再実行してください。")
    catalog = Path.home() / ".local/share/dev-capabilities/core/catalog.py"
    if not catalog.is_file():
        raise Problem(f"共通基盤がありません: {catalog}")
    data = json.loads(run([sys.executable, "-I", catalog, "list"], root))
    approved = {p["id"] for p in data["approved_modules"]}
    if set(PROVIDERS) - approved:
        raise Problem("共通基盤の承認・整合性を確認できません: " + ", ".join(sorted(set(PROVIDERS) - approved)))
    bins = {}
    for provider, (name, version) in PROVIDERS.items():
        binary = shutil.which(name)
        if not binary or Path(binary).resolve().is_relative_to(root):
            raise Problem(f"共通基盤のCLIが見つからないかRepo内を指しています: {name}")
        actual = run([binary, "--version"], root).strip()
        if not re.search(r"(?<![\d.])" + re.escape(version) + r"(?![\d.])", actual):
            raise Problem(f"{name} はこの版で未検証です（必要: {version}）。自動更新は行いません。")
        bins[provider] = binary
    return bins


def probe(bins, provider, root, languages=()):
    python = Path(bins[provider]).resolve().parent / "python"
    if not python.is_file():
        raise Problem(f"uv tool環境のPythonがありません: {python}")
    return json.loads(run([python, "-B", "-I", BUNDLE_DIR / "provider_probe.py", provider, root, json.dumps(list(languages))], root))


def source_rules(bins, root):
    # Use the actual installed parsers' input sets, not a second hand-written list.
    result = set(LANGUAGES)
    names = set()
    for provider in ("graphify", "crg"):
        data = probe(bins, provider, root)
        extensions = data.get("code_extensions")
        if not isinstance(extensions, list) or not extensions or any(not isinstance(x, str) or not x.startswith(".") for x in extensions):
            raise Problem(f"{provider}の解析対象を確認できません")
        result.update(x.lower() for x in extensions)
        names.update(x.lower() for x in data.get("code_names", []))
    return {"extensions": result, "names": names}


def mcp_sections():
    common = "enabled = true\nrequired = false\n"
    return {
        "serena": '[mcp_servers.serena]\ncommand = "serena"\nargs = ' + json.dumps(["start-mcp-server", "--context", "codex", "--project-from-cwd", "--transport", "stdio", "--enable-web-dashboard", "false", "--open-web-dashboard", "false", "--enable-gui-log-window", "false", "--log-level", "WARNING"]) + "\n" + common + 'startup_timeout_sec = 60\ntool_timeout_sec = 120\nenabled_tools = ' + json.dumps(SERENA_TOOLS) + '\n[mcp_servers.serena.env]\nSERENA_HOME = ".serena/runtime"\n',
        "crg": '[mcp_servers.crg]\ncommand = "code-review-graph"\nargs = ' + json.dumps(["serve", "--tools", ",".join(CRG_TOOLS)]) + "\n" + common + 'startup_timeout_sec = 30\ntool_timeout_sec = 180\nenabled_tools = ' + json.dumps(CRG_TOOLS) + '\n[mcp_servers.crg.env]\nCRG_PARSE_WORKERS = "2"\n',
    }


def add_lines(old, lines):
    text = (old or b"").decode()
    # The final rule wins: earlier exclusions can be cancelled by a later '!'.
    block = "# aidev: local analysis\n" + "\n".join(lines) + "\n"
    if text.endswith(block):
        return old
    return (text + ("\n" if text and not text.endswith("\n") else "") + "\n" + block).encode()


def plan(root, bins, files):
    changes = {}
    before = {}

    def stage(relative, new):
        old = read(root, relative)
        before[relative] = old
        if old != new:
            changes[relative] = new

    # Check known outputs before any provider can touch them.
    for relative in [".aidev", ".serena", ".serena/runtime", ".serena/cache", ".serena/logs", "graphify-out", ".code-review-graph"]:
        p = safe_path(root, relative)
        if p.exists():
            if not p.is_dir():
                raise Problem(f"出力先がdirectoryではありません: {p}")
            # Generated state can contain links even when its parent is regular.
            for base, dirs, names in os.walk(p, followlinks=False):
                for name in dirs + names:
                    child = Path(base) / name
                    # npm creates internal .bin symlinks in Serena's own LSP install.
                    lsp = root / ".serena/runtime/language_servers"
                    internal_lsp_link = child.is_symlink() and child.is_relative_to(lsp) and child.resolve().is_relative_to(lsp)
                    if (child.is_symlink() and not internal_lsp_link) or (not child.is_symlink() and child.is_file() and child.stat().st_nlink > 1):
                        raise Problem(f"リンクを含む既存解析状態は自動変更しません: {child}")
    tracked = git(root, "ls-files", "-z").split("\0")
    if any(x and any(x.startswith(p.strip("/") + "/") or x == p.strip("/") for p in GIT_EXCLUDES) for x in tracked):
        raise Problem("解析生成物がGit追跡済みです。追跡状態を自動変更せず停止しました。")
    if read(root, ".serena/project.local.yml") is not None:
        raise Problem(f"Serenaのlocal overrideを先に確認してください: {root / '.serena/project.local.yml'}")
    crg = probe(bins, "crg", root)
    if Path(crg["data_dir"]).resolve() != root / ".code-review-graph":
        raise Problem("CRGのregistryが別の保存先を指定しています。既存設定を保全して停止しました。")
    original = read(root, ".codex/config.toml")
    text = (original or b"").decode()
    parsed = tomllib.loads(text)
    for name, section in mcp_sections().items():
        wanted = tomllib.loads(section)["mcp_servers"][name]
        existing = parsed.get("mcp_servers", {}).get(name)
        if existing is not None:
            # Preserve extra timeout/tool-approval fields; never replace a server.
            keys = ("command", "args", "env", "enabled_tools")
            if any(existing.get(k) != wanted[k] for k in keys) or existing.get("enabled", True) is False or existing.get("cwd") or existing.get("url") or existing.get("disabled_tools"):
                raise Problem(f"既存MCP設定と衝突: {root / '.codex/config.toml'} ({name})。上書きしていません。")
        else:
            text += "\n# aidev: " + name + "\n" + section
    tomllib.loads(text)  # catches inline-table and duplicate-table conflicts
    stage(".codex/config.toml", text.encode())

    original = read(root, ".codex/dev-capabilities.json")
    policy = json.loads(original) if original else {"schema_version": 1, "capabilities": {}}
    if set(policy) != {"schema_version", "capabilities"} or type(policy["schema_version"]) is not int or policy["schema_version"] != 1 or not isinstance(policy["capabilities"], dict):
        raise Problem("既存のrepo policy形式を確認してください")
    for cap, providers in policy["capabilities"].items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", cap) or not isinstance(providers, list) or any(not isinstance(p, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", p) for p in providers) or len(set(providers)) != len(providers):
            raise Problem("既存のrepo policyに不正な能力・provider配列があります")
    for cap, wanted in CAPS.items():
        if cap in policy["capabilities"] and policy["capabilities"][cap] != wanted:
            raise Problem(f"既存の能力選択と衝突: {cap}。既存の無効化・別provider指定を保全しました。")
        policy["capabilities"][cap] = wanted
    stage(".codex/dev-capabilities.json", original if original and json.loads(original) == policy else js(policy).encode())
    for relative, lines in [(".gitignore", GIT_EXCLUDES), (".graphifyignore", EXCLUDES), (".code-review-graphignore", EXCLUDES)]:
        stage(relative, add_lines(read(root, relative), lines))
    stage(".aidev/.gitignore", add_lines(read(root, ".aidev/.gitignore"), ["*"]))

    langs = sorted({LANGUAGES[Path(f).suffix.lower()] for f in files if Path(f).suffix.lower() in LANGUAGES})
    if files and not langs:
        raise Problem("初版の自動言語設定はPython・JavaScript・TypeScript対応です。このRepoの言語は未対応です。")
    schema = probe(bins, "serena", root, langs)
    project = schema["project"]
    project_existing = read(root, ".serena/project.yml")
    if project_existing:
        actual_langs = project.get("language_servers", project.get("languages", []))
        if project.get("activation_command") or project.get("ls_additional_workspace_folders") or project.get("additional_workspace_folders") or project.get("ls_workspace_folders", ["."]) != ["."] or project.get("ls_specific_settings") or project.get("language_backend") not in (None, "LSP"):
            raise Problem("既存Serenaに起動hook/追加workspaceがあります。自動実行せず停止しました。")
        if not set(langs).issubset(actual_langs):
            raise Problem(f"既存Serena設定に必要な言語がありません: {', '.join(langs)}")
        before[".serena/project.yml"] = project_existing
    elif langs:
        project["ignored_paths"] = EXCLUDES
        stage(".serena/project.yml", js(project).encode())

    runtime_existing = read(root, ".serena/runtime/serena_config.yml")
    runtime = schema["runtime"]
    if runtime_existing:
        if runtime.get("project_serena_folder_location", "$projectDir/.serena") != "$projectDir/.serena" or any(Path(p).resolve() != root for p in (runtime.get("projects") or [])):
            raise Problem("Serena runtimeが別Repoを参照しています。既存設定を保全して停止しました。")
        if runtime.get("language_backend", "LSP") != "LSP" or runtime.get("ls_specific_settings") or runtime.get("jetbrains_launch_command"):
            raise Problem("Serena runtimeに独自のbackend/言語サーバー設定があります。自動実行せず停止しました。")
        before[".serena/runtime/serena_config.yml"] = runtime_existing
    else:
        runtime.update(projects=[], web_dashboard=False, web_dashboard_open_on_launch=False, gui_log_window=False,
                       log_level=30, trace_lsp_communication=False, record_tool_usage=False,
                       project_serena_folder_location="$projectDir/.serena", ignored_paths=EXCLUDES)
        stage(".serena/runtime/serena_config.yml", js(runtime).encode())
    return changes, before, langs


@contextmanager
def lock(root):
    # Advisory flock leaves no file behind and serializes aidev for this root.
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Problem("このRepoで別のaidev initが実行中です")
        yield
    finally:
        os.close(fd)


def apply(root, changes, before):
    # Recheck all preflight inputs before the first write; preserve concurrent edits.
    for relative, old in before.items():
        if read(root, relative) != old:
            raise Problem(f"事前確認後に変更されました: {root / relative}")
    if not changes:
        ensure_ignored(root)
        return None
    # Protect backups before storing any original config, even if root ignore
    # contains negations or a later write fails. Original text is kept verbatim.
    barrier = ".aidev/.gitignore"
    if barrier in changes:
        atomic(root / barrier, changes[barrier])
    ensure_ignored(root, [".aidev/backups/aidev-check", ".aidev/logs/aidev-check"])
    backup = root / ".aidev/backups" / (time.strftime("%Y%m%dT%H%M%S") + "-" + str(time.time_ns()))
    for relative in changes:
        if before[relative] is not None:
            atomic(backup / relative, before[relative])
    atomic(backup / "changes.json", js({k: {"existed": before[k] is not None, "after_sha256": digest(v)} for k, v in changes.items()}).encode())
    for relative, value in changes.items():
        if relative == barrier:
            continue
        if read(root, relative) != before[relative]:
            raise Problem(f"並行変更を検出しました: {root / relative}。backup: {backup}")
        atomic(root / relative, value)
    ensure_ignored(root)
    return str(backup)


def ensure_ignored(root, paths=None):
    if paths is None:
        paths = [p.strip("/") + ("/aidev-check" if p.endswith("/") else "") for p in GIT_EXCLUDES]
    for path in paths:
        try:
            git(root, "check-ignore", "--no-index", "-q", "--", path)
        except Problem:
            raise Problem(f"解析状態がGit除外されていません: {root / path}") from None


def serena_caches(root, languages):
    issues = []
    for language in languages:
        for name in ("document_symbols.pkl", "raw_document_symbols.pkl"):
            path = safe_path(root, f".serena/cache/{language}/{name}")
            if not path.is_file():
                issues.append(f"missing: {path}")
                continue
            try:
                # Parse opcodes only; never execute untrusted pickle payloads.
                content = path.read_bytes()
                last = None
                for opcode, _, position in pickletools.genops(content):
                    last = (opcode.name, position)
                if last != ("STOP", len(content) - 1):
                    raise ValueError("incomplete pickle")
            except (ValueError, EOFError, UnicodeError):
                issues.append(f"invalid: {path}")
    return {"ready": not issues, "languages": list(languages), "issues": issues}


def artifacts(root, languages=()):
    graph = safe_path(root, "graphify-out/graph.json")
    db = safe_path(root, ".code-review-graph/graph.db")
    if not graph.is_file() or not db.is_file():
        return None
    data = json.loads(graph.read_text())
    nodes = data.get("nodes", [])
    if not isinstance(nodes, list):
        raise Problem("Graphifyのgraph形式を確認できません")
    wal = safe_path(root, ".code-review-graph/graph.db-wal")
    if wal.exists() and wal.stat().st_size:
        raise Problem("CRGのDBに未checkpointのWALがあります。利用中のサーバーを終了して再確認してください。")
    # immutable avoids creating SQLite -shm/-wal during read-only diagnostics.
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True)) as conn:
        count = conn.execute("SELECT count(*) FROM nodes").fetchone()[0]
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise Problem("CRGのDB整合性検査に失敗しました")
        # Opening CRG can change SQLite layout/metadata without changing analysis.
        # Hash logical graph rows so ordinary MCP reads do not demand a rebuild.
        graph_hash = hashlib.sha256()
        for table in ("nodes", "edges"):
            cursor = conn.execute(f"SELECT * FROM {table} ORDER BY id")
            columns = [c[0] for c in cursor.description]
            for row in cursor:
                value = {k: v for k, v in zip(columns, row) if k != "updated_at"}
                graph_hash.update(table.encode() + json.dumps(value, sort_keys=True).encode() + b"\n")
    return {"graphify_nodes": len(nodes), "crg_nodes": count, "graphify_sha256": digest(graph.read_bytes()), "crg_sha256": graph_hash.hexdigest(), "serena_cache": serena_caches(root, languages)}


def state_read(root):
    raw = read(root, ".aidev/state.json")
    if raw is None:
        return {}
    state = json.loads(raw)
    if state.get("schema_version") != 1:
        raise Problem("未知のaidev状態形式です")
    return state


def initialize(root, dry_run=False, timeout=600):
    with lock(root):
        bins = foundation(root)
        rules = source_rules(bins, root)
        files = sources(root, rules)
        changes, before, langs = plan(root, bins, files)
        if dry_run:
            return {"status": "PLAN", "root": str(root), "files_to_change": [str(root / p) for p in changes], "source_files": len(files), "languages": langs, "writes": False}
        old_state = state_read(root)
        backup = apply(root, changes, before)
        print(f"設定: {len(changes)} ファイル更新。対象コード: {len(files)} ファイル。", flush=True)
        if not files:
            state = {"schema_version": 1, "root": str(root), "status": "WAITING_FOR_CODE", "codex_mcp": "UNVERIFIED"}
            if old_state != state:
                atomic(root / ".aidev/state.json", js(state).encode())
            return {**state, "backup": backup, "next": "Python/JavaScript/TypeScriptのコード追加後に aidev init を再実行してください。"}
        current = fingerprint(root, files)
        current_artifacts = artifacts(root, langs)
        if old_state.get("root") == str(root) and old_state.get("status") == "LOCAL_READY" and old_state.get("fingerprint") == current and current_artifacts == old_state.get("artifacts"):
            return {"status": "LOCAL_READY", "root": str(root), "changed": bool(changes), "indexes": "再利用", "codex_mcp": "UNVERIFIED", "next": NEXT}
        state = {"schema_version": 1, "root": str(root), "status": "INITIALIZING", "codex_mcp": "UNVERIFIED", "steps": {}}
        source_hashes = {f: digest((root / f).read_bytes()) for f in files}
        atomic(root / ".aidev/state.json", js(state).encode())
        commands = [
            ("serena", [bins["serena"], "project", "index", str(root), "--log-level", "WARNING"]),
            ("graphify", [bins["graphify"], "extract", str(root), "--code-only", "--no-cluster", "--max-workers", "2"]),
            ("crg", [Path(bins["crg"]).resolve().parent / "python", "-B", "-I", BUNDLE_DIR / "provider_build.py", "update" if (root / ".code-review-graph/graph.db").exists() else "build", str(root)]),
        ]
        for name, command in commands:
            print(f"{name}: 初期化・索引確認中…", flush=True)
            log = root / ".aidev/logs" / f"{name}.log"
            try:
                output = run(command, root, timeout=timeout, log=log)
                # Both providers can report partial failure while exiting zero.
                if re.search(r"Failed to index [1-9]\d* files|Errors: [1-9]\d*", output):
                    raise Problem(f"{name} が一部ファイルの解析に失敗。ログ: {log}")
                if name == "crg":
                    rows = [line.removeprefix("AIDEV_CRG_RESULT=") for line in output.splitlines() if line.startswith("AIDEV_CRG_RESULT=")]
                    if len(rows) != 1:
                        raise Problem(f"CRGの構造化結果がありません。ログ: {log}")
                    result = json.loads(rows[0])
                    if result.get("status") != "ok" or result.get("errors") or result.get("warnings"):
                        raise Problem(f"CRGの解析・後処理が未完了です。ログ: {log}")
                state["steps"][name] = "PASS"
            except Problem as exc:
                state.update(status="FAILED", error=str(exc))
                state["steps"][name] = "FAILED"
                atomic(root / ".aidev/state.json", js(state).encode())
                raise
            atomic(root / ".aidev/state.json", js(state).encode())
        result = artifacts(root, langs)
        if not result or not result["graphify_nodes"] or not result["crg_nodes"] or not result["serena_cache"]["ready"]:
            state.update(status="FAILED", error="解析ノードなし")
            atomic(root / ".aidev/state.json", js(state).encode())
            raise Problem("索引のノードまたはSerenaキャッシュが不完全です。言語・ignore・解析ログを確認してください。")
        # Serena may canonically rewrite its own config; record only after success.
        after_files = sources(root, rules)
        if files != after_files or any(digest((root / f).read_bytes()) != source_hashes[f] for f in files):
            state.update(status="FAILED", error="処理中のコード変更")
            atomic(root / ".aidev/state.json", js(state).encode())
            raise Problem("処理中に対象コードが増減しました。再実行してください。")
        state.update(status="LOCAL_READY", fingerprint=fingerprint(root, after_files), artifacts=result)
        atomic(root / ".aidev/state.json", js(state).encode())
        return {**state, "backup": backup, "next": NEXT}


def doctor(root):
    bins = foundation(root)
    files = sources(root, source_rules(bins, root))
    changes, _, langs = plan(root, bins, files)
    issues = []
    if changes:
        issues.append("不足設定あり: " + ", ".join(str(root / p) for p in changes))
    state = state_read(root)
    if state.get("root") != str(root):
        issues.append("このcheckoutの初期化記録がありません")
    if state.get("status") != "LOCAL_READY":
        issues.append("コード追加待ち" if not files else "初期化・索引構築が未完了")
    elif state.get("fingerprint") != fingerprint(root, files):
        issues.append("コードまたは解析設定が変わっています。aidev init で更新してください")
    elif artifacts(root, langs) != state.get("artifacts"):
        issues.append("索引が欠落・変更されています。aidev init で確認してください")
    if not changes:
        ensure_ignored(root)
    cache = serena_caches(root, langs)
    if files and not cache["ready"]:
        issues.extend(cache["issues"])
    return {"status": "NEEDS_INIT" if issues else "LOCAL_READY", "root": str(root), "languages": langs, "issues": issues,
            "codex_mcp": "UNVERIFIED", "next": NEXT, "writes": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"aidev {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="現在のRepoの設定・初期化・索引構築")
    init.add_argument("--dry-run", action="store_true", help="変更せず事前確認と変更予定を表示")
    init.add_argument("--timeout", type=int, default=600, help="各providerの上限秒数（既定600）")
    check = sub.add_parser("doctor", help="書き換えずに設定・索引・鮮度を診断")
    check.add_argument("--json", action="store_true", help="JSONで表示")
    args = parser.parse_args(argv)
    try:
        root = repo_root(Path.cwd())
        if args.command == "init":
            if args.timeout < 1:
                raise Problem("timeoutには正の秒数を指定してください")
            result = initialize(root, args.dry_run, args.timeout)
        else:
            result = doctor(root)
        if getattr(args, "json", False) or getattr(args, "dry_run", False):
            print(js(result), end="")
        else:
            print(f"{result['status']}: {root}")
            for issue in result.get("issues", []):
                print(f"  - {issue}")
            if result.get("backup"):
                print(f"backup: {result['backup']}")
            print(result.get("next", ""))
        return 1 if result["status"] == "NEEDS_INIT" else 0
    except (Problem, OSError, ValueError, sqlite3.Error, KeyError, TypeError) as exc:
        if getattr(args, "json", False):
            print(js({"status": "ERROR", "error": str(exc), "writes": False}), end="")
        else:
            print(f"aidev: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
