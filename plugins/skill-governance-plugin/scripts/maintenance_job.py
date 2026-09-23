"""Bounded local scheduler entry: synchronize, then audit. Never edits Skill rules."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from ecosystem_maintenance import plain_path, replace_bytes, single_run


def run_commands(commands, report_path):
    report={'started_at':time.time(),'status':'running','steps':[]}
    code=0
    try:
        for command in commands:
            result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=600,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
                env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
            report['steps'].append({'command':command,'returncode':result.returncode,'stdout':result.stdout[-64000:],'stderr':result.stderr[-4000:]})
            if result.returncode:code=result.returncode;break
    except Exception as error:
        report['error']=str(error);code=1
    report.update(status='blocked' if code else 'ok',finished_at=time.time())
    replace_bytes(report_path,json.dumps(report,ensure_ascii=False,indent=2).encode('utf-8'))
    return code


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--catch-up',action='store_true');args=parser.parse_args()
    plugin=Path(__file__).resolve().parents[1];registry=plugin/'ecosystem-registry.json'
    data=json.loads(registry.read_text(encoding='utf-8'));config=data['maintenance']
    anchor=Path(data['roots'][config['state_root']]['path']);root=anchor/config['state_relative_path']
    if anchor.resolve() not in root.resolve().parents:raise ValueError('STATE_OUTSIDE_ROOT')
    plain_path(root)
    with single_run(root/'job.lock'):
        report=root/'latest-job.json'
        if args.catch_up and report.exists():
            previous=json.loads(report.read_text(encoding='utf-8'))
            now=datetime.now(timezone(timedelta(hours=8)))
            boundary=now.replace(hour=2,minute=0,second=0,microsecond=0)
            if now<boundary:boundary-=timedelta(days=1)
            if previous.get('status')=='ok' and previous.get('finished_at',0)>=boundary.timestamp():return 0
        interpreter=Path(sys.executable)
        if interpreter.name.lower()=='pythonw.exe':interpreter=interpreter.with_name('python.exe')
        base=[str(interpreter),'-B','-X','utf8']
        return run_commands([base+[str(plugin/'scripts/maintenance_cache.py'),'--apply'],base+[str(plugin/'scripts/ecosystem_maintenance.py'),'--apply'],base+[str(plugin/'scripts/skillctl.py'),'audit','--json']],report)


if __name__=='__main__':sys.exit(main())
