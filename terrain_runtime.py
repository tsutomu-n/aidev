"""Pinned, explicitly approved Terrain runtime; no implicit package installation."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time

from aidev import Problem, atomic, digest, env_for, git, js, safe_path
from platform_support import WINDOWS, child_process, data_home, directory_lock, is_link, stop_process

TERRAIN_VERSION = "0.9.5"
TERRAIN_UPSTREAM_SHA = "8d888ae13a6b1253406cac379c8eb30037c96862"
TERRAIN_RUST_MIN = "1.94"
CODEX_ACP_VERSION = "1.11.0"
CONTEXT_MODE = "aidev-context-read-only"
# Set only after all non-LLM gates pass for the exact artifact; version is insufficient.
CONTEXT_QUALIFICATION_SHA256 = 'd2fc0a6d669f1183da3dd408ae6431e1e70c12f040784abad38293e16b427a8a'
CONTEXT_QUALIFICATION = Path(__file__).with_name("context-qualification.json")


def verify_context_capability(path, root=None):
    path = safe_absolute(path, root, True)
    if not CONTEXT_QUALIFICATION_SHA256 or not CONTEXT_QUALIFICATION.is_file():
        raise Problem("未検証ACP: strict context capabilityの検証記録がありません（起動拒否）")
    if file_hash(CONTEXT_QUALIFICATION) != CONTEXT_QUALIFICATION_SHA256:
        raise Problem("ACP capability検証記録のhash不一致")
    try:
        record = json.loads(CONTEXT_QUALIFICATION.read_text())
        if record["mode"] != CONTEXT_MODE or record["acp_sha256"] != file_hash(path):
            raise Problem("旧ACPまたは未検証ACPです（起動拒否）")
        if any(record["gates"].get(k) != "PASS" for k in ("protocol", "codex_policy", "os_deny", "mcp_startup", "recovery")):
            raise Problem("ACP capability検証が未完了です")
        for name, expected in record.get("trees", {}).items():
            if dependency_tree_hash(safe_absolute(name)) != expected:
                raise Problem(f"ACP/MCP依存treeが変更されています: {name}")
        for name, expected in record["files"].items():
            item = safe_absolute(name)
            if not item.is_file() or file_hash(item) != expected:
                raise Problem(f"ACP/MCP依存が欠落または変更されています: {item}")
        if not record["files"] or record.get("schema_version") != 1:
            raise Problem("ACP capability検証記録のschemaが不正です")
        for role in ("engine", "node"):
            expected = record[role]
            executable = safe_absolute(expected["path"], executable=True)
            if record["files"].get(str(executable)) != expected["sha256"] or file_hash(executable) != expected["sha256"]:
                raise Problem(f"検証済み{role}のidentityと不一致です")
        if record["engine"]["sha256"] != record["engine_sha256"]:
            raise Problem("ACP engine identity不一致")
        mcp = record["mcp"]
        safe_absolute(mcp["command"], executable=True)
        safe_absolute(mcp["args"][0])
        if mcp["command"] not in record["files"] or mcp["args"][0] not in record["files"]:
            raise Problem("MCP直接起動entryが未検証です")
        return record
    except (KeyError, IndexError, TypeError, ValueError, OSError) as exc:
        raise Problem("ACP capability検証記録が不正です") from exc


def dependency_tree_hash(root):
    """Include relative names, bytes and link targets; never follow directory links."""
    entries = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            if not path.resolve().is_relative_to(root.resolve()):
                raise Problem(f"依存tree外へのリンクは使用できません: {path}")
            entries[name] = {"link": os.readlink(path)}
        elif path.is_file():
            entries[name] = file_hash(path)
    return digest(json.dumps(entries, sort_keys=True).encode())

PATCH = Path(__file__).parent / "terrain-0.9.5-aidev.patch"
PATCH_FILES = {"crates/terrain-core/src/assets/agent_context.rs", "crates/terrain-core/src/ingest/openapi.rs", "crates/terrain-agent/src/acp.rs"}
FOCUSED = [("terrain-core", "agent_context_recovery_tests"), ("terrain-core", "ingest::openapi::tests"), ("terrain-agent", "aidev_acp_tests")]


def patch_hash():
    # Git for Windows may check out text with CRLF.
    return digest(PATCH.read_bytes().replace(b"\r\n", b"\n"))


def file_hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_absolute(path, repo=None, executable=False):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise Problem(f"実在する絶対パスを指定してください: {path}")
    for item in (path, *path.parents):
        if is_link(item):
            raise Problem(f"symlink/reparse pointは使用できません: {item}")
    if path.exists() and path.is_file() and path.stat().st_nlink != 1:
        raise Problem(f"hardlinkは使用できません: {path}")
    if executable:
        if not path.is_file() or (not WINDOWS and not os.access(path, os.X_OK)):
            raise Problem(f"実行ファイルがありません: {path}")
        if WINDOWS and path.suffix.lower() != ".exe":
            raise Problem("Windowsではshell wrapperではなくnative .exeを指定してください")
        if repo and path.resolve().is_relative_to(repo.resolve()):
            raise Problem(f"Repo内の実行ファイルは使用できません: {path}")
    return path


def stop_tree(proc):
    # ACP's SDK starts a new POSIX process group. Capture Linux descendants
    # before terminating Terrain, so those groups do not escape our cleanup.
    descendants = {}
    pending = [proc.pid]
    if not WINDOWS and Path("/proc").is_dir():
        while pending:
            parent = pending.pop()
            for task in (Path("/proc") / str(parent) / "task").glob("*/children"):
                try:
                    children = [int(value) for value in task.read_text().split()]
                except (OSError, ValueError):
                    continue
                for pid in children:
                    if pid in descendants:
                        continue
                    try:
                        fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
                        descendants[pid] = fields[19]  # starttime, guards PID reuse
                        pending.append(pid)
                    except (OSError, IndexError):
                        continue
    def terminate(sig):
        for pid, started in descendants.items():
            try:
                fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
                if fields[19] == started:
                    os.kill(pid, sig)
            except (OSError, IndexError):
                pass
    if not WINDOWS:
        terminate(signal.SIGTERM)
    stop_process(proc)
    if not WINDOWS:
        terminate(signal.SIGKILL)


def execute(argv, cwd, env=None, timeout=600, log=None):
    if timeout < 1:
        raise Problem("timeoutには正の秒数が必要です")
    with tempfile.TemporaryFile() as output:
        try:
            with child_process([str(x) for x in argv], cwd, env or env_for(cwd), output) as proc:
                try:
                    code = proc.wait(timeout=timeout)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    stop_tree(proc)
                    raise Problem(f"処理を中断しました（上限 {timeout} 秒）") from None
        finally:
            output.seek(0)
            raw = output.read()
            if log:
                atomic(log, raw)
    if code:
        raise Problem(f"{Path(argv[0]).name}: 終了コード {code}" + (f"。ログ: {log}" if log else ""))
    return raw.decode("utf-8", errors="replace")


@contextmanager
def terrain_environment(root, registry, acp=None):
    # Terrain deploys assets and reads settings at startup, even for --version.
    # Confine those side effects to a disposable HOME; never edit real settings.
    with tempfile.TemporaryDirectory(prefix="aidev-terrain-home-") as temporary:
        home = Path(temporary)
        env = env_for(root)
        for key in list(env):
            if key.startswith("TERRAIN_"):
                del env[key]
        env.update(HOME=str(home), USERPROFILE=str(home), TERRAIN_REGISTRY_FILE=str(registry),
                   TERRAIN_REPO_PATH=str(root), INITIAL_AGENT_MODE=CONTEXT_MODE if acp else "read-only")
        env["CODEX_HOME"] = os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
        env.pop("CODEX_PATH", None)
        if acp:
            capability = verify_context_capability(acp["path"], root)
            if acp.get("node") and capability.get("node") != acp["node"]:
                raise Problem("検証済みACP Nodeと不一致です")
            if capability["engine_sha256"] != file_hash(Path(acp["codex"]["path"])):
                raise Problem("検証済みACP engineと不一致です")
            try:
                overlay = json.loads(env.get("CODEX_CONFIG", "{}"))
                servers = overlay.setdefault("mcp_servers", {})
                current = servers.setdefault("chrome-devtools", {})
                for field in ("command", "args"):
                    current[field] = capability["mcp"][field]
                current.setdefault("env", {}).update(capability["mcp"]["env"])
            except (ValueError, TypeError, AttributeError) as exc:
                raise Problem("CODEX_CONFIGが不正です") from exc
            env["CODEX_CONFIG"] = json.dumps(overlay)
            env["CODEX_PATH"] = acp["codex"]["path"]
            env["CODEX_HOME"] = acp["codex_home"]
            if acp.get("node"):
                env["PATH"] = str(Path(acp["node"]["path"]).parent) + os.pathsep + env.get("PATH", "")
        settings = {"acp": {"binary": acp["path"] if acp else "aidev-no-agent-authorized", "args": "", "agent_execution": "acp", "auto_approve": False}, "language": "en"}
        atomic(home / ".terrain/settings.json", js(settings).encode())
        # Stop dotenv's ancestor search without reading the target repo's .env.
        atomic(home / ".env", b"")
        env.update(TERRAIN_ACP_BINARY=settings["acp"]["binary"], TERRAIN_ACP_ARGS="")
        yield env, home


def invoke(binary, root, registry, args, timeout=600, log=None, acp=None):
    with terrain_environment(root, registry, acp) as (env, home):
        env["PATH"] = str(Path(binary).parent) + os.pathsep + env.get("PATH", "")
        return execute([binary, "--repo-path", root, *args], home, env, timeout, log)


def check_version(binary, version):
    with tempfile.TemporaryDirectory(prefix="aidev-version-") as temporary:
        root = Path(temporary)
        with terrain_environment(root, root / "registry.json") as (env, home):
            output = execute([binary, "--version"], home, env, 30)
    if not re.search(r"(?<![\d.])" + re.escape(version) + r"(?![\d.])", output):
        raise Problem(f"未サポートのversion（必要: {version}）: {binary}")


def foundation_path():
    return safe_absolute(data_home() / "terrain/foundation.json")


def load_runtime(root):
    path = foundation_path()
    if not path.is_file():
        raise Problem("Terrain runtime未登録: aidev terrain install --allow-download または setup --approve")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1 or data.get("approved") is not True:
        raise Problem("Terrain runtimeの承認がありません")
    if data.get("upstream_sha") != TERRAIN_UPSTREAM_SHA or data.get("patch_sha256") != patch_hash():
        raise Problem("Terrain patch identityが一致しません。setupで再検証してください")
    for name, version in (("terrain", TERRAIN_VERSION), ("codex_acp", CODEX_ACP_VERSION)):
        record = data.get(name)
        if name == "codex_acp" and record is None:
            continue
        if not isinstance(record, dict) or record.get("version") != version:
            raise Problem(f"runtime version recordが不正: {name}")
        binary = safe_absolute(record["path"], root, True)
        if file_hash(binary) != record.get("sha256"):
            raise Problem(f"承認後に実行ファイルが変更されました: {binary}")
        if name == "codex_acp":
            for dependency in ("codex", "node"):
                if dependency in record:
                    executable = safe_absolute(record[dependency]["path"], root, True)
                    if file_hash(executable) != record[dependency].get("sha256"):
                        raise Problem(f"承認後にACP {dependency}が変更されました: {executable}")
    if data["terrain"].get("verified_behavior") is not True:
        raise Problem("Terrain behavioral verificationがありません")
    return data


def runtime_identity(record):
    return digest(json.dumps(record, sort_keys=True).encode())


def preflight_acp(record, root):
    acp = record.get("codex_acp")
    if not acp:
        raise Problem("Codex ACPをsetup --codex-acp PATH --approve --replaceで明示登録してください")
    path = safe_absolute(acp["path"], root, True)
    capability = verify_context_capability(path, root)
    if acp.get("qualification_sha256") != CONTEXT_QUALIFICATION_SHA256:
        raise Problem("ACP検証記録が登録時と一致しません。setupで再検証してください")
    if file_hash(path) != acp["sha256"]:
        raise Problem("Codex ACP hashが変更されました")
    if not acp.get("codex"):
        raise Problem("ACP engineの登録がありません。setup --codex-acp PATH --approve --replaceで再検証してください")
    for name in ("codex", "node"):
        if name in acp:
            executable = safe_absolute(acp[name]["path"], root, True)
            if file_hash(executable) != acp[name]["sha256"]:
                raise Problem(f"承認後にACP {name}が変更されました: {executable}")
    codex = acp["codex"]["path"]
    override = os.environ.get("CODEX_PATH")
    if override and str(safe_absolute(override, root, True)) != codex:
        raise Problem("CODEX_PATHが承認済みACP engineと一致しません。setupで明示登録してください")
    auth_home = str(safe_absolute(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    if auth_home != acp.get("codex_home"):
        raise Problem("CODEX_HOMEが承認済みACP認証先と一致しません。setupで明示登録してください")
    try:
        with terrain_environment(root, root / ".aidev/terrain/registry.json", acp) as (env, home):
            execute([codex, "login", "status"], home, env, timeout=30)
    except Problem:
        raise Problem("Codex認証を確認できません。利用者がcodex loginを実行してください（自動loginなし）") from None
    return acp


def behavioral_smoke(binary, timeout=600):
    from terrain_provider import context_check, pack_check, provenance_check
    with tempfile.TemporaryDirectory(prefix="aidev-terrain-smoke-") as temporary:
        base = Path(temporary).resolve()
        root = base / "repo 日本語 space"
        root.mkdir()
        git(root, "init", "--quiet")
        atomic(root / ".gitignore", b".references/\n.aidev/\n.env\n")
        atomic(root / "example.py", b"def strategy(value):\n    return value + 7\n")
        spec = b'openapi: 3.0.0\ninfo:\n  title: Fixture\n  version: 1.0.0\npaths:\n  /health:\n    get:\n      summary: health\n      responses: {}\n'
        atomic(root / ".references/external/docs/openapi.yaml", spec)
        git(root, "add", ".gitignore", "example.py")
        git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + str(base / "no-hooks"), "commit", "--quiet", "-m", "fixture")
        registry = base / "registry.json"
        invoke(binary, root, registry, ["assets", "register", root, "--slug", "fixture"], timeout)
        invoke(binary, root, registry, ["scan", root, "--slug", "fixture"], timeout)
        if pack_check(root, "fixture"):
            raise Problem("behavior smoke: packが不正")
        for kind in ("interfaces", "routes"):
            if list((root / ".terrain" / kind).glob("*.md")):
                raise Problem("behavior smoke: ignored OpenAPIが取り込まれました")
        atomic(root / "docs/openapi.yaml", spec)
        invoke(binary, root, registry, ["scan", root, "--slug", "fixture"], timeout)
        if not list((root / ".terrain/interfaces").glob("*.md")) or provenance_check(root):
            raise Problem("behavior smoke: valid OpenAPIの保存に失敗")
        titles = ["Project Overview", "Architecture", "Module Map", "Core Flows", "Tech Stack", "System Boundaries", "Code Map Index"]
        body = "\n\n".join(f"## {title}\n\n" + "日本語の確認。" * 30 for title in titles)
        body += f"\n\nRepository: `{root}`\nCode: `{root}/example.py`\n"
        with terrain_environment(root, registry) as (env, home):
            atomic(home / ".terrain/debug/last-agent-context-raw.md", body.encode())
            execute([binary, "assets", "repair-context", "--slug", "fixture", "--repo-path", root], home, env, timeout)
        issues = context_check(root, "fixture")
        if issues:
            raise Problem("behavior smoke: " + "; ".join(issues))
        read_commands = (["read-context"], ["grep-pack", "--pattern", "strategy"], ["read-pack-file", "--file", "example.py", "--start-line", "1", "--end-line", "20"])
        first = [invoke(binary, root, registry, ["tools", *args, "--project", "fixture"], timeout) for args in read_commands]
        if "日本語の確認" not in first[0] or "strategy" not in first[1] or "example.py" not in first[2]:
            raise Problem("behavior smoke: read tools returned unexpected assets")
        other = base / "other worktree"
        git(root, "worktree", "add", "--detach", str(other), "HEAD")
        atomic(other / "example.py", b"def other_strategy(value):\n    return value + 9\n")
        other_registry = base / "other-registry.json"
        invoke(binary, other, other_registry, ["assets", "register", other, "--slug", "fixture"], timeout)
        invoke(binary, other, other_registry, ["scan", other, "--slug", "fixture"], timeout)
        with terrain_environment(other, other_registry) as (env, home):
            other_body = body.replace(str(root), str(other)).replace("日本語の確認", "別worktreeの確認")
            atomic(home / ".terrain/debug/last-agent-context-raw.md", other_body.encode())
            execute([binary, "assets", "repair-context", "--slug", "fixture", "--repo-path", other], home, env, timeout)
        second = [invoke(binary, other, other_registry, ["tools", *args, "--project", "fixture"], timeout) for args in read_commands]
        again = [invoke(binary, root, registry, ["tools", *args, "--project", "fixture"], timeout) for args in read_commands]
        if ("別worktreeの確認" not in second[0] or "日本語の確認" in second[0]
                or "other_strategy" not in second[1] or "other_strategy" not in second[2]
                or "other_strategy" in again[1] or "別worktreeの確認" in again[0]
                or context_check(other, "fixture") or pack_check(other, "fixture")):
            raise Problem("behavior smoke: worktree asset isolation failure")
        entries = json.loads(registry.read_text())["projects"]
        if len(entries) != 1 or Path(entries[0]["repo_path"]).resolve() != root:
            raise Problem("behavior smoke: registry isolation failure")
    return {"scan_pack": "PASS", "ignored_openapi": "PASS", "valid_openapi": "PASS", "context_repair": "PASS", "read_tools": "PASS", "registry": "PASS", "worktree_isolation": "PASS"}


def setup(binary, codex_acp=None, approve=False, replace=False, root=None, timeout=600):
    root = root or Path.cwd().resolve()
    try:
        root = Path(git(root, "rev-parse", "--show-toplevel").strip()).resolve()
    except Problem:
        pass  # Machine setup also works outside a Git checkout.
    binary = safe_absolute(binary, root, True)
    acp = safe_absolute(codex_acp, root, True) if codex_acp else None
    config = foundation_path()
    if not approve:
        return {"status": "PLAN", "writes": False, "config": str(config), "terrain": str(binary), "codex_acp": str(acp) if acp else None, "next": "--approveでversionとbehavior smokeを検証して登録"}
    if acp:
        capability = verify_context_capability(acp, root)  # Refuse old ACP before any subprocess.
        selected_engine = os.environ.get("CODEX_PATH") or shutil.which("codex")
        selected_node = shutil.which("node")
        if not selected_engine or str(Path(selected_engine).resolve()) != capability["engine"]["path"]:
            raise Problem("検証済みACP engineの絶対パスをCODEX_PATHに指定してください")
        if not selected_node or str(Path(selected_node).resolve()) != capability["node"]["path"]:
            raise Problem("検証済みNodeをPATHの先頭に指定してください")
    before = file_hash(binary)
    check_version(binary, TERRAIN_VERSION)
    smoke = behavioral_smoke(binary, timeout)
    record = {"schema_version": 1, "approved": True, "upstream_sha": TERRAIN_UPSTREAM_SHA, "patch_sha256": patch_hash(),
              "terrain": {"path": str(binary), "version": TERRAIN_VERSION, "sha256": before, "verified_behavior": True}, "behavior": smoke}
    if file_hash(binary) != before:
        raise Problem("検証中にTerrainが変更されました")
    if acp:
        before_acp = file_hash(acp)
        check_version(acp, CODEX_ACP_VERSION)
        if file_hash(acp) != before_acp:
            raise Problem("検証中にCodex ACPが変更されました")
        record["codex_acp"] = {"path": str(acp), "version": CODEX_ACP_VERSION, "sha256": before_acp,
                               "qualification_sha256": CONTEXT_QUALIFICATION_SHA256}
        # Bind the engine checked for authentication to the actual ACP child.
        selected = os.environ.get("CODEX_PATH") or shutil.which("codex")
        if not selected:
            raise Problem("ACP engineのcodex実体が必要です。CODEX_PATHで絶対パスを指定してください")
        codex = safe_absolute(selected if os.environ.get("CODEX_PATH") else Path(selected).resolve(), root, True)
        auth_home = safe_absolute(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        engine_hash = file_hash(codex)
        version = execute([codex, "--version"], root, timeout=30).strip()
        if not re.fullmatch(r"codex-cli \d+\.\d+\.\d+(?:[-+][\w.-]+)?", version) or file_hash(codex) != engine_hash:
            raise Problem("ACP Codex engineのversion/hashを確認できません")
        record["codex_acp"].update(codex={"path": str(codex), "sha256": engine_hash, "version": version}, codex_home=str(auth_home))
        if acp.suffix == ".js":
            node = shutil.which("node")
            if not node:
                raise Problem("JS版ACPには既存Node runtimeが必要です")
            node = safe_absolute(execute([node, "-p", "process.execPath"], root, timeout=30).strip(), root, True)
            node_hash = file_hash(node)
            version = execute([node, "--version"], root, timeout=30).strip()
            if file_hash(node) != node_hash:
                raise Problem("検証中にNodeが変更されました")
            record["codex_acp"]["node"] = {"path": str(node), "sha256": node_hash, "version": version}
    if acp:
        verify_context_capability(acp, root)  # Recheck all dependencies before registration.
    config.parent.mkdir(parents=True, exist_ok=True)
    with directory_lock(config.parent):
        safe_absolute(config)
        old = config.read_bytes() if config.exists() else None
        content = js(record).encode()
        if old != content:
            if old and not replace:
                raise Problem(f"既存登録の更新には setup --terrain-binary {binary} --approve --replace が必要です")
            if old:
                atomic(config.with_name(f"foundation.backup-{time.time_ns()}.json"), old)
            atomic(config, content)
    return {"status": "REGISTERED", "writes": old != content, "config": str(config), **record}


def install(allow_download=False, source=None, timeout=3600):
    if not allow_download:
        return {"status": "PLAN", "writes": False, "next": "build dependency取得を許可する --allow-download が必要。Rustは自動導入しません"}
    tools = {}
    for name in ("git", "rustc", "cargo"):
        found = shutil.which(name)
        if not found:
            raise Problem(f"{name}を先に準備してください。自動導入はしません")
        path = Path(found).absolute()
        if name in ("rustc", "cargo") and path.resolve().stem == "rustup":
            # `rustup which` resolves an already installed toolchain. Execute its
            # native tools so upstream rust-toolchain.toml cannot install one.
            path = Path(execute([path.resolve(), "which", name], Path.home(), timeout=30).strip())
            if not path.is_absolute() or not path.is_file():
                raise Problem(f"導入済みの{name}実体を確認できません")
        tools[name] = str(path)
    rust = execute([tools["rustc"], "--version"], Path.home())
    match = re.search(r"rustc (\d+)\.(\d+)", rust)
    if not match or tuple(map(int, match.groups())) < (1, 94):
        raise Problem("rustc >= 1.94が必要です")
    cargo = execute([tools["cargo"], "--version"], Path.home()).strip()
    if source:
        source = safe_absolute(source)
        if git(source, "rev-parse", "HEAD").strip() != TERRAIN_UPSTREAM_SHA or git(source, "status", "--porcelain", "--untracked-files=all").strip():
            raise Problem("--sourceはexact upstream SHAのclean sourceが必要です")
    base = safe_absolute(data_home() / "terrain")
    base.mkdir(parents=True, exist_ok=True)
    with directory_lock(base):
        build = Path(tempfile.mkdtemp(prefix="build-", dir=base))
        checkout = build / "source"
        # Always use an independent clone; never patch the supplied checkout.
        execute([tools["git"], "clone", "--no-hardlinks", "--", source or "https://github.com/sopaco/terrain.git", checkout], build, timeout=timeout, log=build / "clone.log")
        execute([tools["git"], "checkout", "--detach", TERRAIN_UPSTREAM_SHA], checkout)
        if git(checkout, "rev-parse", "HEAD").strip() != TERRAIN_UPSTREAM_SHA or git(checkout, "status", "--porcelain").strip():
            raise Problem("Terrain upstream identity failure")
        patch = build / PATCH.name
        atomic(patch, PATCH.read_bytes().replace(b"\r\n", b"\n"))
        execute([tools["git"], "apply", "--check", patch], checkout)
        execute([tools["git"], "apply", patch], checkout)
        if set(git(checkout, "diff", "--name-only").splitlines()) != PATCH_FILES:
            raise Problem("Terrain patch scope failure")
        target_dir = Path(os.environ.get("CARGO_TARGET_DIR", str(checkout / "target")))
        if not target_dir.is_absolute():
            target_dir = checkout / target_dir
        safe_absolute(target_dir)
        build_env = env_for(checkout)
        build_env["RUSTC"] = tools["rustc"]
        build_env["PATH"] = str(Path(tools["cargo"]).parent) + os.pathsep + build_env.get("PATH", "")
        for package, test in FOCUSED:
            output = execute([tools["cargo"], "test", "--locked", "-p", package, test, "--", "--test-threads=1"], checkout, env=build_env, timeout=timeout, log=build / (test.replace("::", "-") + ".log"))
            if not re.search(r"test result: ok\. [1-9]\d* passed", output):
                raise Problem(f"focused testが実行されませんでした: {test}")
        execute([tools["cargo"], "build", "--release", "--locked", "-p", "terrain-cli", "--bin", "terrain"], checkout, env=build_env, timeout=timeout, log=build / "build.log")
        binary = target_dir / "release" / ("terrain.exe" if WINDOWS else "terrain")
        smoke = behavioral_smoke(binary, timeout)
        sha = file_hash(binary)
        release_id = digest((sha + patch_hash() + TERRAIN_UPSTREAM_SHA).encode())
        release = safe_absolute(base / "releases" / release_id)
        target = release / binary.name
        if target.exists():
            manifest_path = safe_absolute(release / "manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (file_hash(safe_absolute(target)) != sha or manifest.get("binary_sha256") != sha
                    or manifest.get("patch_sha256") != patch_hash() or manifest.get("upstream_sha") != TERRAIN_UPSTREAM_SHA):
                raise Problem("既存runtime releaseまたはmanifestが変更されています")
        else:
            release.mkdir(parents=True, exist_ok=False)
            shutil.copyfile(binary, target)
            target.chmod(0o700)
            atomic(release / "manifest.json", js({"upstream_sha": TERRAIN_UPSTREAM_SHA, "patch_sha256": patch_hash(), "rustc": rust.strip(), "cargo": cargo, "binary_sha256": sha, "built_at": datetime.now(timezone.utc).isoformat(), "focused_tests": [{"package": package, "filter": test, "status": "PASS"} for package, test in FOCUSED], "behavior": smoke}).encode())
    # setup has its own lock and never silently replaces an approved runtime.
    return setup(target, approve=True, timeout=timeout)
