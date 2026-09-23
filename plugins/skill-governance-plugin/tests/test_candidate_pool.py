import importlib.util
from pathlib import Path
import pytest


def subject():
    path = Path(__file__).resolve().parents[1] / 'scripts/candidate_pool.py'
    assert path.exists(), 'candidate manager is missing'
    spec = importlib.util.spec_from_file_location('candidate_pool', path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def item():
    return {'id': 'paperforge-reasoning', 'title': 'Research reasoning', 'repository': 'https://github.com/FeijiangHan/PaperForge', 'source_path': 'SKILL_CHN.md', 'commit': 'a'*40, 'source_sha256': 'b'*64, 'observed_at': '2026-09-20', 'license': 'not_verified', 'owner_component': 'research.read-paper-analysis-highlight', 'capability': 'prior-only reasoning', 'local_baseline': 'design causality already covered', 'delta': 'separate prior premises from target results', 'risk': 'hindsight and speculative author mental history', 'status': 'pending_comparison'}


def test_discovery_does_not_approve_and_deduplicates():
    m=subject(); pool={'schema_version':1, 'candidates':[]}
    first=m.upsert(pool,item()); second=m.upsert(first,item())
    assert len(second['candidates']) == 1
    proposal=item(); proposal['status']='approved'
    with pytest.raises(ValueError,match='REVIEW_REQUIRED'):
        m.upsert(second,proposal)


def test_new_commit_invalidates_prior_review():
    m=subject(); pool=m.upsert({'schema_version':1,'candidates':[]},item())
    pool=m.review(pool,'paperforge-reasoning','deferred','User: wait for license confirmation')
    same=m.upsert(pool,item())
    assert same['candidates'][0]['status']=='deferred'
    updated=item(); updated['commit']='c'*40; updated['source_sha256']='d'*64
    changed=m.upsert(same,updated)['candidates'][0]
    assert changed['status']=='pending_comparison'
    assert changed['history'][0]['review_note']=='User: wait for license confirmation'


def test_untrusted_link_and_path_rejected():
    m=subject()
    for key,value in [('repository','javascript:alert(1)'),('source_path','../secret'),('commit','main')]:
        bad=item(); bad[key]=value
        with pytest.raises(ValueError):m.upsert({'schema_version':1,'candidates':[]},bad)


def test_changed_proposal_requires_fresh_review_even_at_same_commit():
    m=subject(); pool=m.upsert({'schema_version':1,'candidates':[]},item())
    pool=m.review(pool,'paperforge-reasoning','approved','User approved this delta')
    changed=item(); changed['delta']='Replace every local rule'
    result=m.upsert(pool,changed)['candidates'][0]
    assert result['status']=='pending_comparison'
    assert 'review_note' not in result


def test_review_needs_reason_and_publication_evidence():
    m=subject(); pool=m.upsert({'schema_version':1,'candidates':[]},item())
    with pytest.raises(ValueError):m.review(pool,'paperforge-reasoning','rejected','')
    with pytest.raises(ValueError,match='ADOPTION_EVIDENCE_REQUIRED'):
        m.review(pool,'paperforge-reasoning','adopted','looks good')


def test_adoption_cannot_skip_approval_or_use_fake_evidence():
    m=subject(); pool=m.upsert({'schema_version':1,'candidates':[]},item())
    fake={'local_version':'v1','verification_record':'missing','approved_diff_sha256':'x'}
    with pytest.raises(ValueError):m.review(pool,'paperforge-reasoning','adopted','user',fake)


def test_adoption_binds_reviewed_diff_and_real_verification(tmp_path):
    import hashlib
    m=subject(); pool=m.upsert({'schema_version':1,'candidates':[]},item())
    diff=tmp_path/'approved.patch'; diff.write_bytes(b'exact reviewed change')
    receipt=tmp_path/'verification.json'; receipt.write_bytes(b'{"result":"pass"}')
    evidence={'local_version':'v1','approved_diff_path':str(diff),'approved_diff_sha256':hashlib.sha256(diff.read_bytes()).hexdigest(),'verification_record':str(receipt),'verification_sha256':hashlib.sha256(receipt.read_bytes()).hexdigest()}
    pool=m.review(pool,'paperforge-reasoning','approved','user approved',evidence)
    changed=dict(evidence,approved_diff_sha256='c'*64)
    with pytest.raises(ValueError):m.review(pool,'paperforge-reasoning','adopted','publish',changed)
    result=m.review(pool,'paperforge-reasoning','adopted','verified publication',evidence)
    assert result['candidates'][0]['status']=='adopted'


def test_render_keeps_review_reason_and_does_not_embed_raw_html():
    m=subject(); record=item(); record['title']='<script>alert(1)</script>'
    pool=m.upsert({'schema_version':1,'candidates':[]},record)
    pool=m.review(pool,record['id'],'deferred','license unknown')
    result=m.render_index(pool)
    assert 'license unknown' in result and '<script>' not in result
