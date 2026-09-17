"""CI-only exact-source/baseline comparison and isolated runtime acceptance."""
from pathlib import Path
import json
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import terrain_runtime as runtime
from aidev import Problem, atomic, js


def checked(command, cwd, log):
    return runtime.execute(command, cwd, timeout=3600, log=log)


def suite(source, folder, label):
    results = {}
    # The Rust runtime crates exercise the shipped CLI; desktop GUI is outside
    # aidev's runtime build. Compare exact names + panic messages, never counts.
    for package in ('terrain-core', 'terrain-agent', 'terrain-cli'):
        log = folder / (label + '-' + package + '.log')
        command = ['cargo', 'test', '--locked', '-p', package, '--no-fail-fast', '--', '--test-threads=1']
        try:
            checked(command, source, log)
        except Problem:
            pass
        text = log.read_text(encoding='utf-8', errors='replace')
        names = re.findall(r'^test (\S+) \.\.\. FAILED$', text, re.M)
        if 'test result:' not in text or ('error:' in text and not names):
            raise Problem(f'{label}/{package}: build or harness failure; inspect {log}')
        details = {}
        for name in names:
            match = re.search(r'^---- ' + re.escape(name) + r' stdout ----\n(.*?)(?=^---- |^failures:|\Z)', text, re.M | re.S)
            if not match:
                raise Problem(f'Failure detail missing: {name}')
            detail = match[1].strip()
            detail = detail.replace(str(source), '<source>')
            detail = re.sub(r"thread '([^']+)' \(\d+\)", r"thread '\1'", detail)
            detail = re.sub(r'(\.rs):\d+:\d+', r'\1:<line>', detail)
            details[name] = detail
        results[package] = details
    return results


def main():
    folder = ROOT / 'verification/terrain-ci'
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / 'upstream'
    if source.exists():
        raise Problem('CI source already exists; use a new disposable checkout')
    checked(['git', 'clone', '--branch', runtime.TERRAIN_VERSION, '--single-branch', 'https://github.com/sopaco/terrain.git', str(source)], folder, folder / 'clone.log')
    head = checked(['git', 'rev-parse', 'HEAD'], source, folder / 'head.log').strip()
    if head != runtime.TERRAIN_UPSTREAM_SHA:
        raise Problem('Unexpected upstream SHA')
    baseline = suite(source, folder, 'baseline')
    patch = folder / 'aidev.patch'
    atomic(patch, runtime.PATCH.read_bytes().replace(b'\r\n', b'\n'))
    checked(['git', 'apply', '--check', str(patch)], source, folder / 'patch-check.log')
    checked(['git', 'apply', str(patch)], source, folder / 'patch.log')
    changed = checked(['git', 'diff', '--name-only'], source, folder / 'patch-files.log')
    if set(changed.splitlines()) != runtime.PATCH_FILES:
        raise Problem('Unexpected patch files')
    patched = suite(source, folder, 'patched')
    atomic(folder / 'baseline-comparison.json', js({'baseline': baseline, 'patched': patched}).encode())
    for package, failures in patched.items():
        if any(baseline[package].get(name) != detail for name, detail in failures.items()):
            raise Problem('New/changed upstream test failure; see baseline-comparison.json')
    for package, test in runtime.FOCUSED:
        text = checked(['cargo', 'test', '--locked', '-p', package, test, '--', '--test-threads=1'], source, folder / (test.replace('::', '-') + '.log'))
        if not re.search(r'test result: ok\. [1-9]\d* passed', text):
            raise Problem('No focused tests ran')
    checked(['cargo', 'build', '--release', '--locked', '-p', 'terrain-cli', '--bin', 'terrain'], source, folder / 'build.log')
    binary = source / 'target/release' / ('terrain.exe' if runtime.WINDOWS else 'terrain')
    runtime.check_version(binary, runtime.TERRAIN_VERSION)
    smoke = runtime.behavioral_smoke(binary)
    atomic(folder / 'acceptance.json', js({'upstream_sha': head, 'patch_sha256': runtime.patch_hash(), 'binary_sha256': runtime.file_hash(binary), 'behavior': smoke, 'no_new_runtime_test_failures': True, 'live_context': 'UNVERIFIED'}).encode())
    print(js(smoke))


if __name__ == '__main__':
    main()
