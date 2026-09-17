"""Optional repository knowledge/navigation workflow. Live source remains authoritative."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import time

from aidev import Problem, atomic, digest, git, js, lock, read, repo_root, safe_path
import terrain_runtime as runtime

CONFIG = ".terrain/aidev.json"
STATE = ".aidev/terrain/state.json"
REGISTRY = ".aidev/terrain/registry.json"
PACK = ".terrain/agent/repomix.md"
PACK_META = ".terrain/agent/meta.json"
CONTEXT = ".terrain/agent/context.md"
CONTEXT_META = ".terrain/agent/context-meta.json"
POLICY = "aidev-terrain-0.3.0-acp-read-only-v1"
START = "<!-- aidev:terrain:start -->"
END = "<!-- aidev:terrain:end -->"
GUIDANCE = '''<!-- aidev:terrain:start -->
## Terrain Knowledge Layer

Terrainはderived navigation/index layerです。Source of Truthはcode/tests/schemas/config/lockfiles/CI/CLI helpです。
known-fileの小修正でTerrainを必須にせず、architecture・multi-module・場所不明の調査に使います。
`aidev terrain doctor`で状態を確認し、`aidev terrain tools read-context`から
`aidev terrain tools grep-pack --pattern "語句"` / `aidev terrain tools read-pack-file --file PATH`で絞ります。
重要な主張と編集対象は必ずlive source/tests/schemasで確認します。repomix全文をcontextへ読みません。
raw Terrain registry操作よりaidev wrapperを使います。context生成は明示的な`--build-context`時だけです。
<!-- aidev:terrain:end -->'''
LOCAL_RULES = ["/agent/repomix.md", "/agent/meta.json", "/agent/meta-inputs*", "/.meta/"]
SECRET_PATTERNS = [".env", ".env.*", "*.pem", "*.key", "credentials", "credentials.*", "secrets", "secrets.*", "id_rsa", "id_ed25519"]


def load_json(root, name, optional=False):
    raw = read(root, name)
    if raw is None and optional:
        return None
    if raw is None:
        raise Problem(f"必要なファイルがありません: {root / name}")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise Problem(f"JSON objectが必要です: {root / name}")
    return data


def local_file(name):
    return name.startswith(".aidev/") or name == PACK or name == PACK_META or name.startswith(".terrain/agent/meta-inputs") or name.startswith(".terrain/.meta/")


def audit_paths(root):
    for relative in ("AGENTS.md", ".gitignore", ".terrain", ".aidev", ".aidev/.gitignore", ".aidev/terrain"):
        safe_path(root, relative)
    for relative in (".terrain", ".aidev/terrain"):
        path = safe_path(root, relative)
        if path.exists() and not path.is_dir():
            raise Problem(f"directoryではありません: {path}")
        for base, dirs, files in os.walk(path, followlinks=False):
            for name in dirs + files:
                safe_path(root, str((Path(base) / name).relative_to(root)))
    tracked = git(root, "ls-files", "-z").split("\0")
    bad = [p for p in tracked if local_file(p)]
    if bad:
        raise Problem("Git追跡済みlocal assets: " + ", ".join(bad))


def ignored(root, name):
    # ls-files uses Git's complete ignore model; no shell or filesystem walk.
    return name in set(git(root, "ls-files", "--cached", "--others", "--ignored", "--exclude-standard", "-z", "--", name).split("\0"))


def input_files(root):
    listed = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
    ignored_tracked = set(git(root, "ls-files", "--cached", "--ignored", "--exclude-standard", "-z").split("\0"))
    result = []
    for name in sorted(set(listed)):
        if not name or name in ignored_tracked or name.startswith((".terrain/", ".aidev/")):
            continue
        if any(fnmatch.fnmatchcase(part.lower(), pattern) for part in PurePosixPath(name).parts for pattern in SECRET_PATTERNS):
            raise Problem(f"秘密ファイル候補を先にGit ignoreしてください: {root / name}")
        path = safe_path(root, name)
        if path.is_dir():
            raise Problem(f"submodule/directory inputは未対応です: {path}")
        result.append(name)
    return result


def fingerprint(root, identity, slug):
    h = hashlib.sha256()
    try:
        head = git(root, "rev-parse", "--verify", "HEAD").strip()
    except Problem:
        head = "unborn"
    h.update(js([head, identity, slug, POLICY]).encode())
    # Index blob IDs detect staging changes even when the working file has been
    # edited back to its previous contents. Never read ignored directories.
    names = input_files(root)
    allowed = set(names)
    for entry in git(root, "ls-files", "--stage", "-z").split("\0"):
        if "\t" in entry and entry.split("\t", 1)[1] in allowed:
            h.update(entry.encode() + b"\0")
    # Hash actual working contents, including nonignored untracked files.
    for name in names:
        path = safe_path(root, name)
        h.update(name.encode() + b"\0")
        h.update((runtime.file_hash(path) if path.is_file() else "deleted").encode() + b"\0")
    return h.hexdigest()


def slug_for(root, explicit=None):
    config = load_json(root, CONFIG, optional=True)
    if config:
        if type(config.get("schema_version")) is not int or config["schema_version"] != 1 or config.get("managed_by") != "aidev" or config.get("terrain_version") != runtime.TERRAIN_VERSION:
            raise Problem("Terrain repo configが不正です")
        slug = config.get("slug")
        if explicit and explicit != slug:
            raise Problem("保存済みslugの自動変更は行いません")
    else:
        slug = explicit
        if not slug:
            try:
                remote = git(root, "config", "--get", "remote.origin.url").strip()
                candidate = re.split(r"[/:]", remote.rstrip("/"))[-1]
                slug = candidate.removesuffix(".git")
            except Problem:
                slug = root.name
            slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", slug).strip("-_").lower() or "project"
    if not isinstance(slug, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", slug):
        raise Problem("slugは英数字先頭、英数字・underscore・hyphenの80文字以内です")
    return slug


def markdown_parts(text):
    text = text.replace("\r\n", "\n").lstrip()
    if text.startswith("---\n"):
        end = text.find("\n---", 3)
        if end < 0:
            raise Problem("Markdown frontmatterが閉じられていません")
        return text[4:end], text[end + 4:].lstrip("\n")
    return "", text


def context_check(root, slug=None):
    path = safe_path(root, CONTEXT)
    meta_path = safe_path(root, CONTEXT_META)
    if not path.exists() and not meta_path.exists():
        return []
    if not path.is_file() or not meta_path.is_file():
        return ["context本文またはmetadataがありません"]
    text = path.read_text(encoding="utf-8")
    _, body = markdown_parts(text)
    meta = load_json(root, CONTEXT_META)
    count = sum(line.startswith("## ") for line in body.splitlines())
    issues = []
    if count < 4 or len(body.strip()) < 500:
        issues.append("context bodyがstructurally readyではありません")
    if type(meta.get("section_count")) is not int or meta["section_count"] != count:
        issues.append("context section_count mismatch")
    if type(meta.get("char_count")) is not int or meta["char_count"] != len(body):
        issues.append("context Unicode char_count mismatch")
    portable = text.replace("\\", "/")
    if str(root).replace("\\", "/") in portable or re.search(r"(?<![\w:/])(?:/(?:home|Users|tmp|private|mnt|workspace|workspaces)/|[A-Za-z]:/|//[^/\s]+/)", portable):
        issues.append("contextにrepository/other checkout absolute pathがあります")
    if slug and (meta.get("project") != slug or meta.get("output_file") != "context.md"):
        issues.append("context metadata project/output mismatch")
    if meta.get("repo_path") != ".":
        issues.append("context metadata repo_pathはrelativeである必要があります")
    return issues


def provenance_check(root):
    issues = []
    allowed = set(input_files(root))
    for kind in ("interfaces", "routes"):
        for path in (root / ".terrain" / kind).glob("*.md"):
            safe_path(root, str(path.relative_to(root)))
            front, _ = markdown_parts(path.read_text(encoding="utf-8"))
            match = re.search(r"^source:\s*(.+)$", front, re.MULTILINE)
            source = match[1].strip() if match else ""
            if source.startswith('"'):
                try:
                    source = json.loads(source)
                except ValueError:
                    source = ""
            elif source.startswith("'") and source.endswith("'"):
                source = source[1:-1].replace("''", "'")
            if source not in allowed or not safe_path(root, source).is_file():
                issues.append(f"OpenAPI sourceがallowed inputではありません: {path}")
    return issues


def pack_check(root, slug):
    path = safe_path(root, PACK)
    if not path.is_file() or path.stat().st_size == 0:
        return ["pack missing/empty"]
    meta = load_json(root, PACK_META, optional=True)
    if not meta or meta.get("project") != slug or meta.get("repo_path") != "." or meta.get("output_file") != "repomix.md" or type(meta.get("total_files")) is not int or meta["total_files"] < 1:
        return ["pack metadata invalid"]
    allowed = set(input_files(root))
    headers = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            match = re.match(r"^### (.+?) \(\d+ lines", line)
            if match:
                name = match[1].replace("\\|", "|")
                headers.append(name)
                if name not in allowed:
                    return ["pack contains disallowed input: " + name]
    if len(set(headers)) != meta["total_files"] or len(headers) != len(set(headers)):
        return ["pack section count mismatch"]
    return []


def output_hashes(root):
    return {name: runtime.file_hash(safe_path(root, name)) if safe_path(root, name).is_file() else None for name in (PACK, PACK_META, CONTEXT, CONTEXT_META)}


def registry_check(root, slug):
    registry = load_json(root, REGISTRY, optional=True)
    return bool(registry and registry.get("projects") == [{"slug": slug, "repo_path": str(root)}])


def guidance(old):
    text = (old or b"").decode("utf-8")
    if START in text or END in text:
        if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
            raise Problem("Terrain AGENTS管理markerが不正です")
        return (text[:text.index(START)] + GUIDANCE + text[text.index(END) + len(END):]).encode(), "managed"
    if re.search(r"^##\s+Terrain Knowledge Layer\s*$", text, re.MULTILINE):
        return old, "existing-manual"
    return (text + ("\n\n" if text else "") + GUIDANCE + "\n").encode(), "managed"


def append_rules(old, rules):
    text = (old or b"").decode()
    missing = [rule for rule in rules if rule not in text.splitlines()]
    return (text + ("\n" if text and not text.endswith("\n") else "") + "\n".join(missing) + ("\n" if missing else "")).encode()


def prepare(root, slug):
    guide, mode = guidance(read(root, "AGENTS.md"))
    changes = {
        "AGENTS.md": guide,
        CONFIG: js({"schema_version": 1, "managed_by": "aidev", "slug": slug, "terrain_version": runtime.TERRAIN_VERSION}).encode(),
        ".gitignore": append_rules(read(root, ".gitignore"), ["/.aidev/"]),
        ".aidev/.gitignore": append_rules(read(root, ".aidev/.gitignore"), ["*"]),
        ".terrain/.gitignore": append_rules(read(root, ".terrain/.gitignore"), LOCAL_RULES),
    }
    return {name: value for name, value in changes.items() if value != read(root, name)}, mode


def backup_write(root, changes, run_id, previous=None, already_written=()):
    previous = previous if previous is not None else {name: read(root, name) for name in changes}
    backup = safe_path(root, ".aidev/terrain/backups/" + run_id)
    for name, raw in previous.items():
        if raw is not None:
            atomic(safe_path(root, str((backup / name).relative_to(root))), raw)
    atomic(backup / "changes.json", js({name: {"existed": raw is not None, "after_sha256": digest(changes[name])} for name, raw in previous.items()}).encode())
    for name, value in changes.items():
        if name in already_written:
            continue
        if read(root, name) != previous[name]:
            raise Problem(f"並行設定変更を保全しました: {root / name}")
        atomic(safe_path(root, name), value)


def snapshot_assets(root, run_id):
    # Preserve every existing shared asset before Terrain may update it.
    for path in (root / ".terrain").rglob("*"):
        name = str(path.relative_to(root)).replace("\\", "/")
        if path.is_file() and not local_file(name):
            atomic(safe_path(root, ".aidev/terrain/backups/" + run_id + "/assets/" + name), path.read_bytes())


def migration_current(root, slug):
    if pack_check(root, slug) or context_check(root, slug) or provenance_check(root):
        return False
    try:
        head = git(root, "rev-parse", "HEAD").strip()
    except Problem:
        return False
    if load_json(root, PACK_META).get("baseline_git_head") != head:
        return False
    if (root / CONTEXT).exists() and load_json(root, CONTEXT_META).get("baseline_git_head") != head:
        return False
    # No evidence for dirty/untracked lineage in legacy Terrain. Repack locally,
    # retain context as stale and never invoke an LLM merely for migration.
    changed = set(git(root, "diff", "HEAD", "--name-only", "-z").split("\0")) | set(git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0"))
    return not (changed & set(input_files(root)))


def initialize(root, dry_run=False, build_context=False, slug=None, refresh=False, timeout=600):
    root = repo_root(root)
    with lock(root):
        record = runtime.load_runtime(root)
        identity = runtime.runtime_identity(record)
        audit_paths(root)
        slug = slug_for(root, slug)
        prior = load_json(root, STATE, optional=True)
        if refresh and (not prior or not (root / CONFIG).exists()):
            raise Problem("refreshの前にaidev terrain initが必要です")
        changes, agents = prepare(root, slug)
        current = fingerprint(root, identity, slug)
        existing_assets = (root / PACK).exists() or (root / CONTEXT).exists()
        migration = prior is None and existing_assets
        reusable_migration = migration and "AGENTS.md" not in changes and migration_current(root, slug)
        context_issues = context_check(root, slug)
        provenance_issues = provenance_check(root)
        if provenance_issues or context_issues:
            raise Problem("既存Terrain assetsの監査失敗（自動上書きなし）: " + "; ".join(provenance_issues + context_issues))
        if prior and not changes and registry_check(root, slug):
            report = doctor(root)
            ready = report["status"] in ("TERRAIN_READY", "TERRAIN_READY_CONTEXT_NOT_BUILT")
            if ready and (not build_context or report["context"] == "PASS") and not dry_run:
                return {"status": report["status"], "indexes": "reused", "context": "reused" if report["context"] == "PASS" else "not-built", "writes": False, "agents_guidance": agents}
        if dry_run:
            return {"status": "PLAN", "writes": False, "root": str(root), "slug": slug, "files_to_change": [str(root / n) for n in changes], "agents_guidance": agents, "migration": migration, "build_context": build_context}
        if fingerprint(root, identity, slug) != current:
            raise Problem("事前確認中にsourceが変更されました。再実行してください")
        stable_inputs = {name: runtime.file_hash(root / name) if (root / name).is_file() else None for name in input_files(root) if name not in changes}
        # Establish an ignore barrier before saving any original user bytes.
        before_config = {name: read(root, name) for name in changes}
        barrier = ".aidev/.gitignore"
        if barrier in changes:
            atomic(safe_path(root, barrier), changes[barrier])
        from aidev import ensure_ignored
        ensure_ignored(root, [".aidev/terrain/backups/check", ".aidev/terrain/logs/check"])
        run_id = str(time.time_ns())
        snapshot_assets(root, run_id)
        backup_write(root, changes, run_id, before_config, (barrier,))
        ensure_ignored(root, [PACK, PACK_META, ".terrain/agent/meta-inputs.json", ".terrain/.meta/check"])
        after_inputs = {name: runtime.file_hash(root / name) if (root / name).is_file() else None for name in input_files(root) if name not in changes}
        if stable_inputs != after_inputs:
            raise Problem("設定更新中にsourceが変更されました。再実行してください")
        current = fingerprint(root, identity, slug)
        hashes = output_hashes(root)
        reused = bool(prior and prior.get("source_fingerprint") == current and prior.get("runtime_identity") == identity and prior.get("pack_output_hash") == hashes[PACK] and prior.get("pack_meta_hash") == hashes[PACK_META] and not pack_check(root, slug)) or reusable_migration
        registry = safe_path(root, REGISTRY)
        binary = record["terrain"]["path"]
        def call(args, step, acp=None):
            runtime.load_runtime(root)
            return runtime.invoke(binary, root, registry, args, timeout, safe_path(root, f".aidev/terrain/logs/{run_id}-{step}.log"), acp)
        try:
            if not registry_check(root, slug):
                # Never register into a copied foreign registry.
                backup_write(root, {REGISTRY: js({"projects": []}).encode()}, run_id + "-registry")
                call(["assets", "register", root, "--slug", slug], "register")
            if not reused:
                meta = safe_path(root, PACK_META)
                if meta.exists():
                    atomic(root / f".aidev/terrain/backups/{run_id}/pack-meta.json", meta.read_bytes())
                    meta.unlink()  # Defeat upstream's HEAD-only reuse, not user source.
                call(["scan", root, "--slug", slug], "scan")
                if pack_check(root, slug):
                    call(["assets", "pack-agent", root, "--slug", slug], "pack")
            problems = pack_check(root, slug) + provenance_check(root)
            if problems:
                raise Problem("; ".join(problems))
            hashes = output_hashes(root)
            context_current = bool(prior and prior.get("context_input_fingerprint") == current and prior.get("runtime_identity") == identity and prior.get("generation_policy") == POLICY and prior.get("context_output_hash") == hashes[CONTEXT] and prior.get("context_meta_hash") == hashes[CONTEXT_META] and hashes[CONTEXT]) or bool(reusable_migration and hashes[CONTEXT])
            built = False
            if build_context and not context_current and not migration:
                acp = runtime.preflight_acp(record, root)
                call(["assets", "agent-context", root, "--slug", slug, "--force"], "context", acp)
                if not (root / CONTEXT).is_file() or context_check(root, slug):
                    raise Problem("生成contextのvalidationに失敗しました")
                context_current, built = True, True
            if fingerprint(root, identity, slug) != current:
                raise Problem("処理中にsourceが変更されました。生成物は未確定です。再実行してください")
            audit_paths(root)
            if not registry_check(root, slug):
                raise Problem("registry isolation failure")
            hashes = output_hashes(root)
            state = {"schema_version": 1, "repo_path": str(root), "slug": slug, "runtime_identity": identity,
                     "source_fingerprint": current, "pack_input_fingerprint": current,
                     "context_input_fingerprint": current if context_current else (prior or {}).get("context_input_fingerprint"),
                     "pack_output_hash": hashes[PACK], "pack_meta_hash": hashes[PACK_META], "context_output_hash": hashes[CONTEXT], "context_meta_hash": hashes[CONTEXT_META],
                     "generation_policy": POLICY, "context_stale": bool(hashes[CONTEXT] and not context_current), "agents_guidance": agents,
                     "last_successful_run": datetime.now(timezone.utc).isoformat(), "last_operation": "refresh" if refresh else "init"}
            atomic(safe_path(root, STATE), js(state).encode())
            return {"status": "TERRAIN_READY" if context_current else ("TERRAIN_NEEDS_CONTEXT_REFRESH" if hashes[CONTEXT] else "TERRAIN_READY_CONTEXT_NOT_BUILT"), "indexes": "reused" if reused else "built", "context": "built" if built else ("reused" if context_current else "stale" if hashes[CONTEXT] else "not-built"), "migration": migration, "agents_guidance": agents, "backup": str(root / ".aidev/terrain/backups" / run_id)}
        except (Problem, OSError, ValueError):
            atomic(safe_path(root, f".aidev/terrain/logs/{run_id}-failure.json"), js({"status": "FAILED", "operation": "refresh" if refresh else "init", "state_committed": False}).encode())
            raise


def doctor(root):
    # Only Python + read-only Git plumbing. Never invoke Terrain, ACP or settings.
    report = {"status": "TERRAIN_INVALID", "runtime": "FAIL", "pack": "FAIL", "context": "NOT_BUILT", "source_fresh": False, "writes": False, "issues": []}
    try:
        record = runtime.load_runtime(root)
    except (Problem, OSError, ValueError, KeyError, TypeError) as exc:
        report.update(status="TERRAIN_RUNTIME_MISSING", issues=[str(exc)])
        return report
    report["runtime"] = "PASS"
    try:
        audit_paths(root)
        if not (root / CONFIG).is_file():
            raise Problem("aidev terrain initが必要です")
        slug = slug_for(root)
        if not registry_check(root, slug):
            raise Problem("repo-local registryが現在のcheckoutと一致しません")
        issues = pack_check(root, slug)
        report["pack"] = "FAIL" if issues else "PASS"
        context_issues = context_check(root, slug)
        exists = (root / CONTEXT).is_file()
        report["context"] = "FAIL" if context_issues else "PASS" if exists else "NOT_BUILT"
        issues += context_issues + provenance_check(root)
        if issues:
            report["issues"] = issues
            return report
        from aidev import ensure_ignored
        ensure_ignored(root, [PACK, PACK_META, ".terrain/agent/meta-inputs.json", ".terrain/.meta/check", ".aidev/terrain/state.json"])
        state = load_json(root, STATE)
        if type(state.get("schema_version")) is not int or state["schema_version"] != 1:
            raise Problem("Terrain state schemaが不正です")
        identity = runtime.runtime_identity(record)
        current = fingerprint(root, identity, slug)
        hashes = output_hashes(root)
        fresh = state.get("repo_path") == str(root) and state.get("slug") == slug and state.get("source_fingerprint") == current and state.get("runtime_identity") == identity
        report["source_fresh"] = fresh
        if not fresh or state.get("pack_output_hash") != hashes[PACK] or state.get("pack_meta_hash") != hashes[PACK_META]:
            report["status"] = "TERRAIN_NEEDS_REFRESH"
        elif exists and (state.get("context_input_fingerprint") != current or state.get("generation_policy") != POLICY or state.get("context_stale") or state.get("context_output_hash") != hashes[CONTEXT] or state.get("context_meta_hash") != hashes[CONTEXT_META]):
            report["status"] = "TERRAIN_NEEDS_CONTEXT_REFRESH"
        else:
            report["status"] = "TERRAIN_READY" if exists else "TERRAIN_READY_CONTEXT_NOT_BUILT"
    except (Problem, OSError, ValueError, KeyError, TypeError) as exc:
        report["issues"].append(str(exc))
    return report


def read_tool(root, args):
    report = doctor(root)
    if report["status"] not in ("TERRAIN_READY", "TERRAIN_READY_CONTEXT_NOT_BUILT", "TERRAIN_NEEDS_CONTEXT_REFRESH"):
        raise Problem(f"{report['status']}: 先にdoctor/refreshで入力とassetsを確認してください")
    if args.tool == "read-context" and (report["context"] != "PASS" or report["status"] != "TERRAIN_READY"):
        raise Problem("context未生成です。init --build-contextで明示生成してください")
    record = runtime.load_runtime(root)
    command = ["tools", args.tool, "--project", slug_for(root)]
    for name in ("section", "pattern", "context", "limit", "file", "start_line", "end_line"):
        value = getattr(args, name, None)
        if value is not None:
            if isinstance(value, int) and (value < 0 or (name != "context" and value == 0)):
                raise Problem("line/limitは正数、contextは0以上です")
            command += ["--" + name.replace("_", "-"), str(value)]
    if args.tool == "read-pack-file":
        safe_path(root, args.file)
        if args.start_line and args.end_line and args.start_line > args.end_line:
            raise Problem("start-lineはend-line以下にしてください")
    return runtime.invoke(record["terrain"]["path"], root, root / REGISTRY, command, timeout=60)


def add_parser(sub):
    terrain = sub.add_parser("terrain", help="任意導入のTerrain knowledge/navigation layer")
    commands = terrain.add_subparsers(dest="terrain_command", required=True)
    install = commands.add_parser("install", help="指定upstreamとpatchをbuildして専用runtimeを登録")
    install.add_argument("--allow-download", action="store_true")
    install.add_argument("--source", type=Path)
    install.add_argument("--timeout", type=int, default=3600)
    setup = commands.add_parser("setup", help="既存runtimeを検証・登録（承認なしはPLAN）")
    setup.add_argument("--terrain-binary", type=Path, required=True)
    setup.add_argument("--codex-acp", type=Path)
    setup.add_argument("--approve", action="store_true")
    setup.add_argument("--replace", action="store_true")
    setup.add_argument("--timeout", type=int, default=600)
    for name in ("init", "refresh"):
        parser = commands.add_parser(name)
        parser.add_argument("--build-context", action="store_true", help="必要な場合だけCodex ACPによるLLM処理でcontextを生成・更新（外部送信あり）")
        parser.add_argument("--timeout", type=int, default=600)
        if name == "init":
            parser.add_argument("--dry-run", action="store_true")
            parser.add_argument("--slug")
    commands.add_parser("doctor", help="Terrainを起動しない書込みなし診断").add_argument("--json", action="store_true")
    tools = commands.add_parser("tools").add_subparsers(dest="tool", required=True)
    tools.add_parser("read-context").add_argument("--section")
    grep = tools.add_parser("grep-pack")
    grep.add_argument("--pattern", required=True)
    grep.add_argument("--context", type=int, default=2)
    grep.add_argument("--limit", type=int, default=20)
    file = tools.add_parser("read-pack-file")
    file.add_argument("--file", required=True)
    file.add_argument("--start-line", type=int)
    file.add_argument("--end-line", type=int)


def dispatch(args):
    cmd = args.terrain_command
    if getattr(args, "timeout", 1) < 1:
        raise Problem("timeoutには正の秒数が必要です")
    if cmd == "install":
        result = runtime.install(args.allow_download, args.source, args.timeout)
    elif cmd == "setup":
        result = runtime.setup(args.terrain_binary, args.codex_acp, args.approve, args.replace, timeout=args.timeout)
    else:
        root = repo_root(Path.cwd())
        if cmd == "doctor":
            result = doctor(root)
        elif cmd == "tools":
            print(read_tool(root, args), end="")
            return 0
        else:
            result = initialize(root, getattr(args, "dry_run", False), args.build_context, getattr(args, "slug", None), cmd == "refresh", args.timeout)
    print(js(result), end="")
    return 1 if result["status"] in ("TERRAIN_INVALID", "TERRAIN_RUNTIME_MISSING", "TERRAIN_NEEDS_REFRESH", "TERRAIN_NEEDS_CONTEXT_REFRESH") else 0
