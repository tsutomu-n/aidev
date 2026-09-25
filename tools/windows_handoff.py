"""Verify a handoff or reproduce installer defects using disposable fixtures.

No provider downloads, host installation, registration, or Git writes. Only the
explicit `manifest` command writes the handoff inventory in this source checkout.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'WINDOWS_HANDOFF_MANIFEST.json'
FILES = (
    'AGENTS.md', '.gitignore', '.github/workflows/tests.yml',
    'src/aidev.py', 'src/install.py', 'src/platform_support.py', 'src/provider_probe.py', 'src/provider_build.py',
    'README.md', 'docs/STATUS.md', 'docs/TECHNICAL.md', 'docs/USER_GUIDE.md', 'docs/WINDOWS.md', 'WINDOWS_HANDOFF.md',
    'tests/test_aidev.py', 'tests/test_portability.py', 'tools/windows_handoff.py',
    'src/terrain_runtime.py', 'src/terrain_provider.py', 'src/terrain-0.9.5-aidev.patch', 'docs/TERRAIN.md',
    'tests/test_terrain.py', '.github/workflows/terrain.yml', 'tools/terrain_ci.py',
    'src/context-qualification.json', 'tests/test_context_contract.py', 'tools/context_supervisor.py',
    'src/codex-acp-1.11.0-context.patch', 'docs/UBUNTU_ACCEPTANCE.md',
)


def file_hash(path):
    # All inventory members are UTF-8 text. Git for Windows may use CRLF in
    # the worktree; compare canonical LF, without hiding other byte changes.
    text = path.read_bytes().decode('utf-8').replace('\r\n', '\n')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def inventory():
    return {name: file_hash(ROOT / name) for name in FILES}


def git(*args):
    result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(ROOT), *args], env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}, capture_output=True, text=True, encoding='utf-8', errors='replace')
    return result.stdout.strip() if result.returncode == 0 else None


def verify(expected_head=None):
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if (not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1
            or data.get('hash_mode') != 'sha256-utf8-lf' or not isinstance(data.get('files'), dict)
            or set(data['files']) != set(FILES)):
        raise ValueError('Invalid handoff manifest schema or file inventory')
    mismatches = []
    for name, expected in data['files'].items():
        path = ROOT / name
        if not path.is_file() or path.is_symlink() or file_hash(path) != expected:
            mismatches.append(str(path))
    head = git('rev-parse', 'HEAD')
    status = git('status', '--porcelain', '--untracked-files=all')
    tracked = git('ls-files', '-z')
    required = set(FILES) | {MANIFEST.name}
    missing_from_git = sorted(required - set((tracked or '').split('\0')))
    content_ok = not mismatches
    expected_ok = head is not None and expected_head is not None and head == expected_head
    delivery_ok = content_ok and expected_ok and status == '' and not missing_from_git
    return {
        'schema_version': 1,
        'status': 'PASS' if content_ok and (expected_head is None or delivery_ok) else 'FAIL',
        'root': str(ROOT), 'head': head, 'expected_head': expected_head,
        'content_match': content_ok, 'mismatched_files': mismatches,
        'git_clean': status == '' if status is not None else None,
        'not_tracked': missing_from_git,
        'delivery_verified': delivery_ok,
        'note': 'Content inventory is not a trusted signature; verify the sender-provided commit hash too. Windows runtime acceptance is separate.',
        'python': {'executable': sys.executable, 'version': platform.python_version()},
        'host': {'system': platform.system(), 'release': platform.release(), 'version': platform.version(), 'machine': platform.machine()},
    }


def reproduce():
    # Import only this checkout's reviewed standard-library installer.
    sys.path.insert(0, str(ROOT / 'src'))
    import install
    from platform_support import directory_lock
    results = []
    cases = ['W-01', 'W-02', 'W-03-source', 'W-03-publish']
    for case in cases:
        if case == 'W-01' and sys.platform != 'win32':
            results.append({'id': case, 'status': 'UNVERIFIED', 'reason': 'Requires native Windows cmd execution'})
            continue
        with tempfile.TemporaryDirectory(prefix='aidev-handoff-') as directory, ExitStack() as stack:
            folder = Path(directory)
            source = folder / 'source'
            source.mkdir()
            for name in install.FILES:
                (source / name).write_bytes(install.bundle_bytes(install.SOURCE, name))
            target = folder / 'app'
            entry = target / 'bin/aidev.cmd'
            for name, value in [('SOURCE', source), ('TARGET', target), ('ENTRY', entry), ('WINDOWS', True)]:
                stack.enter_context(patch.object(install, name, value))
            original_which = shutil.which
            stack.enter_context(patch.object(install.shutil, 'which', side_effect=lambda name: None if name == 'aidev' else original_which(name) if sys.platform == 'win32' else 'fixture-py' if name == 'py' else original_which(name)))
            stack.enter_context(redirect_stdout(io.StringIO()))
            if case == 'W-01':
                install.install()
                repo = folder / 'repo'
                repo.mkdir()
                # Harmless marker only. No arbitrary commands or provider code.
                (repo / 'py.cmd').write_bytes(b'@echo off\r\necho invoked>"%~dp0hijacked.txt"\r\nexit /b 73\r\n')
                run = subprocess.run([str(entry), '--version'], cwd=repo, capture_output=True, timeout=15)
                hijacked = (repo / 'hijacked.txt').exists()
                results.append({'id': case, 'status': 'PASS' if not hijacked and run.returncode == 0 else 'FAIL',
                                'repo_command_executed': hijacked, 'exit_code': run.returncode})
            elif case == 'W-02':
                marker = b'REM independently created user command\r\n'
                @contextmanager
                def race_lock(path):
                    entry.write_bytes(marker)
                    with directory_lock(path):
                        yield
                stack.enter_context(patch.object(install, 'directory_lock', race_lock))
                rejected = False
                try:
                    install.install()
                except (OSError, ValueError):
                    rejected = True
                preserved = entry.is_file() and entry.read_bytes() == marker
                results.append({'id': case, 'status': 'PASS' if preserved else 'FAIL',
                                'user_command_preserved': preserved, 'rejected': rejected})
            else:
                failure_seen = False
                if case == 'W-03-source':
                    original = (source / 'aidev.py').read_bytes()
                    (source / 'aidev.py').write_bytes(b'invalid syntax !\n')
                    try:
                        install.install()
                    except (SyntaxError, OSError, ValueError):
                        failure_seen = True
                    finally:
                        (source / 'aidev.py').write_bytes(original)
                else:
                    original_rename = install.os.rename
                    def failed_publish(source_path, destination):
                        if Path(destination) == entry:
                            raise OSError('fixture: entry publication failed')
                        return original_rename(source_path, destination)
                    # This reaches the real Windows entry publication operation,
                    # not the preceding completed-release staging operation.
                    with patch.object(install.os, 'rename', side_effect=failed_publish):
                        try:
                            install.install()
                        except (OSError, ValueError):
                            failure_seen = True
                retries = []
                recovered = False
                for upgrade in (False, True):
                    try:
                        install.install(upgrade=upgrade)
                        recovered = entry.is_file() and install.active_release().is_dir()
                        retries.append({'upgrade': upgrade, 'recovered': recovered})
                        if recovered:
                            break
                    except (OSError, ValueError, SyntaxError) as exc:
                        retries.append({'upgrade': upgrade, 'error_type': type(exc).__name__})
                results.append({'id': case, 'status': 'PASS' if failure_seen and recovered else 'FAIL',
                                'failure_injected': failure_seen, 'retries': retries})
    return {'schema_version': 1, 'status': 'FAIL' if any(r['status'] == 'FAIL' for r in results) else 'UNVERIFIED' if any(r['status'] == 'UNVERIFIED' for r in results) else 'PASS',
            'native_windows': sys.platform == 'win32', 'scope': 'Disposable installer fixtures; no provider or host registration',
            'checks': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('verify', help='Read-only inventory / delivery verification')
    check.add_argument('--expected-head', help='Full commit hash supplied by the sender')
    sub.add_parser('reproduce', help='Disposable W-01/W-02/W-03 probes; known defects exit 1')
    sub.add_parser('manifest', help='Explicitly refresh the source inventory after reviewed changes')
    args = parser.parse_args()
    try:
        if sys.version_info < (3, 11):
            raise ValueError('Python 3.11 or later is required')
        if args.command == 'verify':
            if args.expected_head and not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', args.expected_head):
                raise ValueError('expected-head must be a full lowercase hexadecimal commit hash')
            result = verify(args.expected_head)
        elif args.command == 'reproduce':
            result = reproduce()
        else:
            result = {'schema_version': 1, 'hash_mode': 'sha256-utf8-lf', 'files': inventory()}
            MANIFEST.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            result = {'status': 'PASS', 'written': str(MANIFEST)}
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 1 if result['status'] == 'FAIL' else 2 if result['status'] == 'UNVERIFIED' else 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'ERROR', 'error': str(exc)}, ensure_ascii=True))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
