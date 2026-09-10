#!/usr/bin/env python3
"""Install/upgrade a local aidev bundle; retain previous releases and user edits."""
import argparse
import ast
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

SOURCE = Path(__file__).resolve().parent
TARGET = Path.home() / ".local/share/aidev"
ENTRY = Path.home() / ".local/bin/aidev"
FILES = ("aidev.py", "provider_probe.py", "provider_build.py", "README.md")
LEGACY_HASHES = {
    "aidev.py": "fe6b2ed14922df68e63be57dbf5362e5e2f36adb575a946ba9f63d9b1b23876b",
    "provider_probe.py": "319a6b845c49ff6ec4b74bfca2b64f1eea12f58afdb88f66125b5dc5040580bd",
    "README.md": "dd87a709becbb316a2b7a5424e5441d68b3dbaf13832be093d7b8ac81feb05f7",
}


def hashes(folder, names):
    result = {}
    for name in names:
        path = folder / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"通常の配布ファイルではありません: {path}")
        result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def stage_release(folder, names):
    expected = hashes(folder, names)
    ident = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()[:20]
    releases = TARGET / "releases"
    if releases.is_symlink():
        raise ValueError(f"symlinkの配置先は使用しません: {releases}")
    releases.mkdir(mode=0o700, exist_ok=True)
    release = releases / ident
    manifest = {"application": "aidev", "schema_version": 1, "files": expected}
    if release.exists() or release.is_symlink():
        if release.is_symlink() or hashes(release, names) != expected or json.loads((release / "installation.json").read_text()) != manifest:
            raise ValueError(f"既存releaseが変更されています: {release}")
        return release
    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=releases))
    try:
        for name in names:
            shutil.copyfile(folder / name, staging / name)
            os.chmod(staging / name, 0o700 if name == "aidev.py" else 0o600)
            if name.endswith(".py"):
                ast.parse((staging / name).read_text(), filename=name)
        if hashes(staging, names) != expected:
            raise ValueError("コピー中にsourceが変更されました")
        (staging / "installation.json").write_text(json.dumps(manifest, indent=2) + "\n")
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


def active_release():
    if not ENTRY.is_symlink():
        raise ValueError(f"aidev管理外の既存コマンドです: {ENTRY}")
    active = ENTRY.resolve()
    if active == TARGET / "aidev.py" and not (TARGET / "aidev.py").is_symlink():
        if hashes(TARGET, LEGACY_HASHES) != LEGACY_HASHES:
            raise ValueError("旧版のファイルに変更があります。上書きしません。")
        return stage_release(TARGET, tuple(LEGACY_HASHES))
    if active.name != "aidev.py" or active.parent.parent != TARGET / "releases":
        raise ValueError(f"aidev管理外の参照先です: {ENTRY}")
    manifest = json.loads((active.parent / "installation.json").read_text())
    files = manifest.get("files", {})
    if manifest.get("application") != "aidev" or manifest.get("schema_version") != 1 or not files or not set(files).issubset(FILES):
        raise ValueError("既存releaseのmanifestを確認できません")
    if hashes(active.parent, files) != files:
        raise ValueError("インストール済みファイルに変更があります。上書きしません。")
    return active.parent


def install(upgrade=False):
    if sys.version_info < (3, 11):
        raise ValueError("Python 3.11以降が必要です")
    for path in (TARGET.parent, ENTRY.parent):
        if not path.is_dir() or path.is_symlink():
            raise ValueError(f"通常directoryの配置先を用意してください: {path}")
    existed = TARGET.exists() or TARGET.is_symlink() or ENTRY.exists() or ENTRY.is_symlink() or shutil.which("aidev")
    if existed and not upgrade:
        raise ValueError("aidevの既存コマンド/配置先があります。更新には --upgrade を指定してください。")
    if TARGET.is_symlink() or (TARGET.exists() and not TARGET.is_dir()):
        raise ValueError(f"管理directoryを確認できません: {TARGET}")
    if not existed:
        TARGET.mkdir(mode=0o700)
    elif not TARGET.is_dir():
        raise ValueError("既存コマンドはこのインストーラーの管理外です")
    fd = os.open(TARGET, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        entry_before = os.readlink(ENTRY) if ENTRY.is_symlink() else None
        previous = active_release() if existed else None
        # Stable links must preserve user changes too.
        for name in FILES:
            path = TARGET / name
            if path.exists() or path.is_symlink():
                managed = previous is not None and name in json.loads((previous / "installation.json").read_text())["files"]
                if not managed or not path.is_file() or path.read_bytes() != (previous / name).read_bytes():
                    raise ValueError(f"管理pathに利用者の変更があります: {path}")
        release = stage_release(SOURCE, FILES)
        if previous == release:
            print("同じ版がインストール済みです。変更はありません。")
            return release
        if (os.readlink(ENTRY) if ENTRY.is_symlink() else None) != entry_before or (entry_before is None and ENTRY.exists()):
            raise ValueError("準備中にコマンドの参照先が変更されました")
        # Switch the command to the complete release in one atomic operation.
        replace_link(ENTRY, release / "aidev.py")
        for name in FILES:
            replace_link(TARGET / name, release / name)
        print(f"インストール完了: {ENTRY}")
        if previous:
            print(f"旧版を保持: {previous}")
        return release
    finally:
        os.close(fd)


def main(argv=None):
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
