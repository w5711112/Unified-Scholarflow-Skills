"""Mechanical cache cleanup through workspace-hygiene; semantic files stay protected."""
import argparse
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import sys
import time
from ecosystem_maintenance import plain_path

PLUGIN=Path(__file__).resolve().parents[1]

def clean_root(root,quarantine,*,apply=False):
    path=PLUGIN/'skills/workspace-hygiene/scripts/workspace_hygiene.py'
    spec=importlib.util.spec_from_file_location('workspace_hygiene',path)
    m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
    # Source/test files and PPT versions are never semantic candidates.
    policy={'automatic_cleanup':True,'protected_names':['_ppt-shared-assets']}
    report=m.scan_workspace(root,policy);proposal=m.build_proposal(report,[])
    result={'root':str(root),'candidates':[asdict(c) for c in proposal.candidates]}
    if apply and proposal.candidates:
        plain_path(quarantine.parent);quarantine.parent.mkdir(parents=True,exist_ok=True)
        result['result']=asdict(m.apply_proposal(proposal,quarantine,None))
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');args=p.parse_args()
    data=json.loads((PLUGIN/'ecosystem-registry.json').read_text(encoding='utf-8'))
    roots=[Path(data['roots']['agents-home']['path'])/'skills']
    for c in data['components']:
        if c['kind']=='plugin' and c['status']=='active':roots.append(Path(data['roots'][c['root']]['path'])/c['relative_path'])
    outputs=[]
    for i,root in enumerate(roots):
        plain_path(root)
        # Same-volume, outside the scanned root. No drive-wide scan or deletion.
        anchor=Path(data['roots']['agents-home']['path']) if root.drive.lower()=='c:' else root.parent
        quarantine=anchor/'quarantine'/f'mechanical-cache-{time.time_ns()}-{i}'
        outputs.append(clean_root(root,quarantine,apply=args.apply))
    print(json.dumps(outputs,ensure_ascii=False))

if __name__=='__main__':main()
