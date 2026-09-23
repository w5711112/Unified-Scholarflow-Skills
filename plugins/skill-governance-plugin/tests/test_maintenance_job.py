import importlib.util
from pathlib import Path
import json
import sys

def test_job_failure_is_recorded_and_success_not_fabricated(tmp_path):
    source=Path(__file__).resolve().parents[1]/'scripts/maintenance_job.py'
    assert source.exists(),'bounded scheduler job missing'
    sys.path.insert(0,str(source.parent))
    spec=importlib.util.spec_from_file_location('maintenance_job',source)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    script=tmp_path/'fail.py';script.write_text('raise SystemExit(7)')
    result=m.run_commands([[sys.executable,str(script)]],tmp_path/'latest.json')
    assert result==7
    saved=json.loads((tmp_path/'latest.json').read_text())
    assert saved['status']=='blocked' and saved['steps'][0]['returncode']==7

def test_successful_job_has_bounded_latest_result(tmp_path):
    source=Path(__file__).resolve().parents[1]/'scripts/maintenance_job.py'
    assert source.exists(),'bounded scheduler job missing'
    sys.path.insert(0,str(source.parent))
    spec=importlib.util.spec_from_file_location('maintenance_job',source)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    assert m.run_commands([[sys.executable,'-c','print("[]")']],tmp_path/'latest.json')==0
    assert json.loads((tmp_path/'latest.json').read_text())['status']=='ok'
