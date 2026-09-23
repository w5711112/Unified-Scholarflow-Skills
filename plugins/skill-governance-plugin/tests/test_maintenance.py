import importlib.util
import sys
from pathlib import Path
import pytest
import json

ROOT = Path(__file__).resolve().parents[1]


def subject():
    path = ROOT / 'scripts/ecosystem_maintenance.py'
    assert path.exists(), 'maintenance implementation is missing'
    spec = importlib.util.spec_from_file_location('ecosystem_maintenance', path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def test_sync_conflict_keeps_both_files(tmp_path):
    m = subject()
    a, b = tmp_path / 'a.md', tmp_path / 'b.md'
    a.write_bytes(b'old'); b.write_bytes(b'manual edit')
    plan = {str(a): b'new', str(b): b'new'}
    baseline = {str(a): m.digest(b'old'), str(b): m.digest(b'old')}
    with pytest.raises(ValueError, match='DERIVED_EDIT_CONFLICT'):
        m.apply_generated(plan, baseline, tmp_path / 'recovery', apply=True)
    assert a.read_bytes() == b'old'
    assert b.read_bytes() == b'manual edit'


def test_dry_run_and_noop(tmp_path):
    m = subject()
    a = tmp_path / 'a.md'; a.write_bytes(b'old')
    base = {str(a): m.digest(b'old')}
    report = m.apply_generated({str(a): b'new'}, base, tmp_path / 'recovery', apply=False)
    assert a.read_bytes() == b'old' and report['changed'] == [str(a)]
    m.apply_generated({str(a): b'new'}, base, tmp_path / 'recovery', apply=True)
    before = a.stat().st_mtime_ns
    assert m.apply_generated({str(a): b'new'}, {str(a): m.digest(b'new')}, tmp_path / 'recovery', apply=True)['changed'] == []
    assert a.stat().st_mtime_ns == before


def test_unknown_existing_target_requires_review(tmp_path):
    m = subject(); p = tmp_path / 'user.md'; p.write_bytes(b'user')
    with pytest.raises(ValueError, match='UNTRACKED_TARGET'):
        m.apply_generated({str(p): b'generated'}, {}, tmp_path / 'recovery', apply=True)
    assert p.read_bytes() == b'user'


def test_failed_commit_rolls_back(tmp_path, monkeypatch):
    m = subject(); a, b = tmp_path / 'a', tmp_path / 'b'
    a.write_bytes(b'a'); b.write_bytes(b'b')
    original = m.replace_bytes
    def fail_once(p, value):
        if p == b and value == b'new':
            raise OSError('simulated locked file')
        original(p, value)
    monkeypatch.setattr(m, 'replace_bytes', fail_once)
    with pytest.raises(OSError):
        m.apply_generated({str(a): b'new', str(b): b'new'}, {str(a): m.digest(b'a'), str(b): m.digest(b'b')}, tmp_path / 'recovery', apply=True)
    assert a.read_bytes() == b'a' and b.read_bytes() == b'b'


def test_due_uses_last_success_and_detects_clock_problem():
    m = subject()
    assert m.is_due(None, 100, 40)
    assert m.is_due(50, 100, 40)
    assert not m.is_due(70, 100, 40)
    with pytest.raises(ValueError, match='CLOCK_REVERSED'):
        m.is_due(101, 100, 40)


def test_state_only_success_does_not_accumulate_recovery_directories(tmp_path):
    m=subject(); p=tmp_path/'guide'; p.write_bytes(b'current')
    state=tmp_path/'state.json'; state.write_bytes(b'{"last_success":1}')
    result=m.apply_generated({str(p):b'current'}, {str(p):m.digest(b'current')},tmp_path/'recovery-next',apply=True,state_path=state,state_payload=b'{"last_success":2}')
    assert result['changed']==[] and result['applied']
    assert state.read_bytes()==b'{"last_success":2}'
    assert not (tmp_path/'recovery-next').exists()


def test_retired_target_is_not_silently_untracked(tmp_path):
    m=subject(); p=tmp_path/'old.md'; p.write_bytes(b'valuable')
    with pytest.raises(ValueError,match='TARGET_RETIREMENT_REQUIRED'):
        m.apply_generated({}, {str(p):m.digest(b'valuable')}, tmp_path/'recovery', apply=True)
    assert p.read_bytes()==b'valuable'


def test_pending_transaction_blocks_fresh_commit(tmp_path):
    m=subject(); old=tmp_path/'recovery-old'; old.mkdir()
    (old/'journal.json').write_text(json.dumps({'status':'prepared'}))
    with pytest.raises(ValueError,match='RECOVERY_PENDING'):
        m.apply_generated({str(tmp_path/'new'):b'new'}, {}, tmp_path/'recovery-new', apply=True)
    assert not (tmp_path/'new').exists()


def test_state_commit_failure_rolls_back_content(tmp_path,monkeypatch):
    m=subject(); p=tmp_path/'guide'; p.write_bytes(b'old')
    state=tmp_path/'state.json'; state.write_bytes(b'{}')
    original=m.replace_bytes
    def fail_state(path,value):
        if path==state: raise OSError('state locked')
        original(path,value)
    monkeypatch.setattr(m,'replace_bytes',fail_state)
    with pytest.raises(OSError,match='state locked'):
        m.apply_generated({str(p):b'new'}, {str(p):m.digest(b'old')},tmp_path/'recovery',apply=True,state_path=state,state_payload=b'{"updated":true}')
    assert p.read_bytes()==b'old' and state.read_bytes()==b'{}'


def test_source_membership_change_invalidates_render(tmp_path):
    sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'tests'))
    from test_ecosystem_overview import make_registry,load_overview
    m=subject(); overview=load_overview(); registry,note=make_registry(tmp_path)
    note.write_text(overview.AUTO_BEGIN+'\n'+overview.AUTO_END)
    _,guard=m.build_desired(registry)
    data=overview.load_registry(registry)
    source=Path(data['roots']['agents-home']['path'])/'skills/two/references/new.md'
    source.write_text('new requirement')
    with pytest.raises(ValueError,match='SOURCE_SET_CHANGED'): guard()
