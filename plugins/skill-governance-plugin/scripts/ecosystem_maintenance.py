"""Finite, stdlib-only maintenance of registered derived reading surfaces.

Never edits canonical rules, publishes a release lock, or deletes semantic files.
Existing targets require a reviewed baseline. Run --adopt only after inspecting them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
from contextlib import contextmanager


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def plain_path(path: Path) -> None:
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or getattr(part.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError(f'REPARSE_PATH:{part}')


def replace_bytes(path: Path, value: bytes) -> None:
    plain_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.maintenance-next')
    with temporary.open('xb') as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def is_due(last_success: float | None, now: float, interval: float) -> bool:
    if last_success is None:
        return True
    if now < last_success:
        raise ValueError('CLOCK_REVERSED')
    return now - last_success >= interval


def apply_generated(desired: dict[str, bytes], baseline: dict[str, str], recovery: Path, *, apply: bool = False, source_guard=None, state_path=None, state_payload=None) -> dict:
    retired = sorted(set(baseline) - set(desired))
    if retired:
        raise ValueError('TARGET_RETIREMENT_REQUIRED:' + '|'.join(retired))
    plain_path(recovery.parent)
    for previous in recovery.parent.glob('recovery-*'):
        plain_path(previous)
        journal = previous / 'journal.json'
        plain_path(journal)
        if not journal.is_file() or json.loads(journal.read_text(encoding='utf-8')).get('status') not in {'committed','rolled_back'}:
            raise ValueError(f'RECOVERY_PENDING:{previous}')
    output_hashes = {name: digest(value) for name,value in desired.items()}
    desired, baseline = dict(desired), dict(baseline)
    if state_path is not None:
        if str(state_path) in desired or not isinstance(state_payload,bytes):
            raise ValueError('STATE_TARGET_INVALID')
        plain_path(state_path)
        if state_path.exists(): baseline[str(state_path)] = digest(state_path.read_bytes())
        desired[str(state_path)] = state_payload
    originals, changed = {}, []
    for name, payload in desired.items():
        path = Path(name)
        if not path.is_absolute():
            raise ValueError('TARGET_NOT_ABSOLUTE')
        plain_path(path)
        old = path.read_bytes() if path.exists() else None
        originals[name] = old
        if old == payload:
            continue
        if old is not None and name not in baseline:
            raise ValueError(f'UNTRACKED_TARGET:{name}')
        if name in baseline and (old is None or digest(old) != baseline[name]):
            raise ValueError(f'DERIVED_EDIT_CONFLICT:{name}')
        changed.append(name)
    result = {'changed': [n for n in changed if n != str(state_path)], 'applied': False, 'hashes': output_hashes}
    if not apply or not changed:
        return result
    if source_guard:
        source_guard()
    if state_path is not None and changed == [str(state_path)]:
        # No content transaction exists: atomically advance one success timestamp.
        # Do not accumulate a backup/journal on every healthy nightly no-op.
        current = state_path.read_bytes() if state_path.exists() else None
        if current != originals[str(state_path)]:
            raise ValueError(f'TARGET_CHANGED_DURING_COMMIT:{state_path}')
        replace_bytes(state_path, state_payload)
        if state_path.read_bytes() != state_payload:
            raise ValueError(f'READBACK_MISMATCH:{state_path}')
        result['applied'] = True
        return result
    # Recovery must not replace an unresolved earlier transaction.
    plain_path(recovery)
    if recovery.exists():
        raise ValueError(f'RECOVERY_PENDING:{recovery}')
    recovery.mkdir(parents=True)
    journal = {'status': 'prepared', 'targets': []}
    for i, name in enumerate(changed):
        old = originals[name]
        backup = recovery / str(i)
        if old is not None:
            backup.write_bytes(old)
        journal['targets'].append({'path': name, 'backup': str(backup) if old is not None else None, 'new_hash': digest(desired[name])})
    journal_path = recovery / 'journal.json'
    journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding='utf-8')
    written = []
    try:
        for name in changed:
            path = Path(name)
            plain_path(path)
            current = path.read_bytes() if path.exists() else None
            if current != originals[name]:
                raise ValueError(f'TARGET_CHANGED_DURING_COMMIT:{name}')
            if source_guard:
                source_guard()
            replace_bytes(path, desired[name])
            written.append(name)
            if path.read_bytes() != desired[name]:
                raise ValueError(f'READBACK_MISMATCH:{name}')
    except Exception:
        errors = []
        for name in reversed(written):
            try:
                path = Path(name)
                if path.read_bytes() != desired[name]:
                    raise ValueError('TARGET_CHANGED_BEFORE_ROLLBACK')
                if originals[name] is None:
                    path.unlink()
                else:
                    replace_bytes(path, originals[name])
            except Exception as error:
                errors.append(f'{name}:{error}')
        journal.update(status='rollback_incomplete' if errors else 'rolled_back', errors=errors)
        journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding='utf-8')
        raise
    journal['status'] = 'committed'
    journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding='utf-8')
    result['applied'] = True
    result['recovery'] = str(recovery)
    return result


@contextmanager
def single_run(path: Path):
    plain_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def build_desired(registry: Path):
    import ecosystem_overview as overview
    data = overview.load_registry(registry)
    root = overview.resolve_guides_root(registry)
    desired, sources = {}, {str(registry): digest(registry.read_bytes())}
    memberships = {}
    for component in overview._active_skills(data):
        source = overview._component_path(component, data)
        memberships[source] = {str(p) for p in overview._semantic_files(source)}
        for path in overview._semantic_files(source):
            plain_path(path)
            sources[str(path)] = digest(path.read_bytes())
        target = overview._guide_path(root, component, data['guides'])
        desired[str(target)] = overview.render_guide(component, data).encode('utf-8')
        for mirror in component.get('mirror_packages', []):
            anchor = Path(data['roots'][mirror['root']]['path'])
            destination = anchor / mirror['relative_path']
            plain_path(destination)
            if anchor.resolve() not in destination.resolve().parents:
                raise ValueError('MIRROR_OUTSIDE_ROOT')
            for path in overview._semantic_files(source):
                desired[str(destination / path.relative_to(source))] = path.read_bytes()
    note = overview.resolve_overview_path(registry)
    current = note.read_text(encoding='utf-8')
    desired[str(note)] = overview._replace_auto_block(current, overview.render_generated_block(data)).encode('utf-8')
    def source_guard():
        for source, expected in memberships.items():
            if {str(p) for p in overview._semantic_files(source)} != expected:
                raise ValueError(f'SOURCE_SET_CHANGED:{source}')
        for name, expected in sources.items():
            plain_path(Path(name))
            if digest(Path(name).read_bytes()) != expected:
                raise ValueError(f'SOURCE_CHANGED:{name}')
    source_guard()
    return desired, source_guard


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, default=Path(__file__).resolve().parents[1] / 'ecosystem-registry.json')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--adopt', action='store_true', help='Record reviewed current target hashes; no content replacement')
    parser.add_argument('--due-only', action='store_true')
    args = parser.parse_args()
    data = json.loads(args.registry.read_text(encoding='utf-8'))
    config = data['maintenance']
    state_root = Path(data['roots'][config['state_root']]['path']) / config['state_relative_path']
    anchor = Path(data['roots'][config['state_root']]['path']).resolve()
    if anchor not in state_root.resolve().parents:
        raise ValueError('STATE_OUTSIDE_ROOT')
    plain_path(state_root)
    with single_run(state_root / 'maintenance.lock'):
        state_path = state_root / 'state.json'
        state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
        if args.due_only and not is_due(state.get('last_success'), time.time(), 86400):
            print(json.dumps({'status': 'not_due'})); return
        desired, guard = build_desired(args.registry)
        if args.adopt:
            if args.apply:
                raise ValueError('ADOPT_AND_APPLY_EXCLUSIVE')
            state['targets'] = {name: digest(Path(name).read_bytes()) for name in desired if Path(name).exists()}
            replace_bytes(state_path, json.dumps(state, ensure_ascii=False, indent=2).encode('utf-8'))
            print(json.dumps({'status': 'baseline_adopted', 'targets': len(state['targets'])})); return
        next_state = dict(state, targets={name:digest(value) for name,value in desired.items()}, last_success=time.time())
        result = apply_generated(desired, state.get('targets', {}), state_root / ('recovery-' + str(time.time_ns())), apply=args.apply, source_guard=guard,
            state_path=state_path if args.apply else None, state_payload=json.dumps(next_state,ensure_ascii=False,indent=2).encode('utf-8') if args.apply else None)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'status': 'blocked', 'error': str(error)}, ensure_ascii=False))
        sys.exit(1)
