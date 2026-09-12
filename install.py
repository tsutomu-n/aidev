#!/usr/bin/env python3
"""Install/upgrade a local aidev bundle; retain previous releases and user edits."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
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


def hashes(folder, names):
    result = {}
    for name in names:
        path = folder / name
        if is_link(path) or not path.is_file():
            raise ValueError(f"通常の配布ファイルではありません: {path}")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def stage_release(folder, names):
    expected = hashes(folder, names)
    ident = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()[:20]
    releases = TARGET / "releases"
    if is_link(releases):
        raise ValueError(f"symlinkの配置先は使用しません: {releases}")
    releases.mkdir(mode=0o700, exist_ok=True)
    release = releases / ident
    manifest = {"application": "aidev", "schema_version": 1, "files": expected}
    if release.exists() or release.is_symlink():
        if is_link(release) or hashes(release, names) != expected or json.loads((release / "installation.json").read_text(encoding="utf-8")) != manifest:
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
        os.rename(staging, release)
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


def windows_launcher(release):
    # ASCII batch file: the installation path (including Japanese and spaces)
    # is obtained by cmd itself; no hardcoded codepage-dependent path text.
    ident = release.name
    if len(ident) != 20 or any(c not in "0123456789abcdef" for c in ident):
        raise ValueError("不正なrelease識別子です")
    return ("@echo off\r\nsetlocal DisableDelayedExpansion\r\n"
            f'py -3 -X utf8 "%~dp0..\\releases\\{ident}\\aidev.py" %*\r\n'
            "exit /b %errorlevel%\r\n").encode("ascii")


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
        if raw != windows_launcher(active.parent):
            raise ValueError("Windowsランチャーに利用者の変更があります")
    elif not ENTRY.is_symlink():
        raise ValueError(f"aidev管理外の既存コマンドです: {ENTRY}")
    else:
        active = ENTRY.resolve()
    if active == TARGET / "aidev.py" and not (TARGET / "aidev.py").is_symlink():
        if hashes(TARGET, LEGACY_HASHES) != LEGACY_HASHES:
            raise ValueError("旧版のファイルに変更があります。上書きしません。")
        return stage_release(TARGET, tuple(LEGACY_HASHES))
    if active.name != "aidev.py" or active.parent.parent != TARGET / "releases":
        raise ValueError(f"aidev管理外の参照先です: {ENTRY}")
    if is_link(active.parent) or is_link(active.parent.parent):
        raise ValueError("リンクされたreleaseは使用しません")
    manifest = json.loads((active.parent / "installation.json").read_text(encoding="utf-8"))
    files = manifest.get("files", {})
    if manifest.get("application") != "aidev" or manifest.get("schema_version") != 1 or not files or not set(files).issubset(FILES):
        raise ValueError("既存releaseのmanifestを確認できません")
    if hashes(active.parent, files) != files:
        raise ValueError("インストール済みファイルに変更があります。上書きしません。")
    return active.parent


def install(upgrade=False):
    if sys.version_info < (3, 11):
        raise ValueError("Python 3.11以降が必要です")
    if WINDOWS and not shutil.which("py"):
        raise ValueError("Python 3.11以降とWindows Python Launcher (py -3)が必要です")
    for path in (TARGET.parent, ENTRY.parent):
        for parent in (path, *path.parents):
            if is_link(parent):
                raise ValueError(f"リンクされた配置先は使用しません: {parent}")
        path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir() or is_link(path):
            raise ValueError(f"通常directoryの配置先を用意してください: {path}")
    existed = ENTRY.exists() or is_link(ENTRY) or (TARGET / "releases").exists() or (TARGET / "aidev.py").exists() or shutil.which("aidev")
    if existed and not upgrade:
        raise ValueError("aidevの既存コマンド/配置先があります。更新には --upgrade を指定してください。")
    if is_link(TARGET) or (TARGET.exists() and not TARGET.is_dir()):
        raise ValueError(f"管理directoryを確認できません: {TARGET}")
    if not existed:
        TARGET.mkdir(mode=0o700, exist_ok=True)
    elif not TARGET.is_dir():
        raise ValueError("既存コマンドはこのインストーラーの管理外です")
    with directory_lock(TARGET):
        entry_before = ENTRY.read_bytes() if WINDOWS and ENTRY.is_file() else os.readlink(ENTRY) if ENTRY.is_symlink() else None
        previous = active_release() if existed else None
        # Stable links must preserve user changes too.
        for name in (() if WINDOWS else FILES):
            path = TARGET / name
            if path.exists() or path.is_symlink():
                managed = previous is not None and name in json.loads((previous / "installation.json").read_text(encoding="utf-8"))["files"]
                if not managed or not path.is_file() or path.read_bytes() != (previous / name).read_bytes():
                    raise ValueError(f"管理pathに利用者の変更があります: {path}")
        release = stage_release(SOURCE, FILES)
        if previous == release:
            print("同じ版がインストール済みです。変更はありません。")
            return release
        entry_now = ENTRY.read_bytes() if WINDOWS and ENTRY.is_file() else os.readlink(ENTRY) if ENTRY.is_symlink() else None
        if entry_now != entry_before or (entry_before is None and ENTRY.exists()):
            raise ValueError("準備中にコマンドの参照先が変更されました")
        # Switch the command to the complete release in one atomic operation.
        if WINDOWS:
            fd, temporary = tempfile.mkstemp(prefix=".aidev-", dir=ENTRY.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(windows_launcher(release))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, ENTRY)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        else:
            replace_link(ENTRY, release / "aidev.py")
            for name in FILES:
                replace_link(TARGET / name, release / name)
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
