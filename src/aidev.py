#!/usr/bin/env python3
"""Windows / Ubuntuのrepo-localコード解析初期化。Python 3.11+。"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import pickletools
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import tomllib

from platform_support import WINDOWS, child_process, data_home, directory_lock, is_link, stop_process

VERSION = "0.3.0"
BUNDLE_DIR = Path(__file__).resolve().parent
PROVIDERS = {"serena": ("serena", "1.7.0"), "graphify": ("graphify", "0.9.55"), "crg": ("code-review-graph", "2.3.8")}
CAPS = {"symbol_semantics": ["serena"], "architecture_relationships": ["graphify"], "change_impact": ["crg"]}
LANGUAGES = {".py": "python", ".pyi": "python", ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript", ".js": "typescript", ".jsx": "typescript", ".mjs": "typescript", ".cjs": "typescript"}
CODE_EXTENSIONS = set(LANGUAGES) | {".go", ".rs", ".java", ".c", ".cpp", ".h", ".cs", ".rb", ".php", ".swift", ".kt", ".vue", ".svelte"}
EXCLUDES = [".git/", ".aidev/", ".codex/", ".serena/", ".terrain/", "graphify-out/", ".code-review-graph/", "node_modules/", ".venv/", "venv/", "__pycache__/", ".next/", "dist/", "build/", "vendor/", ".env", ".env.*", "*.pem", "*.key", "credentials.*", "secrets.*"]
GIT_EXCLUDES = ["/.aidev/", "/graphify-out/", "/.code-review-graph/", "/.serena/runtime/", "/.serena/cache/", "/.serena/memories/", "/.serena/logs/", "/.serena/project.local.yml"]
SERENA_TOOLS = ["initial_instructions", "activate_project", "get_current_config", "get_symbols_overview", "find_symbol", "find_referencing_symbols", "find_implementations", "find_declaration", "get_diagnostics_for_file", "list_memories", "read_memory", "onboarding", "write_memory", "replace_symbol_body", "rename_symbol", "insert_after_symbol", "insert_before_symbol"]
CRG_TOOLS = ["list_graph_stats_tool", "query_graph_tool", "get_impact_radius_tool", "get_review_context_tool", "get_minimal_context_tool", "detect_changes_tool", "build_or_update_graph_tool"]
NEXT = "Repoルートから新規Codexセッションを開き、標準の信頼確認後に /mcp と、ツール名を指定しない定義・構造・影響照会で実際の利用を確認してください。"
CODE_START = "<!-- aidev:code-intelligence:start -->"
CODE_END = "<!-- aidev:code-intelligence:end -->"
CODE_GUIDANCE = '''<!-- aidev:code-intelligence:start -->
## aidev コード調査

単純な文字列・設定値の検索や既知ファイルの小修正は通常の手段を使います。次の調査が主題なら、利用可能な対応能力を選びます。
- シンボルの定義・参照の追跡: Serena MCPのシンボル照会。
- モジュールやコード間の構造・関係: Graphify CLIの索引照会。
- 差分の影響範囲・レビュー対象・テスト候補: CRG MCPの影響照会。比較baseを明示します。

索引が必要な調査では`aidev doctor --json`で対応能力の状態を確認します。コード・branchの変更後や重要な判断の前にも確認します。`LOCAL_READY`はMCP接続や解析の網羅性の証明ではありません。
入力変更で更新が必要なら、現在のRepoに並行編集・設定衝突がない場合に限り、`aidev init --dry-run`で予定を確認して`aidev init`を一度実行します。失敗・再失効時は更新を繰り返さず実ソースで調べ、索引が使えなかったことを伝えます。
能力が利用できない場合は実ソースで調べ、不足を伝えます。索引の候補と重要な主張・編集対象は実ソース/tests/schemasで確認します。
<!-- aidev:code-intelligence:end -->'''


class Problem(Exception):
    pass


def js(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def current_head(root):
    try:
        return git(root, "rev-parse", "HEAD").strip()
    except Problem:
        return None


def env_for(root):
    env = os.environ.copy()
    # Do not inject repository Python modules into installed CLI processes.
    for name in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(name, None)
    env.update(SERENA_HOME=str(root / ".serena/runtime"), CRG_PARSE_WORKERS="2", GRAPHIFY_NO_TIPS="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return env


def run(argv, root, timeout=30, log=None):
    """No shell; terminate the entire child process group on timeout/interruption."""
    with tempfile.TemporaryFile() as output:
        interrupted = False
        launch_error = None
        try:
            with child_process([str(x) for x in argv], root, env_for(root), output) as proc:
                try:
                    code = proc.wait(timeout=timeout)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    interrupted = True
                    stop_process(proc)
        except OSError as exc:
            launch_error = exc
        except KeyboardInterrupt:
            interrupted = True
        output.seek(0)
        raw = output.read()
    if log is not None:
        atomic(log, raw)
    if launch_error is not None:
        detail = f" ログ: {log}" if log else ""
        raise Problem(f"子プロセスを安全に起動・終了できません: {launch_error}.{detail}") from launch_error
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
    if Path(relative).is_absolute() or Path(relative).drive:
        raise Problem("Repo外のpathは使用できません")
    current = root
    for part in Path(relative).parts:
        if part in ("..", "/"):
            raise Problem("Repo外のpathは使用できません")
        current /= part
        if is_link(current):
            raise Problem(f"symlink/reparse pointの設定・出力先は変更しません: {current}")
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


def agents_guidance_file(root):
    """Choose the root instruction file Codex actually reads."""
    override = read(root, "AGENTS.override.md")
    return "AGENTS.override.md" if override and override.strip() else "AGENTS.md"


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
    config = data_home() / "foundation.json"
    if config.exists() or is_link(config):
        return registered_foundation(root, config)
    if WINDOWS:
        raise Problem(f"provider環境が未登録です。aidev setup --help を確認してください: {config}")
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


class ProviderBins(dict):
    def __init__(self, records):
        super().__init__((p, r["command"]) for p, r in records.items())
        self.pythons = {p: r["python"] for p, r in records.items()}


def provider_python(bins, provider):
    if isinstance(bins, ProviderBins):
        return Path(bins.pythons[provider])
    python = Path(bins[provider]).resolve().parent / ("python.exe" if WINDOWS else "python")
    if not python.is_file():
        raise Problem(f"provider環境のPythonがありません。aidev setupで明示指定できます: {python}")
    return python


def check_provider_version(provider, binary, root):
    name, version = PROVIDERS[provider]
    actual = run([binary, "--version"], root).strip()
    if not re.search(r"(?<![\d.])" + re.escape(version) + r"(?![\d.])", actual):
        raise Problem(f"{name} はこの版で未検証です（必要: {version}）。自動更新は行いません。")


def registered_foundation(root, config):
    if any(is_link(p) for p in (config, *config.parents)):
        raise Problem(f"リンクされたprovider登録は使用しません: {config}")
    data = json.loads(config.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1
            or data.get("approved") is not True or not isinstance(data.get("providers"), dict)
            or set(data["providers"]) != set(PROVIDERS)):
        raise Problem("aidev専用のprovider承認登録を確認できません")
    records = data["providers"]
    for provider, record in records.items():
        if not isinstance(record, dict) or record.get("version") != PROVIDERS[provider][1]:
            raise Problem(f"provider登録の版が異なります: {provider}")
        for key in ("command", "python"):
            path = Path(record[key])
            if not path.is_absolute() or not path.is_file() or path.resolve().is_relative_to(root):
                raise Problem(f"provider実行ファイルが不正またはRepo内です: {path}")
            if digest(path.read_bytes()) != record.get(key + "_sha256"):
                raise Problem(f"provider実行ファイルが登録後に変更されました: {path}")
        check_provider_version(provider, record["command"], root)
    return ProviderBins(records)


def setup_foundation(pythons, approve=False, replace=False):
    # These explicit paths are the user's execution scope. Never discover or
    # install code from a repository or silently approve PATH candidates.
    records = {}
    root = Path.home()
    for provider, python in pythons.items():
        if not python.is_absolute() or not python.is_file():
            raise Problem(f"Pythonの実在する絶対パスを指定してください: {python}")
        binary = python.parent / (PROVIDERS[provider][0] + (".exe" if WINDOWS else ""))
        if not binary.is_file():
            raise Problem(f"同じprovider環境のCLIがありません: {binary}")
        record = {"python": str(python), "command": str(binary), "version": PROVIDERS[provider][1]}
        before = {key + "_sha256": digest(Path(record[key]).read_bytes()) for key in ("python", "command")}
        check_provider_version(provider, binary, root)
        # Confirm the specified interpreter imports the matching distribution.
        distribution = {"serena": "serena-agent", "graphify": "graphifyy", "crg": "code-review-graph"}[provider]
        version = run([python, "-B", "-I", "-X", "utf8", "-c", "import importlib.metadata,sys; print(importlib.metadata.version(sys.argv[1]))", distribution], root).strip()
        if version != record["version"]:
            raise Problem(f"Python環境とCLIのprovider版が一致しません: {provider}")
        if any(digest(Path(record[key]).read_bytes()) != before[key + "_sha256"] for key in ("python", "command")):
            raise Problem("検査中にprovider実行ファイルが変更されました")
        records[provider] = {**record, **before}
    config = data_home() / "foundation.json"
    result = {"schema_version": 1, "approved": bool(approve), "providers": records}
    if not approve:
        return {"status": "PLAN", "writes": False, "config": str(config), **result}
    # Preserve custom content by default, and retain the exact previous bytes
    # on explicit replacement. No Ubuntu catalog or Codex settings are edited.
    for parent in (config.parent, *config.parent.parents):
        if is_link(parent):
            raise Problem(f"リンクの登録先は使用しません: {parent}")
    config.parent.mkdir(parents=True, exist_ok=True)
    with directory_lock(config.parent):
        if is_link(config):
            raise Problem(f"リンクの登録先は使用しません: {config}")
        raw = config.read_bytes() if config.exists() else None
        content = js(result).encode()
        if raw != content:
            if raw is not None and not replace:
                raise Problem("既存のprovider登録があります。更新には --replace が必要です")
            if raw is not None:
                atomic(config.with_name(f"foundation.backup-{time.time_ns()}.json"), raw)
            atomic(config, content)
    return {"status": "REGISTERED", "config": str(config), "writes": raw != content, **result}


def probe(bins, provider, root, languages=()):
    python = provider_python(bins, provider)
    return json.loads(run([python, "-B", "-I", "-X", "utf8", BUNDLE_DIR / "provider_probe.py", provider, root, json.dumps(list(languages))], root))


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


def mcp_sections(bins=None):
    common = "enabled = true\nrequired = false\n"
    sections = {
        "serena": '[mcp_servers.serena]\ncommand = "serena"\nargs = ' + json.dumps(["start-mcp-server", "--context", "codex", "--project-from-cwd", "--transport", "stdio", "--enable-web-dashboard", "false", "--open-web-dashboard", "false", "--enable-gui-log-window", "false", "--log-level", "WARNING"]) + "\n" + common + 'startup_timeout_sec = 60\ntool_timeout_sec = 120\nenabled_tools = ' + json.dumps(SERENA_TOOLS) + '\n[mcp_servers.serena.env]\nSERENA_HOME = ".serena/runtime"\n',
        "crg": '[mcp_servers.crg]\ncommand = "code-review-graph"\nargs = ' + json.dumps(["serve", "--tools", ",".join(CRG_TOOLS)]) + "\n" + common + 'startup_timeout_sec = 30\ntool_timeout_sec = 180\nenabled_tools = ' + json.dumps(CRG_TOOLS) + '\n[mcp_servers.crg.env]\nCRG_PARSE_WORKERS = "2"\n',
    }

    if isinstance(bins, ProviderBins):
        for provider, command in (("serena", "serena"), ("crg", "code-review-graph")):
            sections[provider] = sections[provider].replace('command = ' + json.dumps(command), 'command = ' + json.dumps(bins[provider], ensure_ascii=False))
    return sections


def add_lines(old, lines):
    text = (old or b"").decode()
    # The final rule wins: earlier exclusions can be cancelled by a later '!'.
    block = "# aidev: local analysis\n" + "\n".join(lines) + "\n"
    marker = "# aidev: local analysis\n"
    if text.endswith(block) and text.count(marker) == 1:
        return old
    if marker in text:
        prefix, *managed = text.split(marker)
        if all(part and all(line in lines for line in part.splitlines() if line) for part in managed):
            return (prefix + block).encode()
    return (text + ("\n" if text and not text.endswith("\n") else "") + "\n" + block).encode()


def code_guidance(old):
    text = (old or b"").decode("utf-8")
    if CODE_START in text or CODE_END in text:
        if text.count(CODE_START) != 1 or text.count(CODE_END) != 1 or text.index(CODE_START) > text.index(CODE_END):
            raise Problem("aidev AGENTS管理markerが不正です")
        return (text[:text.index(CODE_START)] + CODE_GUIDANCE + text[text.index(CODE_END) + len(CODE_END):]).encode()
    return (text + ("\n\n" if text else "") + CODE_GUIDANCE + "\n").encode()


def existing_serena_log_link(root, path):
    # Older Serena setups can link per-project logs to Serena's user log dir.
    # This is not an aidev output or config path, and os.walk never follows it.
    return (not WINDOWS and path == root / ".serena/runtime/logs" and path.is_symlink()
            and path.is_dir() and path.resolve() == (Path.home() / ".serena/logs").resolve())


def plan(root, bins, files):
    changes = {}
    before = {}

    def load(relative):
        # Keep the bytes used to derive the plan, not a later re-read which
        # could hide a concurrent edit from apply()'s preflight comparison.
        if relative not in before:
            before[relative] = read(root, relative)
        return before[relative]

    def stage(relative, new):
        if load(relative) != new:
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
                    if (is_link(child) and not internal_lsp_link and not existing_serena_log_link(root, child)) or (not child.is_symlink() and child.is_file() and child.stat().st_nlink > 1):
                        raise Problem(f"リンクを含む既存解析状態は自動変更しません: {child}")
    tracked = git(root, "ls-files", "-z").split("\0")
    if any(x and any(x.startswith(p.strip("/") + "/") or x == p.strip("/") for p in GIT_EXCLUDES) for x in tracked):
        raise Problem("解析生成物がGit追跡済みです。追跡状態を自動変更せず停止しました。")
    if load(".serena/project.local.yml") is not None:
        raise Problem(f"Serenaのlocal overrideを先に確認してください: {root / '.serena/project.local.yml'}")
    crg = probe(bins, "crg", root)
    if Path(crg["data_dir"]).resolve() != root / ".code-review-graph":
        raise Problem("CRGのregistryが別の保存先を指定しています。既存設定を保全して停止しました。")
    original = load(".codex/config.toml")
    text = (original or b"").decode()
    parsed = tomllib.loads(text)
    for name, section in mcp_sections(bins).items():
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

    original = load(".codex/dev-capabilities.json")
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
    # The presence/content of the override determines where guidance goes.
    # Preserve that selection input too, even when AGENTS.md is selected.
    override = load("AGENTS.override.md")
    guidance_file = "AGENTS.override.md" if override and override.strip() else "AGENTS.md"
    stage(guidance_file, code_guidance(load(guidance_file)))
    for relative, lines in [(".gitignore", GIT_EXCLUDES), (".graphifyignore", EXCLUDES), (".code-review-graphignore", EXCLUDES)]:
        stage(relative, add_lines(load(relative), lines))
    stage(".aidev/.gitignore", add_lines(load(".aidev/.gitignore"), ["*"]))

    langs = sorted({LANGUAGES[Path(f).suffix.lower()] for f in files if Path(f).suffix.lower() in LANGUAGES})
    if files and not langs:
        raise Problem("初版の自動言語設定はPython・JavaScript・TypeScript対応です。このRepoの言語は未対応です。")
    project_existing = load(".serena/project.yml")
    runtime_existing = load(".serena/runtime/serena_config.yml")
    schema = probe(bins, "serena", root, langs)
    project = schema["project"]
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
    try:
        with directory_lock(root):
            yield
    except BlockingIOError:
        raise Problem("このRepoで別のaidev initが実行中です") from None


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
    atomic(backup / "changes.json", js({k: {
        "existed": before[k] is not None,
        "before_sha256": digest(before[k]) if before[k] is not None else None,
        "after_sha256": digest(v),
    } for k, v in changes.items()}).encode())
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
    data = json.loads(graph.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise Problem("Graphifyのgraph形式を確認できません（JSON objectが必要です）")
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


def serena_artifact_hash(root, languages):
    h = hashlib.sha256()
    for language in sorted(languages):
        for name in ("document_symbols.pkl", "raw_document_symbols.pkl"):
            relative = f".serena/cache/{language}/{name}"
            raw = safe_path(root, relative).read_bytes()
            h.update(relative.encode() + b"\0" + raw + b"\0")
    return h.hexdigest()


def artifact_hashes(root, languages, result):
    return {"serena": serena_artifact_hash(root, languages), "graphify": result["graphify_sha256"], "crg": result["crg_sha256"]}


def crg_build_head(root):
    db = safe_path(root, ".code-review-graph/graph.db")
    if not db.is_file():
        return None
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro&immutable=1", uri=True)) as conn:
        table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone()
        if not table:
            return None  # Older or fixture graphs have no native HEAD record.
        row = conn.execute("SELECT value FROM metadata WHERE key='git_head_sha'").fetchone()
        return row[0] if row else None


def index_metadata(root, source_fingerprint, languages, result, completed):
    hashes = artifact_hashes(root, languages, result)
    head = current_head(root)
    records = {}
    for name in PROVIDERS:
        version = PROVIDERS[name][1]
        artifact_hash = hashes[name]
        identity = ["aidev-index-v1", name, version, source_fingerprint, artifact_hash]
        records[name] = {"built_at": completed[name], "git_head": head, "input_fingerprint": source_fingerprint,
                         "provider_version": version, "artifact_sha256": artifact_hash,
                         "snapshot_id": digest(js(identity).encode())}
    return records


def metadata_matches(record, name, source_fingerprint, artifact_hash):
    if record is None:  # Only an absent metadata field is a legacy receipt.
        return True
    if not isinstance(record, dict):
        return False
    version = PROVIDERS[name][1]
    identity = ["aidev-index-v1", name, version, source_fingerprint, artifact_hash]
    return (record.get("input_fingerprint") == source_fingerprint and record.get("provider_version") == version
            and record.get("artifact_sha256") == artifact_hash
            and record.get("snapshot_id") == digest(js(identity).encode()))


def state_read(root):
    raw = read(root, ".aidev/state.json")
    if raw is None:
        return {}
    state = json.loads(raw)
    if (not isinstance(state, dict) or type(state.get("schema_version")) is not int
            or state["schema_version"] != 1):
        raise Problem("未知のaidev状態形式です")
    for key in ("artifacts", "index_metadata"):
        if key in state and not isinstance(state[key], dict):
            raise Problem(f"aidev状態の{key}はJSON objectである必要があります。元の状態は変更していません")
    if "index_metadata" in state:
        for name, record in state["index_metadata"].items():
            if not isinstance(record, dict):
                raise Problem(f"aidev構築記録の形式が不正です: {name}。元の状態は変更していません")
    return state


def index_record(state, name):
    # Legacy states omit the whole field. A missing entry in a newer receipt
    # must fail comparison instead of being silently treated as legacy.
    if "index_metadata" not in state:
        return None
    return state["index_metadata"].get(name, {})


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
        start_head = current_head(root)
        current_artifacts = artifacts(root, langs)
        native_crg_head = crg_build_head(root)
        saved_records = old_state.get("index_metadata", {})
        current_hashes = (artifact_hashes(root, langs, current_artifacts)
                          if current_artifacts and current_artifacts["serena_cache"]["ready"] else {})
        records_match = bool(current_artifacts and current_artifacts["serena_cache"]["ready"] and all(
            metadata_matches(index_record(old_state, name), name, current, current_hashes[name]) for name in PROVIDERS))
        if (old_state.get("root") == str(root) and old_state.get("status") == "LOCAL_READY"
                and old_state.get("fingerprint") == current and current_artifacts == old_state.get("artifacts")
                and records_match and (native_crg_head is None or native_crg_head == start_head)):
            return {"status": "LOCAL_READY", "root": str(root), "changed": bool(changes), "indexes": "再利用", "codex_mcp": "UNVERIFIED", "next": NEXT}
        state = {"schema_version": 1, "root": str(root), "status": "INITIALIZING", "codex_mcp": "UNVERIFIED", "steps": {},
                 "index_metadata": saved_records}
        completed = {}
        source_hashes = {f: digest((root / f).read_bytes()) for f in files}
        atomic(root / ".aidev/state.json", js(state).encode())
        commands = [
            ("serena", [bins["serena"], "project", "index", str(root), "--log-level", "WARNING"]),
            ("graphify", [bins["graphify"], "extract", str(root), "--code-only", "--no-cluster", "--max-workers", "2"]),
            ("crg", [provider_python(bins, "crg"), "-B", "-I", "-X", "utf8", BUNDLE_DIR / "provider_build.py", "update" if (root / ".code-review-graph/graph.db").exists() else "build", str(root)]),
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
                completed[name] = utc_now()
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
        if (files != after_files or current_head(root) != start_head
                or any(digest((root / f).read_bytes()) != source_hashes[f] for f in files)):
            state.update(status="FAILED", error="処理中のコード変更")
            atomic(root / ".aidev/state.json", js(state).encode())
            raise Problem("処理中に対象コードが増減しました。再実行してください。")
        final_fingerprint = fingerprint(root, after_files)
        state.update(status="LOCAL_READY", fingerprint=final_fingerprint, artifacts=result,
                     index_metadata=index_metadata(root, final_fingerprint, langs, result, completed))
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
    current_fingerprint = fingerprint(root, files)
    current_artifacts = None
    source_matches = state.get("fingerprint") == current_fingerprint
    if state.get("root") != str(root):
        issues.append("このcheckoutの初期化記録がありません")
    if state.get("status") != "LOCAL_READY":
        issues.append("コード追加待ち" if not files else "初期化・索引構築が未完了")
    elif not source_matches:
        issues.append("コードまたは解析設定が変わっています。aidev init で更新してください")
    else:
        current_artifacts = artifacts(root, langs)
        if current_artifacts != state.get("artifacts"):
            issues.append("索引が欠落・変更されています。aidev init で確認してください")
    native_crg_head = crg_build_head(root)
    head = current_head(root)
    if native_crg_head is not None and native_crg_head != head:
        issues.append("CRGの構築時HEADが現在のHEADと異なります。aidev init で更新してください")
    if not changes:
        ensure_ignored(root)
    cache = serena_caches(root, langs)
    if files and not cache["ready"]:
        issues.extend(cache["issues"])
    saved_artifacts = state.get("artifacts") or {}
    actual_hashes = {}
    if current_artifacts:
        actual_hashes = {"graphify": current_artifacts["graphify_sha256"], "crg": current_artifacts["crg_sha256"]}
        if cache["ready"]:
            actual_hashes["serena"] = serena_artifact_hash(root, langs)
    record_matches = {}
    for name in PROVIDERS:
        record_matches[name] = bool(name in actual_hashes and metadata_matches(
            index_record(state, name), name, current_fingerprint, actual_hashes[name]))
    if source_matches and current_artifacts is not None:
        for name, matches in record_matches.items():
            if not matches:
                issues.append(f"{name}の成果物・構築記録が一致しません。aidev init で更新してください")
    providers = {}
    for name in PROVIDERS:
        record = index_record(state, name) or {}
        reasons = []
        if changes:
            reasons.append("設定更新が必要")
        if state.get("root") != str(root) or state.get("status") != "LOCAL_READY":
            reasons.append("初期化・索引構築が未完了")
        elif not source_matches:
            reasons.append("解析入力が変更されています")
        elif current_artifacts is None:
            reasons.append("成果物が欠落しています")
        elif name == "serena" and current_artifacts["serena_cache"] != saved_artifacts.get("serena_cache"):
            reasons.append("Serenaキャッシュが変更されています")
        elif name == "graphify" and current_artifacts["graphify_sha256"] != saved_artifacts.get("graphify_sha256"):
            reasons.append("Graphify索引が変更されています")
        elif name == "crg" and current_artifacts["crg_sha256"] != saved_artifacts.get("crg_sha256"):
            reasons.append("CRG索引が変更されています")
        if name == "serena" and not cache["ready"]:
            reasons.append("Serenaキャッシュが不完全です")
        if source_matches and current_artifacts is not None and not record_matches[name]:
            reasons.append("成果物・構築記録が一致しません")
        if name == "crg" and native_crg_head is not None and native_crg_head != head:
            reasons.append("CRGの構築時HEADが異なります")
        providers[name] = {"status": "NEEDS_INIT" if reasons else "READY", "reasons": reasons,
                           "built_at": record.get("built_at"), "build_git_head": record.get("git_head"),
                           "input_fingerprint": record.get("input_fingerprint"),
                           "provider_version": record.get("provider_version"),
                           "artifact_sha256": record.get("artifact_sha256"), "snapshot_id": record.get("snapshot_id"),
                           "next": "aidev init" if reasons else None}
    try:
        terrain_config = safe_path(root, ".terrain/aidev.json")
        if terrain_config.exists():
            import terrain_provider
            terrain_report = terrain_provider.doctor(root)
            providers["terrain"] = terrain_provider.doctor_summary(root, terrain_report)
        else:
            providers["terrain"] = {"status": "NOT_INSTALLED", "reasons": [], "next": "aidev terrain init --dry-run"}
    except (Problem, OSError, ValueError, KeyError, TypeError) as exc:
        providers["terrain"] = {"status": "TERRAIN_INVALID", "reasons": [str(exc)], "next": "aidev terrain doctor --json"}
    return {"status": "NEEDS_INIT" if issues else "LOCAL_READY", "root": str(root), "languages": langs, "issues": issues,
            "codex_mcp": "UNVERIFIED", "next": NEXT, "writes": False,
            "checked_at": utc_now(), "current_input_fingerprint": current_fingerprint,
            "source_files": len(files), "providers": providers}


def main(argv=None):
    if WINDOWS:
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"aidev {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="現在のRepoの設定・初期化・索引構築")
    init.add_argument("--dry-run", action="store_true", help="変更せず事前確認と変更予定を表示")
    init.add_argument("--timeout", type=int, default=600, help="各providerの上限秒数（既定600）")
    check = sub.add_parser("doctor", help="書き換えずに設定・索引・鮮度を診断")
    check.add_argument("--json", action="store_true", help="JSONで表示")
    setup = sub.add_parser("setup", help="指定した既存provider環境の検査・明示承認登録（自動導入なし）")
    for provider in PROVIDERS:
        setup.add_argument(f"--{provider}-python", type=Path, required=True, help="provider専用環境のPython絶対パス")
    setup.add_argument("--approve", action="store_true", help="検査した3providerをこの利用者のaidevで使うことを承認して保存")
    setup.add_argument("--replace", action="store_true", help="既存のaidev専用登録を明示的に更新")
    requested = list(sys.argv[1:] if argv is None else argv)
    if requested and requested[0] == "terrain":
        import terrain_provider
        terrain_provider.add_parser(sub)
    else:
        sub.add_parser("terrain", help="各Repoに導入できるTerrain索引（runtime登録が必要）")
    args = parser.parse_args(argv)
    try:
        if args.command == "terrain":
            return terrain_provider.dispatch(args)
        if args.command == "setup":
            result = setup_foundation({p: getattr(args, p + "_python") for p in PROVIDERS}, args.approve, args.replace)
            print(js(result), end="")
            return 0
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
            if args.command == "doctor":
                for name, detail in result["providers"].items():
                    reason = "; ".join(detail.get("reasons", []))
                    print(f"  {name}: {detail['status']}" + (f" ({reason})" if reason else ""))
                    if detail.get("next") and detail["status"] not in ("READY", "NOT_INSTALLED"):
                        print(f"    次: {detail['next']}")
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
    sys.modules.setdefault("aidev", sys.modules[__name__])
    raise SystemExit(main())
