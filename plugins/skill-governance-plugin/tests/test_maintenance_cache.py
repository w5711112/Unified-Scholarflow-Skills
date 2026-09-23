from pathlib import Path
import importlib.util
import sys

def test_cache_cleanup_preserves_old_scripts_and_ppt_sources(tmp_path):
    path=Path(__file__).resolve().parents[1]/'scripts/maintenance_cache.py'
    assert path.exists(),'scoped cache route missing'
    sys.path.insert(0,str(path.parent))
    spec=importlib.util.spec_from_file_location('maintenance_cache',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    root=tmp_path/'skills';cache=root/'academic-native-htmlppt-design/scripts/__pycache__/a.pyc'
    cache.parent.mkdir(parents=True);cache.write_bytes(b'cache')
    old=root/'v1.1.py';old.write_bytes(b'valuable')
    ppt=root/'academic-native-htmlppt-design/SKILL.md';ppt.write_bytes(b'rules')
    report=m.clean_root(root,tmp_path/'quarantine',apply=False)
    assert [r['relative_path'] for r in report['candidates']]==['academic-native-htmlppt-design/scripts/__pycache__/a.pyc']
    assert cache.exists() and old.read_bytes()==b'valuable' and ppt.read_bytes()==b'rules'
