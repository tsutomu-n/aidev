"""Conservative, repo-local ownership receipts and subtractive removal."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile

LEDGER = '.aidev/ownership.json'
PROGRESS = '.aidev/remove-progress.json'
COMPONENTS = ('core', 'terrain')
HEX = set('0123456789abcdef')
LOCAL_ONLY = ('.aidev/', '.serena/cache/', '.serena/runtime/', 'graphify-out/', '.code-review-graph/', '.terrain/agent/', '.terrain/.meta/')
CORE_FILES = {'.aidev/state.json': 'core', '.serena/project.yml': 'core.serena', '.serena/runtime/serena_config.yml': 'core.serena',
              **{f'.aidev/logs/{provider}.log': 'core.local' for provider in ('serena', 'graphify', 'crg')}}
TERRAIN_FILES = {name: 'terrain.local' for name in ('.aidev/terrain/state.json', '.aidev/terrain/registry.json',
                 '.terrain/agent/repomix.md', '.terrain/agent/meta.json', '.terrain/agent/meta-inputs.json')}
TERRAIN_FILES['.terrain/aidev.json'] = 'terrain'
TERRAIN_FILES.update({name: 'terrain.shared' for name in ('.terrain/agent/context.md', '.terrain/agent/context-meta.json')})
CORE_TREES = {'graphify-out': 'core.graphify', '.code-review-graph': 'core.crg', '.serena/cache': 'core.serena'}
TERRAIN_TREES = {name: 'terrain.local' for name in ('.aidev/terrain/backups', '.aidev/terrain/logs', '.terrain/agent', '.terrain/.meta')}
IGNORE_PATHS = ('.gitignore', '.aidev/.gitignore', '.terrain/.gitignore')


class OwnershipError(ValueError):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(data):
    return (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode()


def _time():
    return datetime.now(timezone.utc).isoformat()


def _relative(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or name.startswith('/') or name == '.git':
        raise OwnershipError('unsafe ownership path')
    path = PurePosixPath(name)
    if any(part in ('', '.', '..') for part in name.split('/')) or path.as_posix() != name or name.startswith('.git/'):
        raise OwnershipError('unsafe ownership path')
    return path


def _path(root, name):
    parts = _relative(name).parts
    path = root
    for part in parts:
        path /= part
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (not stat.S_ISDIR(info.st_mode) and info.st_nlink != 1):
            raise OwnershipError('link or hardlink: ' + name)
        if path != root.joinpath(*parts) and not stat.S_ISDIR(info.st_mode):
            raise OwnershipError('non-directory ancestor: ' + name)
    return path


def _read(root, name):
    path = _path(root, name)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_size > 20_000_000:
        raise OwnershipError('not a regular small file: ' + name)
    return path.read_bytes()


def _write(root, name, raw):
    path = _path(root, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.aidev-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _file_digest(root, name):
    path = _path(root, name)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OwnershipError('not a regular owned file: ' + name)
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def _managed_entry(scope, entry):
    name, kind, component = entry['path'], entry['kind'], entry['component']
    if kind == 'file':
        allowed = CORE_FILES if scope == 'core' else TERRAIN_FILES
        return component == allowed.get(name)
    if kind == 'tree':
        if scope == 'core' and name.startswith('.aidev/backups/') and len(PurePosixPath(name).parts) == 3:
            return component == 'core.local'
        return component == (CORE_TREES if scope == 'core' else TERRAIN_TREES).get(name)
    if kind == 'json_members':
        expected = {'/capabilities/symbol_semantics': ['serena'], '/capabilities/architecture_relationships': ['graphify'],
                    '/capabilities/change_impact': ['crg']}
        return (scope == component == 'core' and name == '.codex/dev-capabilities.json'
                and all(pointer in expected and record['owned_value'] == expected[pointer]
                        for pointer, record in entry['members'].items()))
    if kind != 'block':
        return False
    pair = (entry['start_marker'], entry['end_marker'])
    if name in ('AGENTS.md', 'AGENTS.override.md'):
        label = 'code-intelligence' if scope == 'core' else 'terrain'
        return component == scope and pair == (f'<!-- aidev:{label}:start -->', f'<!-- aidev:{label}:end -->')
    if name in IGNORE_PATHS + ('.graphifyignore', '.code-review-graphignore'):
        if (scope == 'terrain' and name not in IGNORE_PATHS) or (scope == 'core' and name == '.terrain/.gitignore'):
            return False
        return component == scope and pair == (f'# aidev:{scope}:{name}:start', f'# aidev:{scope}:{name}:end')
    return (scope == component == 'core' and name == '.codex/config.toml'
            and pair in {(f'# aidev:mcp:{p}:start', f'# aidev:mcp:{p}:end') for p in ('serena', 'crg')})


def _managed_backup(scope, entry, backup):
    parts = PurePosixPath(backup).parts
    if scope == 'core':
        return len(parts) >= 4 and parts[:2] == ('.aidev', 'backups') and parts[3:] == PurePosixPath(entry['path']).parts
    if len(parts) < 5 or parts[:3] != ('.aidev', 'terrain', 'backups'):
        return False
    suffix = parts[4:]
    return suffix == PurePosixPath(entry['path']).parts or (parts[4] == 'assets' and parts[5:] == PurePosixPath(entry['path']).parts)


def _validate(root, data):
    if not isinstance(data, dict) or set(data) != {'schema_version', 'repo_path', 'created_at', 'updated_at', 'components'} or type(data['schema_version']) is not int or data['schema_version'] != 1 or data['repo_path'] != str(root) or not all(isinstance(data[k], str) and data[k] for k in ('created_at', 'updated_at')):
        raise OwnershipError('invalid ownership ledger or repo path')
    comps = data['components']
    if not isinstance(comps, dict) or set(comps) != set(COMPONENTS):
        raise OwnershipError('invalid ownership components')
    seen = set()
    for scope, obj in comps.items():
        if not isinstance(obj, dict) or set(obj) != {'entries'} or not isinstance(obj['entries'], dict):
            raise OwnershipError('invalid ownership entries')
        for key, entry in obj['entries'].items():
            if not isinstance(key, str) or not key or not isinstance(entry, dict) or not {'kind', 'path', 'component'} <= set(entry):
                raise OwnershipError('invalid ownership entry')
            name = entry['path']
            _relative(name)
            if not isinstance(entry['component'], str) or not (entry['component'] == scope or entry['component'].startswith(scope + '.')):
                raise OwnershipError('invalid ownership component')
            kind = entry['kind']
            if kind == 'file':
                if set(entry) != {'kind', 'path', 'component', 'origin', 'owned'} or not isinstance(entry['origin'], dict) or set(entry['origin']) != {'existed', 'sha256', 'backup'} or not isinstance(entry['owned'], dict) or set(entry['owned']) != {'sha256'} or not _hash(entry['owned']['sha256']):
                    raise OwnershipError('invalid file ownership')
                origin = entry['origin']
                if type(origin['existed']) is not bool or (origin['existed'] and (not _hash(origin['sha256']) or not isinstance(origin['backup'], str))) or (not origin['existed'] and (origin['sha256'] is not None or origin['backup'] is not None)):
                    raise OwnershipError('invalid file origin')
                if origin['backup'] is not None:
                    _relative(origin['backup'])
            elif kind == 'block':
                if not {'kind', 'path', 'component', 'start_marker', 'end_marker', 'owned_block_sha256'} <= set(entry) or set(entry) - {'kind', 'path', 'component', 'start_marker', 'end_marker', 'owned_block_sha256', 'origin_existed', 'owned_file_sha256', 'origin_backup', 'origin_sha256'} or ('origin_existed' in entry and type(entry['origin_existed']) is not bool) or ('owned_file_sha256' in entry and not _hash(entry['owned_file_sha256'])) or ('origin_backup' in entry and not isinstance(entry['origin_backup'], str)) or ('origin_sha256' in entry and not _hash(entry['origin_sha256'])) or not _hash(entry['owned_block_sha256']) or not all(isinstance(entry[k], str) and entry[k] for k in ('start_marker', 'end_marker')):
                    raise OwnershipError('invalid block ownership')
                if 'origin_backup' in entry:
                    _relative(entry['origin_backup'])
            elif kind == 'json_members':
                if set(entry) != {'kind', 'path', 'component', 'members', 'origin_existed'} or type(entry['origin_existed']) is not bool or not isinstance(entry['members'], dict) or not entry['members']:
                    raise OwnershipError('invalid JSON ownership')
                for pointer, record in entry['members'].items():
                    if not isinstance(pointer, str) or not pointer.startswith('/') or not isinstance(record, dict) or set(record) != {'origin_exists', 'owned_value'} or type(record['origin_exists']) is not bool or record['origin_exists']:
                        raise OwnershipError('invalid JSON member')
            elif kind == 'tree':
                if set(entry) != {'kind', 'path', 'component', 'origin_existed', 'owned_tree_sha256', 'file_count'} or type(entry['origin_existed']) is not bool or not _hash(entry['owned_tree_sha256']) or type(entry['file_count']) is not int or entry['file_count'] < 0:
                    raise OwnershipError('invalid tree ownership')
            else:
                raise OwnershipError('unknown ownership kind')
            if not _managed_entry(scope, entry):
                raise OwnershipError('ownership entry outside managed scope')
            backup = entry.get('origin_backup') or entry.get('origin', {}).get('backup')
            if backup is not None and not _managed_backup(scope, entry, backup):
                raise OwnershipError('ownership backup outside managed scope')
            if key != _key(entry):
                raise OwnershipError('ownership entry key mismatch')
            identity = (name, entry.get('start_marker', '') if kind == 'block' else next(iter(entry['members'])) if kind == 'json_members' and len(entry['members']) == 1 else '')
            if identity in seen or any((name.startswith(other + '/') or other.startswith(name + '/')) for other, other_kind in seen if kind == 'tree' or other_kind == 'tree'):
                raise OwnershipError('conflicting ownership entry')
            seen.add(identity)
    return data


def load(root):
    root = Path(root).resolve()
    raw = _read(root, LEDGER)
    return None if raw is None else _validate(root, json.loads(raw))


def _new(root):
    now = _time()
    return {'schema_version': 1, 'repo_path': str(root), 'created_at': now, 'updated_at': now, 'components': {scope: {'entries': {}} for scope in COMPONENTS}}


def _save(root, data):
    data['updated_at'] = _time()
    _validate(root, data)
    _write(root, LEDGER, _json(data))


def _key(entry):
    return entry['kind'] + ':' + entry['path'] + (':' + entry['start_marker'] if entry['kind'] == 'block' else ':' + next(iter(entry['members'])) if entry['kind'] == 'json_members' and len(entry['members']) == 1 else '')


def _record(root, scope, entry):
    root = Path(root).resolve()
    data = load(root) or _new(root)
    entries = data['components'][scope]['entries']
    key = _key(entry)
    previous = entries.get(key)
    if previous:
        if previous['kind'] != entry['kind'] or previous['path'] != entry['path']:
            raise OwnershipError('ownership conflict')
        if entry['kind'] == 'file':
            entry['origin'] = previous['origin']
        elif entry['kind'] == 'tree':
            entry['origin_existed'] = previous['origin_existed']
        elif entry['kind'] == 'block':
            for field in ('origin_existed', 'origin_backup', 'origin_sha256'):
                if field in previous:
                    entry[field] = previous[field]
        elif entry['kind'] == 'json_members':
            entry['origin_existed'] = previous['origin_existed']
            entry['members'] = {**previous['members'], **entry['members']}
    entries[key] = entry
    _save(root, data)


def record_file(root, scope, name, before, after, backup=None, component=None):
    if before == after:
        return
    root = Path(root).resolve()
    old_data = load(root)
    prior = next((e for e in old_data['components'][scope]['entries'].values() if e['kind'] == 'file' and e['path'] == name), None) if old_data else None
    if before is not None and prior and digest(before) != prior['owned']['sha256']:
        return  # A user edit before this run cannot become a new owned baseline.
    if before is not None and backup is None and prior is None:
        return  # Never claim a pre-existing file without a durable exact origin.
    if _read(root, name) != after:
        raise OwnershipError('file changed before ownership receipt: ' + name)
    if before is not None and backup is not None and _read(root, backup) != before:
        raise OwnershipError('origin backup mismatch: ' + name)
    _record(root, scope, {'kind': 'file', 'path': name, 'component': component or scope,
                          'origin': {'existed': before is not None, 'sha256': digest(before) if before is not None else None, 'backup': backup}, 'owned': {'sha256': digest(after)}})


def _block(raw, start, end):
    start, end = start.encode(), end.encode()
    if raw is None or raw.count(start) == raw.count(end) == 0:
        return None
    if raw.count(start) != 1 or raw.count(end) != 1 or raw.index(start) > raw.index(end):
        raise OwnershipError('ambiguous managed block')
    return raw[raw.index(start):raw.index(end) + len(end)]


def record_block(root, scope, name, start, end, block, component=None, origin_existed=True, before=None, backup=None):
    root = Path(root).resolve()
    if _block(_read(root, name), start, end) != block:
        raise OwnershipError('block changed before ownership receipt')
    data = load(root)
    prior = next((e for e in data['components'][scope]['entries'].values() if e['kind'] == 'block' and e['path'] == name and e['start_marker'] == start), None) if data else None
    if prior and before is not None and digest(before) != prior.get('owned_file_sha256'):
        return  # An outside edit must not become part of a full-file restore.
    entry = {'kind': 'block', 'path': name, 'component': component or scope, 'start_marker': start, 'end_marker': end, 'owned_block_sha256': digest(block), 'origin_existed': origin_existed, 'owned_file_sha256': digest(_read(root, name))}
    if before is not None and backup is not None and _read(root, backup) == before:
        entry['origin_backup'] = backup
        entry['origin_sha256'] = digest(before)
    _record(root, scope, entry)


def record_json_members(root, scope, name, before, members, component=None):
    root = Path(root).resolve()
    current = json.loads(_read(root, name))
    for pointer, value in members.items():
        if not pointer.startswith('/') or _member(current, pointer) != value:
            raise OwnershipError('JSON member changed before ownership receipt')
    for pointer, value in members.items():
        _record(root, scope, {'kind': 'json_members', 'path': name, 'component': component or scope,
                              'origin_existed': before is not None, 'members': {pointer: {'origin_exists': False, 'owned_value': value}}})


def _member(data, pointer):
    value = data
    for part in pointer[1:].split('/'):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def record_generated_file(root, scope, name, before_sha256, component=None):
    root = Path(root).resolve()
    after = _file_digest(root, name)
    if after is None or after == before_sha256:
        return
    data = load(root)
    prior = next((e for e in data['components'][scope]['entries'].values() if e['kind'] == 'file' and e['path'] == name), None) if data else None
    if before_sha256 is not None and (prior is None or prior['owned']['sha256'] != before_sha256):
        return
    _record(root, scope, {'kind': 'file', 'path': name, 'component': component or scope,
                          'origin': {'existed': False, 'sha256': None, 'backup': None}, 'owned': {'sha256': after}})


def _tree(root, name):
    path = _path(root, name)
    if not path.exists():
        return None
    if not path.is_dir():
        raise OwnershipError('not a tree: ' + name)
    rows = []
    for base, dirs, files in os.walk(path, followlinks=False):
        for child in sorted(dirs + files):
            item = Path(base) / child
            rel = item.relative_to(path).as_posix()
            info = item.lstat()
            if stat.S_ISDIR(info.st_mode):
                rows.append(('d', rel, ''))
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                rows.append(('f', rel, _file_digest(root, item.relative_to(root).as_posix())))
            else:
                raise OwnershipError('link or special file in tree: ' + name)
    return digest(_json(sorted(rows))), sum(row[0] == 'f' for row in rows)


def record_tree(root, scope, name, origin_existed, component=None, before_identity=None):
    if origin_existed:
        return
    root = Path(root).resolve()
    old_data = load(root)
    prior = next((e for e in old_data['components'][scope]['entries'].values() if e['kind'] == 'tree' and e['path'] == name), None) if old_data else None
    if prior and before_identity is not None and before_identity != (prior['owned_tree_sha256'], prior['file_count']):
        return
    identity = _tree(root, name)
    if identity is not None:
        _record(root, scope, {'kind': 'tree', 'path': name, 'component': component or scope, 'origin_existed': False, 'owned_tree_sha256': identity[0], 'file_count': identity[1]})


def _tracked(root, name):
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--', name], capture_output=True, check=True)
    return bool(result.stdout)


def _classify(root, entry):
    name, kind = entry['path'], entry['kind']
    try:
        path = _path(root, name)
        if kind == 'tree':
            actual = _tree(root, name)
            if actual is None:
                return 'ALREADY_REMOVED', 'tree absent', None
            if entry['origin_existed'] or actual != (entry['owned_tree_sha256'], entry['file_count']) or _tracked(root, name):
                return 'PRESERVE_MODIFIED', 'tree changed, pre-existing, or tracked', None
            return 'SAFE_DELETE', 'exact owned tree', None
        raw = None if kind == 'file' else _read(root, name)
        if kind == 'block':
            part = _block(raw, entry['start_marker'], entry['end_marker'])
            if part is None:
                return 'ALREADY_REMOVED', 'block absent', None
            if digest(part) != entry['owned_block_sha256']:
                return 'PRESERVE_MODIFIED', 'managed block changed', None
            if entry.get('origin_backup') and digest(raw) == entry.get('owned_file_sha256'):
                old = _read(root, entry['origin_backup'])
                if old is not None and digest(old) == entry['origin_sha256']:
                    return 'SAFE_RESTORE', 'exact owned file and origin', old
            return 'SAFE_SUBTRACT', 'exact owned block', raw.replace(part, b'', 1)
        if kind == 'file':
            current_hash = _file_digest(root, name)
            if current_hash is None:
                return 'ALREADY_REMOVED', 'file absent', None
            origin = entry['origin']
            if origin['existed'] and current_hash == origin['sha256']:
                return 'ALREADY_REMOVED', 'origin already restored', None
            if current_hash != entry['owned']['sha256']:
                return 'PRESERVE_MODIFIED', 'file changed', None
            if not origin['existed']:
                if _tracked(root, name):
                    return 'PRESERVE_EXTERNAL', 'created file is Git tracked', None
                return 'SAFE_DELETE', 'exact owned file', None
            old = _read(root, origin['backup'])
            if old is None or digest(old) != origin['sha256']:
                return 'PRESERVE_UNPROVEN', 'origin backup missing or changed', None
            return 'SAFE_RESTORE', 'exact owned file and origin', old
        if raw is None:
            return 'ALREADY_REMOVED', 'file absent', None
        if kind == 'json_members':
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError('JSON is not object')
            changed = False
            for pointer, record in entry['members'].items():
                present = _member(data, pointer)
                if present is None:
                    return 'ALREADY_REMOVED', 'owned JSON member absent', None
                if present != record['owned_value']:
                    return 'PRESERVE_MODIFIED', 'owned JSON member changed', None
                parts = pointer[1:].split('/')
                obj = data
                for part in parts[:-1]:
                    obj = obj[part]
                del obj[parts[-1]]
                changed = True
            if not changed:
                return 'ALREADY_REMOVED', 'members absent', None
            if not entry['origin_existed'] and data == {'schema_version': 1, 'capabilities': {}} and not _tracked(root, name):
                return 'SAFE_DELETE', 'new owned JSON file empty', None
            return 'SAFE_SUBTRACT', 'exact owned JSON members', _json(data)
    except (OwnershipError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        return 'PRESERVE_UNPROVEN', str(exc), None
    return 'PRESERVE_UNPROVEN', 'unknown entry', None


def _legacy(root, terrain_only):
    candidates = (('.terrain/aidev.json', 'terrain'), ('.aidev/terrain/state.json', 'terrain'), ('.aidev/state.json', 'core'), ('.codex/config.toml', 'core'), ('graphify-out', 'core'), ('.code-review-graph', 'core'))
    actions = []
    for name, scope in candidates:
        if terrain_only and scope != 'terrain':
            continue
        try:
            if _path(root, name).exists():
                actions.append({'path': name, 'component': scope, 'action': 'PRESERVE_UNPROVEN', 'reason': 'legacy origin not proven'})
        except OwnershipError:
            actions.append({'path': name, 'component': scope, 'action': 'PRESERVE_UNPROVEN', 'reason': 'unsafe path'})
    for name in ('AGENTS.override.md', 'AGENTS.md'):
        try:
            raw = _read(root, name)
            if raw is None:
                continue
            import aidev
            import terrain_provider
            definitions = ((aidev.CODE_START, aidev.CODE_END, aidev.CODE_GUIDANCE.encode(), 'core'),
                           (terrain_provider.START, terrain_provider.END, terrain_provider.GUIDANCE.encode(), 'terrain'))
            for start, end, known, scope in definitions:
                if terrain_only and scope != 'terrain':
                    continue
                part = _block(raw, start, end)
                if part is not None:
                    actions.append({'path': name, 'component': scope, 'action': 'SAFE_SUBTRACT' if part == known else 'PRESERVE_MODIFIED', 'reason': 'exact legacy aidev marker and content' if part == known else 'legacy managed block changed'})
        except (OwnershipError, OSError, ImportError):
            actions.append({'path': name, 'component': 'terrain' if terrain_only else 'core', 'action': 'PRESERVE_UNPROVEN', 'reason': 'unsafe or ambiguous legacy guidance'})
    return actions


def _remove_tree(root, name, expected, on_write):
    path = _path(root, name)
    if _tree(root, name) != expected:
        raise OwnershipError('tree changed before deletion')
    file_hashes = {}
    for base, dirs, files in os.walk(path, followlinks=False):
        for filename in files:
            item = Path(base) / filename
            info = item.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OwnershipError('tree child changed before deletion')
            file_hashes[item.relative_to(path).as_posix()] = _file_digest(root, item.relative_to(root).as_posix())
    if _tree(root, name) != expected:
        raise OwnershipError('tree changed before deletion')
    for base, dirs, files in os.walk(path, topdown=False, followlinks=False):
        for filename in files:
            item = Path(base) / filename
            info = item.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or _file_digest(root, item.relative_to(root).as_posix()) != file_hashes.get(item.relative_to(path).as_posix()):
                raise OwnershipError('tree child changed during deletion')
            item.unlink()
            on_write(item.relative_to(root).as_posix())
        for dirname in dirs:
            item = Path(base) / dirname
            if not stat.S_ISDIR(item.lstat().st_mode):
                raise OwnershipError('tree directory changed during deletion')
            item.rmdir()
            on_write(item.relative_to(root).as_posix())
    path.rmdir()
    on_write(name)


class RemovalJournal:
    """Write-ahead recovery evidence; never trust an old pointer as a write path."""

    def __init__(self, root, actions, ledger):
        self.root = root
        self.previous = read_progress(root)
        self.directory = Path(tempfile.mkdtemp(prefix='aidev-remove-recovery-'))
        self.record = {'schema_version': 1, 'repo_path': str(root), 'status': 'preparing',
                       'actions': actions, 'completed': [], 'pending': None, 'changed_paths': [],
                       'before': {}}
        if ledger is not None:
            _write(self.directory, 'ownership.before.json', ledger)
        if self.previous is not None:
            _write(self.directory, 'previous-progress.json', self.previous)
        # Every modified/deleted file is retained, including derived trees.
        for name in dict.fromkeys(a['path'] for a in actions if a['action'].startswith('SAFE_')):
            path = _path(root, name)
            if path.is_dir():
                names = [p.relative_to(root).as_posix() for p in path.rglob('*')]
                names.insert(0, name)
            else:
                names = [name]
            for relative in names:
                source = _path(root, relative)
                if source.is_dir():
                    self.record['before'][relative] = {'kind': 'directory'}
                    continue
                before = _file_digest(root, relative)
                if before is None:
                    raise OwnershipError('source disappeared during recovery backup: ' + relative)
                saved = self.directory / 'before' / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, saved)
                with saved.open('rb') as stream:
                    os.fsync(stream.fileno())
                if _file_digest(self.directory, 'before/' + relative) != before or _file_digest(root, relative) != before:
                    raise OwnershipError('source changed during recovery backup: ' + relative)
                self.record['before'][relative] = {'kind': 'file', 'sha256': before}
        self.record['status'] = 'in_progress'
        self.flush()
        self.pointer = _json({'schema_version': 1, 'repo_path': str(root), 'recovery_backup': str(self.directory)})
        if _read(root, PROGRESS) != self.previous:
            raise OwnershipError('concurrent recovery pointer change')
        _write(root, PROGRESS, self.pointer)

    def flush(self):
        _write(self.directory, 'journal.json', _json(self.record))

    def check(self):
        if _read(self.root, PROGRESS) != self.pointer:
            raise OwnershipError('concurrent recovery pointer change')

    def begin(self, name, action):
        self.check()
        self.record['pending'] = {'path': name, 'action': action}
        self.flush()

    def changed(self, name):
        self.record['changed_paths'].append(name)
        self.flush()

    def done(self):
        self.record['completed'].append(self.record['pending'])
        self.record['pending'] = None
        self.flush()

    def finish(self):
        self.check()
        self.record['status'] = 'complete'
        self.flush()
        _path(self.root, PROGRESS).unlink()


def read_progress(root):
    raw = _read(root, PROGRESS)
    if raw is not None:
        data = json.loads(raw)
        if (not isinstance(data, dict) or set(data) != {'schema_version', 'repo_path', 'recovery_backup'}
                or type(data['schema_version']) is not int or data['schema_version'] != 1
                or data['repo_path'] != str(root) or not isinstance(data['recovery_backup'], str)
                or not Path(data['recovery_backup']).is_absolute()
                or not Path(data['recovery_backup']).name.startswith('aidev-remove-recovery-')):
            raise OwnershipError('unrecognized removal progress; preserved')
    return raw


def _local_residue(root):
    """Find local content other than the ledger and the ignore barrier itself."""
    for name in ('.aidev', '.terrain/agent', '.terrain/.meta', '.serena/cache', '.serena/runtime',
                 '.serena/memories', '.serena/logs', '.serena/project.local.yml', 'graphify-out', '.code-review-graph'):
        path = _path(root, name)
        if not path.exists():
            continue
        if not path.is_dir():
            return True
        for base, dirs, files in os.walk(path, followlinks=False):
            for child in dirs + files:
                relative = (Path(base) / child).relative_to(root).as_posix()
                if relative not in (LEDGER, '.aidev/.gitignore', '.aidev/.lock'):
                    return True
    return False


def remove(root, dry_run=False, terrain_only=False):
    root = Path(root).resolve()
    changed = False
    recovery = None
    journal = None
    actions = []
    try:
        read_progress(root)
        if _tracked(root, LEDGER) or _tracked(root, PROGRESS):
            raise OwnershipError('ownership ledger or removal progress is Git tracked; preserved')
        ledger_before = _read(root, LEDGER)
        data = load(root)
        def check_ledger():
            if _read(root, LEDGER) != ledger_before:
                raise OwnershipError('concurrent ownership ledger change')
        check_ledger()
        if data is None:
            actions = _legacy(root, terrain_only)
            safe = [item for item in actions if item['action'] == 'SAFE_SUBTRACT']
            preserved = any(item['action'].startswith('PRESERVE') for item in actions)
            if dry_run:
                check_ledger()
                status = 'REMOVE_PARTIAL' if preserved else 'REMOVE_READY' if safe else 'NOT_INSTALLED'
                return {'status': status, 'writes': False, 'root': str(root), 'actions': actions}
            planned = []
            for item in safe:
                name = item['path']
                start, end = (('<!-- aidev:terrain:start -->', '<!-- aidev:terrain:end -->') if item['component'] == 'terrain' else ('<!-- aidev:code-intelligence:start -->', '<!-- aidev:code-intelligence:end -->'))
                raw = _read(root, name)
                planned.append((name, raw, _block(raw, start, end)))
            if _legacy(root, terrain_only) != actions:
                raise OwnershipError('concurrent legacy guidance change')
            if planned or _read(root, PROGRESS) is not None:
                journal = RemovalJournal(root, actions, ledger_before)
                recovery = journal.directory
                changed = True
            expected_legacy = {name: raw for name, raw, _ in planned}
            for name, raw, block in planned:
                check_ledger()
                current = _read(root, name)
                if current != expected_legacy[name] or block is None or current.count(block) != 1:
                    raise OwnershipError('concurrent legacy guidance change')
                updated = current.replace(block, b'', 1)
                journal.begin(name, 'SAFE_SUBTRACT')
                _write(root, name, updated)
                expected_legacy[name] = updated
                changed = True
                journal.changed(name)
                journal.done()
            if journal:
                check_ledger()
                journal.finish()
            status = 'REMOVED_WITH_PRESERVED' if preserved else 'REMOVED' if safe else 'NOT_INSTALLED'
            return {'status': status, 'writes': changed, 'root': str(root), 'actions': actions, 'recovery_backup': str(recovery) if recovery else None}
        scopes = ('terrain',) if terrain_only else ('terrain', 'core')
        items = [(scope, key, entry) for scope in scopes for key, entry in data['components'][scope]['entries'].items()]
        items.sort(key=lambda item: item[2]['path'] in ('.aidev/state.json', '.aidev/terrain/state.json'))
        if not items and _read(root, PROGRESS) is None:
            return {'status': 'NOT_INSTALLED', 'writes': False, 'root': str(root), 'actions': []}
        planned = [(scope, key, entry, *_classify(root, entry)) for scope, key, entry in items]
        # Provider-owned derived state remains when its MCP registration is manual
        # or cannot be removed. A matching path or default value is not ownership.
        for provider in ('serena', 'crg'):
            removable = any(entry['kind'] == 'block' and entry['path'] == '.codex/config.toml'
                            and entry['start_marker'] == f'# aidev:mcp:{provider}:start'
                            and action in ('SAFE_SUBTRACT', 'SAFE_RESTORE')
                            for _, _, entry, action, _, _ in planned)
            if not removable:
                planned = [(scope, key, entry, 'PRESERVE_EXTERNAL', 'provider MCP remains external or modified', None)
                           if entry['component'] == 'core.' + provider and entry['kind'] in ('file', 'tree') and action in ('SAFE_DELETE', 'SAFE_RESTORE')
                           else (scope, key, entry, action, reason, value)
                           for scope, key, entry, action, reason, value in planned]
        unresolved = [entry for _, _, entry, action, _, _ in planned if action.startswith('PRESERVE')]
        needed_backups = {entry.get('origin_backup') or entry.get('origin', {}).get('backup')
                          for entry in unresolved}
        if unresolved:
            planned = [(scope, key, entry, 'PRESERVE_EXTERNAL', 'state retained for partial removal', None)
                       if entry['path'] in ('.aidev/state.json', '.aidev/terrain/state.json') and action == 'SAFE_DELETE'
                       else (scope, key, entry, action, reason, value)
                       for scope, key, entry, action, reason, value in planned]
            planned = [(scope, key, entry, 'PRESERVE_EXTERNAL', 'origin backup needed by unresolved ownership', None)
                       if entry['kind'] == 'tree' and any(path and path.startswith(entry['path'] + '/') for path in needed_backups)
                       and action == 'SAFE_DELETE'
                       else (scope, key, entry, action, reason, value)
                       for scope, key, entry, action, reason, value in planned]
        if unresolved or _local_residue(root):
            planned = [(scope, key, entry, 'PRESERVE_EXTERNAL', 'ignore barrier retained for local content or unresolved ownership', None)
                       if entry['kind'] == 'block' and entry['path'] in IGNORE_PATHS and action in ('SAFE_SUBTRACT', 'SAFE_RESTORE')
                       else (scope, key, entry, action, reason, value)
                       for scope, key, entry, action, reason, value in planned]
        actions = [{'path': entry['path'], 'component': entry['component'], 'action': action, 'reason': reason} for _, _, entry, action, reason, _ in planned]
        preserved = any(a['action'].startswith('PRESERVE') for a in actions)
        if dry_run:
            check_ledger()
            return {'status': 'REMOVE_PARTIAL' if preserved else 'REMOVE_READY', 'writes': False, 'root': str(root), 'actions': actions}
        # All planned decisions are bound to current evidence before the first write.
        check_ledger()
        if any(_classify(root, entry) != (action, reason, value) for _, _, entry, action, reason, value in planned if not action.startswith('PRESERVE')):
            raise OwnershipError('concurrent change before remove')
        cleanup = {entry['path'] for _, _, entry, action, _, _ in planned if entry['kind'] == 'block' and entry.get('origin_existed') is False and entry.get('owned_file_sha256') == digest(_read(root, entry['path']) or b'') and action == 'SAFE_SUBTRACT'}
        expected = {entry['path']: (_tree(root, entry['path']) if entry['kind'] == 'tree' else _file_digest(root, entry['path']) if entry['kind'] == 'file' else _read(root, entry['path'])) for _, _, entry, action, _, _ in planned if not action.startswith('PRESERVE')}
        if any(not action.startswith('PRESERVE') for _, _, _, action, _, _ in planned) or _read(root, PROGRESS) is not None:
            journal = RemovalJournal(root, actions, ledger_before)
            recovery = journal.directory
            changed = True
        mutated_paths = set()
        def mark_changed(name):
            nonlocal changed
            changed = True
            journal.changed(name)
        for scope, key, entry, action, reason, value in planned:
            if action.startswith('PRESERVE'):
                continue
            check_ledger()
            name = entry['path']
            current = _tree(root, name) if entry['kind'] == 'tree' else _file_digest(root, name) if entry['kind'] == 'file' else _read(root, name)
            if current != expected[name]:
                raise OwnershipError('concurrent change during remove')
            fresh_action, fresh_reason, fresh_value = _classify(root, entry)
            if (fresh_action, fresh_reason) != (action, reason):
                if entry['kind'] == 'block' and fresh_action == 'ALREADY_REMOVED' and name in mutated_paths:
                    action = 'ALREADY_REMOVED'
                elif not (entry['kind'] == 'json_members' and action == 'SAFE_SUBTRACT' and fresh_action == 'SAFE_DELETE' and entry['origin_existed'] is False):
                    raise OwnershipError('concurrent change during remove')
                action = fresh_action
            value = fresh_value
            journal.begin(name, action)
            check_ledger()
            if action == 'SAFE_DELETE':
                if entry['kind'] == 'tree':
                    _remove_tree(root, name, expected[name], mark_changed)
                else:
                    _path(root, name).unlink()
                expected[name] = None
                mutated_paths.add(name)
                changed = True
            elif action in ('SAFE_RESTORE', 'SAFE_SUBTRACT'):
                _write(root, name, value)
                expected[name] = _file_digest(root, name) if entry['kind'] == 'file' else value
                mutated_paths.add(name)
                changed = True
            if action in ('SAFE_DELETE', 'SAFE_RESTORE', 'SAFE_SUBTRACT') and entry['kind'] != 'tree':
                journal.changed(name)
            del data['components'][scope]['entries'][key]
            check_ledger()
            _save(root, data)
            ledger_before = _read(root, LEDGER)
            changed = True
            journal.done()
        for name in cleanup:
            if not any(e['path'] == name for scope in COMPONENTS for e in data['components'][scope]['entries'].values()):
                raw = _read(root, name)
                if raw is not None and raw.strip() == b'' and set(raw) <= {10} and not _tracked(root, name):
                    check_ledger()
                    if raw != expected[name]:
                        raise OwnershipError('concurrent change before empty file cleanup')
                    journal.begin(name, 'DELETE_EMPTY_OWNED_FILE')
                    _path(root, name).unlink()
                    changed = True
                    journal.changed(name)
                    journal.done()
        if not any(data['components'][scope]['entries'] for scope in COMPONENTS):
            check_ledger()
            _path(root, LEDGER).unlink()
            changed = True
            ledger_before = None
        if journal:
            check_ledger()
            journal.finish()
        return {'status': 'REMOVED_WITH_PRESERVED' if preserved else 'REMOVED', 'writes': changed, 'root': str(root), 'actions': actions, 'recovery_backup': str(recovery) if recovery else None}
    except (OwnershipError, OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {'status': 'ERROR', 'writes': changed, 'root': str(root), 'error': str(exc), 'actions': actions,
                'completed_actions': journal.record['completed'] if journal else [],
                'pending_action': journal.record['pending'] if journal else None,
                'recovery_backup': str(recovery) if recovery else None}


def recorded(root, scope, kind, name, marker=None):
    data = load(root)
    if data is None:
        return False
    return any(e['kind'] == kind and e['path'] == name and (marker is None or e.get('start_marker') == marker)
               for e in data['components'][scope]['entries'].values())


def block_matches_receipt(root, scope, name, marker, block):
    data = load(root)
    return bool(data and any(e['kind'] == 'block' and e['path'] == name and e['start_marker'] == marker
                             and e['owned_block_sha256'] == digest(block)
                             for e in data['components'][scope]['entries'].values()))


def record_change(root, scope, name, before, after, backup=None):
    """Claim only a write with a precise unit and an unchanged on-disk result."""
    if before == after:
        return
    if name == '.codex/dev-capabilities.json' and scope == 'core':
        old = json.loads(before) if before else {'capabilities': {}}
        new = json.loads(after)
        added = {'/capabilities/' + key: value for key, value in new['capabilities'].items()
                 if key not in old.get('capabilities', {})}
        if added:
            record_json_members(root, scope, name, before, added)
        return
    markers = []
    if name in ('AGENTS.md', 'AGENTS.override.md'):
        markers = [('<!-- aidev:code-intelligence:start -->', '<!-- aidev:code-intelligence:end -->') if scope == 'core'
                   else ('<!-- aidev:terrain:start -->', '<!-- aidev:terrain:end -->')]
    elif name == '.codex/config.toml' and scope == 'core':
        markers = [(f'# aidev:mcp:{server}:start', f'# aidev:mcp:{server}:end') for server in ('serena', 'crg')]
    elif name in ('.gitignore', '.graphifyignore', '.code-review-graphignore', '.aidev/.gitignore', '.terrain/.gitignore'):
        markers = [(f'# aidev:{scope}:{name}:start', f'# aidev:{scope}:{name}:end')]
    if markers:
        for start, end in markers:
            block = _block(after, start, end)
            if block is not None and (_block(before, start, end) is None or recorded(root, scope, 'block', name, start)):
                record_block(root, scope, name, start, end, block, origin_existed=before is not None, before=before, backup=backup)
        return
    component = "core.serena" if scope == "core" and name.startswith(".serena/") else scope
    record_file(root, scope, name, before, after, backup, component=component)
