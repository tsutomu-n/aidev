#!/usr/bin/env python3
"""Install/upgrade a local aidev bundle; retain previous releases and user edits."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from platform_support import WINDOWS, data_home, directory_lock, is_link

SOURCE = Path(__file__).resolve().parent
TARGET = data_home()
ENTRY = TARGET / "bin/aidev.cmd" if WINDOWS else Path.home() / ".local/bin/aidev"
FILES = ("aidev.py", "provider_probe.py", "provider_build.py", "platform_support.py", "README.md", "USER_GUIDE.md", "TECHNICAL.md", "STATUS.md", "WINDOWS.md")
LEGACY_HASHES = {
    "aidev.py": "fe6b2ed14922df68e63be57dbf5362e5e2f36adb575a946ba9f63d9b1b23876b",
    "provider_probe.py": "319a6b845c49ff6ec4b74bfca2b64f1eea12f58afdb88f66125b5dc5040580bd",
    "README.md": "dd87a709becbb316a2b7a5424e5441d68b3dbaf13832be093d7b8ac81feb05f7",
}
JOURNAL = "installation-progress.json"


def hashes(folder, names):
    result = {}
    for name in names:
        path = folder / name
        if is_link(path) or not path.is_file():
            raise ValueError(f"通常の配布ファイルではありません: {path}")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def runtime():
    executable = Path(sys.executable).resolve()
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("実行中Pythonの絶対パスを確認できません")
    try:
        version = json.loads(subprocess.check_output(
            [str(executable), "-X", "utf8", "-c", "import json,sys; print(json.dumps(list(sys.version_info[:3])))"],
            text=True, encoding="utf-8", stderr=subprocess.STDOUT))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ValueError(f"実行中Pythonを検証できません: {executable}") from exc
    if not isinstance(version, list) or len(version) != 3 or tuple(version[:2]) < (3, 11):
        raise ValueError("Python 3.11以降が必要です")
    return {"executable": str(executable), "version": version,
            "launcher": "cmd-utf8-fixed-python" if WINDOWS else "symlink"}


def release_manifest(folder, names, run):
    return {"application": "aidev", "schema_version": 2, "files": hashes(folder, names), "runtime": run}


def stage_release(folder, names, run=None):
    run = runtime() if run is None else run
    manifest = release_manifest(folder, names, run)
    expected = manifest["files"]
    ident = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:20]
    releases = TARGET / "releases"
    if is_link(releases):
        raise ValueError(f"symlinkの配置先は使用しません: {releases}")
    releases.mkdir(mode=0o700, exist_ok=True)
    release = releases / ident
    if release.exists() or release.is_symlink():
        if is_link(release) or not (release / "installation.json").is_file() or hashes(release, names) != expected or json.loads((release / "installation.json").read_text(encoding="utf-8")) != manifest:
            raise ValueError(f"既存releaseが変更されています: {release}")
        return release
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=releases))
    try:
        for name in names:
            shutil.copyfile(folder / name, staging / name)
            os.chmod(staging / name, 0o700 if name == "aidev.py" else 0o600)
            if name.endswith(".py"):
                ast.parse((staging / name).read_text(encoding="utf-8"), filename=name)
        if hashes(staging, names) != expected:
            raise ValueError("コピー中にsourceが変更されました")
        (staging / "installation.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (staging / "installation.json").chmod(0o600)
        os.rename(staging, release)  # destination is a new, content-addressed name
    finally:
        # Discard only this invocation's unpublished temporary copy.
        if staging.exists():
            shutil.rmtree(staging)
    return release


def replace_link(path, target):
    temporary = path.with_name(".aidev-link-" + uuid.uuid4().hex)
    try:
        temporary.symlink_to(target)
        os.replace(temporary, path)
    finally:
        if temporary.is_symlink():
            temporary.unlink()


def windows_launcher(release, run=None):
    run = runtime() if run is None else run
    ident = release.name
    python = run.get("executable")
    if len(ident) != 20 or any(c not in "0123456789abcdef" for c in ident) or not isinstance(python, str) or not Path(python).is_absolute():
        raise ValueError("不正なrelease識別子またはPython実体です")
    batch_python = python.replace("%", "%%")
    # chcp is restored even when aidev exits non-zero. The command line is read
    # after UTF-8 has been selected, so an absolute Unicode Python path is safe.
    return ("@echo off\r\nsetlocal DisableDelayedExpansion\r\n"
            "for /f \"tokens=2 delims=: \" %%A in ('chcp') do set \"_aidev_cp=%%A\"\r\n"
            "chcp 65001 >nul\r\n"
            f'"{batch_python}" -X utf8 "%~dp0..\\releases\\{ident}\\aidev.py" %*\r\n'
            "set \"_aidev_exit=%errorlevel%\"\r\nchcp %_aidev_cp% >nul\r\nexit /b %_aidev_exit%\r\n").encode("utf-8")


def active_release():
    if WINDOWS:
        if is_link(ENTRY) or not ENTRY.is_file() or ENTRY.stat().st_nlink > 1:
            raise ValueError(f"aidev管理外の既存コマンドです: {ENTRY}")
        raw = ENTRY.read_bytes()
        import re
        match = re.search(rb"releases\\([0-9a-f]{20})\\aidev.py", raw)
        if not match:
            raise ValueError("管理外のWindowsランチャーです")
        active = TARGET / "releases" / match[1].decode("ascii") / "aidev.py"
    elif not ENTRY.is_symlink():
        raise ValueError(f"aidev管理外の既存コマンドです: {ENTRY}")
    else:
        active = ENTRY.resolve()
    if active == TARGET / "aidev.py" and not (TARGET / "aidev.py").is_symlink():
        if hashes(TARGET, LEGACY_HASHES) != LEGACY_HASHES:
            raise ValueError("旧版のファイルに変更があります。上書きしません。")
        return stage_release(TARGET, tuple(LEGACY_HASHES), runtime())
    if active.name != "aidev.py" or active.parent.parent != TARGET / "releases":
        raise ValueError(f"aidev管理外の参照先です: {ENTRY}")
    if is_link(active.parent) or is_link(active.parent.parent):
        raise ValueError("リンクされたreleaseは使用しません")
    manifest = json.loads((active.parent / "installation.json").read_text(encoding="utf-8"))
    files = manifest.get("files", {})
    if manifest.get("application") != "aidev" or manifest.get("schema_version") not in (1, 2) or not files or not set(files).issubset(FILES):
        raise ValueError("既存releaseのmanifestを確認できません")
    if hashes(active.parent, files) != files:
        raise ValueError("インストール済みファイルに変更があります。上書きしません。")
    if WINDOWS:
        if manifest.get("schema_version") != 2:
            raise ValueError("旧形式Windowsランチャーは安全に移行できません")
        if raw != windows_launcher(active.parent, manifest.get("runtime")):
            raise ValueError("Windowsランチャーに利用者の変更があります")
    return active.parent


def entry_record():
    if not ENTRY.exists() and not ENTRY.is_symlink():
        return {"kind": "absent"}
    stat = ENTRY.lstat()
    if ENTRY.is_symlink():
        return {"kind": "symlink", "target": os.readlink(ENTRY), "nlink": stat.st_nlink}
    if ENTRY.is_file():
        return {"kind": "file", "sha256": hashlib.sha256(ENTRY.read_bytes()).hexdigest(), "nlink": stat.st_nlink}
    return {"kind": "other"}


def journal_path():
    return TARGET / JOURNAL


def read_journal():
    path = journal_path()
    if not path.exists():
        return None
    if is_link(path) or not path.is_file():
        raise ValueError("インストール処理記録を確認できません")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("application") != "aidev" or record.get("schema_version") != 1 or not isinstance(record.get("release"), str):
        raise ValueError("所有者不明の未完了配置があります。削除せず保全して相談してください")
    return record


def write_journal(record):
    path = journal_path()
    temporary = path.with_name("." + JOURNAL + "." + uuid.uuid4().hex)
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def clear_journal():
    if journal_path().exists():
        journal_path().unlink()


def install(upgrade=False):
    run = runtime()
    for path in (TARGET.parent, ENTRY.parent):
        for parent in (path, *path.parents):
            if is_link(parent):
                raise ValueError(f"リンクされた配置先は使用しません: {parent}")
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir() or is_link(path):
            raise ValueError(f"通常directoryの配置先を用意してください: {path}")
    if is_link(TARGET) or (TARGET.exists() and not TARGET.is_dir()):
        raise ValueError(f"管理directoryを確認できません: {TARGET}")
    TARGET.mkdir(mode=0o700, exist_ok=True)
    with directory_lock(TARGET):
        record = read_journal()
        entry_before = entry_record()
        previous = active_release() if entry_before["kind"] != "absent" else None
        release_root = TARGET / "releases"
        # An interruption after entry publication can leave only the Unix helper
        # links unfinished. Resume that owned state without requiring --upgrade.
        if record is not None and record.get("phase") == "entry-published":
            if previous is None or previous.name != record["release"]:
                raise ValueError("未完了処理のentryとreleaseが一致しません。上書きしません")
            if not WINDOWS:
                old_name = record.get("previous")
                old = release_root / old_name if isinstance(old_name, str) else None
                for name in FILES:
                    path = TARGET / name
                    if path.is_symlink() and path.resolve() == previous / name:
                        continue
                    if path.exists() or path.is_symlink():
                        if old is None or not path.is_symlink() or path.resolve() != old / name:
                            raise ValueError(f"管理pathに利用者の変更があります: {path}")
                        os.rename(path, path.with_name(".aidev-link-backup-" + uuid.uuid4().hex))
                    path.symlink_to(previous / name)
            clear_journal()
            print("中断したインストール処理を完了しました。")
            return previous
        # A release directory without our durable record may be an old partial
        # installation. Do not guess ownership or delete it to make progress.
        if (entry_before["kind"] != "absent" and previous is None) or ((release_root.exists() or (TARGET / "aidev.py").exists()) and previous is None and record is None):
            raise ValueError("所有記録のない既存配置があります。削除せず保全して相談してください")
        if previous is None and record is None and entry_before["kind"] == "absent" and not release_root.exists() and not (TARGET / "aidev.py").exists() and shutil.which("aidev"):
            raise ValueError("aidevの既存コマンド/配置先があります。上書きしません。")
        if previous is not None and not upgrade:
            raise ValueError("aidevの既存コマンド/配置先があります。更新には --upgrade を指定してください。")
        manifest = release_manifest(SOURCE, FILES, run)
        release_id = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:20]
        # A previous failed attempt with another source/runtime remains preserved.
        write_journal({"application": "aidev", "schema_version": 1, "release": release_id,
                       "phase": "staging", "entry_before": entry_before,
                       "previous": previous.name if previous else None})
        release = stage_release(SOURCE, FILES, run)
        if previous == release:
            clear_journal()
            print("同じ版がインストール済みです。変更はありません。")
            return release
        if entry_record() != entry_before:
            raise ValueError("準備中にコマンドの参照先が変更されました。上書きしません")
        write_journal({"application": "aidev", "schema_version": 1, "release": release.name,
                       "phase": "publishing", "entry_before": entry_before,
                       "previous": previous.name if previous else None})
        backup = None
        if previous is not None:
            backup = TARGET / "entry-backups" / (uuid.uuid4().hex + (".cmd" if WINDOWS else ".link"))
            backup.parent.mkdir(mode=0o700, exist_ok=True)
            os.rename(ENTRY, backup)
        if WINDOWS:
            fd, temporary = tempfile.mkstemp(prefix=".aidev-", dir=ENTRY.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(windows_launcher(release, run))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.rename(temporary, ENTRY)  # never overwrite a competing entry
            except OSError:
                if backup is not None and entry_record()["kind"] == "absent":
                    os.rename(backup, ENTRY)
                raise
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        else:
            try:
                ENTRY.symlink_to(release / "aidev.py")  # fails if another writer won
            except OSError:
                if backup is not None and entry_record()["kind"] == "absent":
                    os.rename(backup, ENTRY)
                raise
        write_journal({"application": "aidev", "schema_version": 1, "release": release.name,
                       "phase": "entry-published", "entry_before": entry_before,
                       "previous": previous.name if previous else None,
                       "entry_backup": str(backup) if backup else None})
        if not WINDOWS:
            for name in FILES:
                path = TARGET / name
                if path.exists() or path.is_symlink():
                    if previous is None or not path.is_symlink() or path.resolve() != previous / name:
                        raise ValueError(f"管理pathに利用者の変更があります: {path}")
                    saved = path.with_name(".aidev-link-backup-" + uuid.uuid4().hex)
                    os.rename(path, saved)
                path.symlink_to(release / name)
        clear_journal()
        print(f"インストール完了: {ENTRY}")
        if previous:
            print(f"旧版を保持: {previous}")
        return release


def main(argv=None):
    if WINDOWS:
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upgrade", action="store_true", help="自分の旧版だけを更新し、旧releaseを保持")
    args = parser.parse_args(argv)
    try:
        install(args.upgrade)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"aidev install: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
