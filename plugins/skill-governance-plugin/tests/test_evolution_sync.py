from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_ecosystem_overview import load_overview, load_skillctl, make_registry, marker


def test_release_hash_ignores_office_owner_locks_but_keeps_real_assets(tmp_path):
    m = load_skillctl()
    (tmp_path / 'deck.pptx').write_bytes(b'original deck')
    before = m._tree_sha256(tmp_path)
    (tmp_path / '~$deck.pptx').write_bytes(b'transient owner')
    assert m._tree_sha256(tmp_path) == before
    (tmp_path / 'deck.pptx').write_bytes(b'changed deck')
    changed = m._tree_sha256(tmp_path)
    assert changed != before
    (tmp_path / '~$rules.md').write_text('a real unusual rule name')
    assert m._tree_sha256(tmp_path) != changed


def test_overview_noop_preserves_mtime(tmp_path):
    m = load_overview()
    registry, note = make_registry(tmp_path)
    note.write_text(f"{marker(m, registry, 'research.one')}\n{marker(m, registry, 'global.two')}\n{m.AUTO_BEGIN}\nold\n{m.AUTO_END}\n", encoding="utf-8")
    m.sync_overview(registry)
    before = note.stat().st_mtime_ns
    m.sync_overview(registry)
    assert note.stat().st_mtime_ns == before


def test_strict_guides_reject_broken_source_link_before_writing(tmp_path):
    m = load_overview()
    registry, _ = make_registry(tmp_path)
    data = m.load_registry(registry)
    data['guides']['strict_links'] = True
    registry.write_text(json.dumps(data), encoding='utf-8')
    import pytest
    with pytest.raises(ValueError, match='GUIDE_LINK_MISSING'):
        m.sync_guides(registry)
    assert not (m.resolve_guides_root(registry) / 'research' / 'one-完整指南.md').exists()


def test_generated_roles_track_actual_source_description(tmp_path):
    m = load_overview()
    registry, _ = make_registry(tmp_path)
    data = m.load_registry(registry)
    data['overview']['source_roles'] = True
    source = Path(data['roots']['research-project']['path']) / 'skills/one/SKILL.md'
    source.write_text('---\nname: one\ndescription: ONLY VERIFIED SOURCE ROLE\n---\n# One\n', encoding='utf-8')
    rendered = m.render_generated_block(data)
    assert 'ONLY VERIFIED SOURCE ROLE' in rendered
    assert 'one-完整指南' in rendered


def test_guide_starts_with_entry_and_uses_real_source_anchors(tmp_path):
    m = load_overview()
    registry, _ = make_registry(tmp_path)
    data = m.load_registry(registry)
    component = next(c for c in data['components'] if c['id'] == 'global.two')
    text = m.render_guide(component, data)
    assert text.index('## SKILL.md') < text.index('## references/rules.md')
    assert '(#^source-' in text
    for target in __import__('re').findall(r'\(#\^(source-[a-f0-9]+)\)', text):
        assert f'\n^{target}\n' in text


def test_package_mirror_detects_reference_drift(tmp_path):
    import shutil
    overview=load_overview(); ctl=load_skillctl()
    registry,_=make_registry(tmp_path); data=overview.load_registry(registry)
    source=Path(data['roots']['agents-home']['path'])/'skills/two'
    mirror=tmp_path/'drafts/two';shutil.copytree(source,mirror)
    data['roots']['drafts']={'kind':'derived','path':str(tmp_path/'drafts')}
    component=next(c for c in data['components'] if c['id']=='global.two')
    component['mirror_packages']=[{'root':'drafts','relative_path':'two'}]
    assert not [f for f in ctl.validate_registry(data) if f.code=='MIRROR_PACKAGE_MISMATCH']
    (mirror/'references/rules.md').write_text('independent edit',encoding='utf-8')
    assert [f for f in ctl.validate_registry(data) if f.code=='MIRROR_PACKAGE_MISMATCH']
