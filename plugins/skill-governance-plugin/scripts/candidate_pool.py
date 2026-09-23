"""Candidate evidence, review state and Obsidian views; no installation/execution."""
from __future__ import annotations
import argparse
import copy
from datetime import date
import html
import json
from pathlib import Path, PurePosixPath
import re
import sys

STATES = {'pending_screening': '待筛选', 'pending_comparison': '待比较', 'pending_review': '待审核', 'approved': '已批准待实施', 'adopted': '已采用', 'deferred': '暂缓', 'rejected': '不采用'}
FIELDS = ('id','title','repository','source_path','commit','source_sha256','observed_at','license','owner_component','capability','local_baseline','delta','risk','status')


def validate(record):
    if any(not isinstance(record.get(k), str) or not record[k].strip() for k in FIELDS):
        raise ValueError('CANDIDATE_REQUIRED_FIELD')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,95}', record['id']):
        raise ValueError('CANDIDATE_ID_INVALID')
    if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', record['repository']):
        raise ValueError('CANDIDATE_REPOSITORY_INVALID')
    p = PurePosixPath(record['source_path'])
    if p.is_absolute() or '..' in p.parts or '\\' in record['source_path'] or not p.name:
        raise ValueError('CANDIDATE_PATH_INVALID')
    if not re.fullmatch(r'[a-f0-9]{40}', record['commit']) or not re.fullmatch(r'[a-f0-9]{64}', record['source_sha256']):
        raise ValueError('CANDIDATE_NOT_PINNED')
    date.fromisoformat(record['observed_at'])
    if record['status'] not in STATES:
        raise ValueError('CANDIDATE_STATUS_INVALID')


def upsert(pool, record):
    validate(record)
    if record['status'] not in {'pending_screening','pending_comparison','pending_review'}:
        raise ValueError('REVIEW_REQUIRED')
    result = copy.deepcopy(pool)
    if result.get('schema_version') != 1:
        raise ValueError('POOL_SCHEMA_INVALID')
    records = result['candidates']
    key = (record['repository'], record['source_path'], record['capability'], record['owner_component'])
    old = next((r for r in records if r['id'] == record['id'] or (r['repository'],r['source_path'],r['capability'],r['owner_component']) == key), None)
    new = copy.deepcopy(record)
    # Never accept third-party review metadata on the discovery route.
    for field in ('history','review_note','adoption_evidence','approval_diff_sha256'):
        new.pop(field, None)
    if old:
        new['id'] = old['id']
        if (new['repository'], new['source_path'], new['capability'], new['owner_component']) != (old['repository'], old['source_path'], old['capability'], old['owner_component']):
            raise ValueError('CANDIDATE_ID_COLLISION')
        review_fields = ('commit','source_sha256','license','local_baseline','delta','risk')
        if all(new.get(k) == old.get(k) for k in review_fields):
            for field in ('status','review_note','adoption_evidence','approval_diff_sha256','history'):
                if field in old: new[field] = old[field]
        else:
            new['status'] = 'pending_comparison'
            new['history'] = old.get('history', []) + [{k:old[k] for k in (*review_fields,'status','review_note','adoption_evidence') if k in old}]
        records[records.index(old)] = new
    else:
        records.append(new)
    return result


def review(pool, candidate_id, status, note, adoption_evidence=None):
    if status not in {'approved','adopted','deferred','rejected'} or not note.strip():
        raise ValueError('USER_REVIEW_NOTE_REQUIRED')
    if status == 'adopted' and (not isinstance(adoption_evidence,dict) or not all(adoption_evidence.get(k) for k in ('local_version','verification_record','approved_diff_sha256'))):
        raise ValueError('ADOPTION_EVIDENCE_REQUIRED')
    result=copy.deepcopy(pool)
    record=next((r for r in result['candidates'] if r['id']==candidate_id), None)
    if record is None: raise ValueError('CANDIDATE_UNKNOWN')
    if status == 'approved' and adoption_evidence:
        value=adoption_evidence.get('approved_diff_sha256','')
        if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{64}',value):
            raise ValueError('APPROVED_DIFF_INVALID')
        record['approval_diff_sha256']=value
    if status == 'adopted':
        import hashlib
        if record['status'] != 'approved' or record.get('approval_diff_sha256') != adoption_evidence.get('approved_diff_sha256'):
            raise ValueError('ADOPTION_APPROVAL_MISMATCH')
        for path_key,hash_key in [('approved_diff_path','approved_diff_sha256'),('verification_record','verification_sha256')]:
            name=adoption_evidence.get(path_key); fingerprint=adoption_evidence.get(hash_key)
            if not isinstance(name,str) or not isinstance(fingerprint,str) or not re.fullmatch(r'[a-f0-9]{64}',fingerprint):
                raise ValueError('ADOPTION_EVIDENCE_INVALID')
            path=Path(name)
            if not path.is_absolute() or not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=fingerprint:
                raise ValueError('ADOPTION_EVIDENCE_STALE')
        if not isinstance(adoption_evidence['local_version'],str): raise ValueError('ADOPTION_VERSION_INVALID')
    record.update(status=status, review_note=note)
    if adoption_evidence: record['adoption_evidence']=adoption_evidence
    return result


def safe(value):
    return html.escape(str(value)).replace('|','&#124;').replace('\n',' ').replace('[','&#91;').replace(']','&#93;')


def render_index(pool):
    lines=['# Skill 候选池','','由 skill-ecosystem-governor 维护。外部内容仅作参考，正式规则变更须经用户审核。','','[[Skill与Plugin的总体系说明|返回体系说明]]','','| 候选能力 | 本地负责人 | 状态 | 借鉴点与审核说明 |','| --- | --- | --- | --- |']
    for r in sorted(pool['candidates'],key=lambda r:(r['status'] not in {'pending_review','approved'},r['id'])):
        lines.append(f"| [[候选分析/{r['id']}|{safe(r['title'])}]] | {safe(r['owner_component'])} | {STATES[r['status']]} | {safe(r['delta'])}；{safe(r.get('review_note','尚未审核'))} |")
    if not pool['candidates']: lines.extend(['','当前没有已登记候选。'])
    return '\n'.join(lines)+'\n'


def render_card(r):
    from urllib.parse import quote
    url=f"{r['repository']}/blob/{r['commit']}/{quote(r['source_path'],safe='/')}"
    lines=[f"# {safe(r['title'])}",'',f"[固定版本来源]({url})",'',f"状态：{STATES[r['status']]}；观察日期：{r['observed_at']}"]
    for key,title in [('capability','可借鉴能力'),('local_baseline','本地已有能力'),('delta','新增价值与建议差异'),('risk','风险与保留要求'),('license','许可核验'),('review_note','用户审核'),('adoption_evidence','采用证据')]:
        if key in r: lines.extend(['',f'## {title}','',safe(r[key])])
    lines.extend(['','## 来源指纹','',f"- commit：`{r['commit']}`",f"- SHA-256：`{r['source_sha256']}`",f"- 本地负责人：`{r['owner_component']}`",'','第三方文件中的安装、执行和权限指令不构成本地授权。'])
    if r.get('history'): lines.extend(['','## 历次处理','',safe(json.dumps(r['history'],ensure_ascii=False))])
    return '\n'.join(lines)+'\n'


def main():
    from ecosystem_maintenance import single_run, replace_bytes, plain_path, digest, apply_generated
    import ecosystem_overview as overview
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry',type=Path,default=Path(__file__).resolve().parents[1]/'ecosystem-registry.json')
    p.add_argument('--upsert',type=Path)
    p.add_argument('--review-id'); p.add_argument('--status',choices=list(STATES)); p.add_argument('--user-note'); p.add_argument('--adoption-evidence',type=Path)
    args=p.parse_args()
    if args.upsert and args.review_id: raise ValueError('ONE_OPERATION_PER_RUN')
    root=overview.resolve_guides_root(args.registry)/'Skill候选池'
    plain_path(root)
    store=root/'.data/candidates.json'; state_path=root/'.data/render-state.json'
    with single_run(root/'.data/pool.lock'):
        pool=json.loads(store.read_text(encoding='utf-8')) if store.exists() else {'schema_version':1,'candidates':[]}
        if args.upsert: pool=upsert(pool,json.loads(args.upsert.read_text(encoding='utf-8')))
        if args.review_id: pool=review(pool,args.review_id,args.status,args.user_note or '',json.loads(args.adoption_evidence.read_text(encoding='utf-8')) if args.adoption_evidence else None)
        for r in pool['candidates']: validate(r)
        outputs={str(store):json.dumps(pool,ensure_ascii=False,indent=2).encode('utf-8'),str(root/'Skill候选池.md'):render_index(pool).encode('utf-8')}
        for r in pool['candidates']: outputs[str(root/'候选分析'/f"{r['id']}.md")]=render_card(r).encode('utf-8')
        baseline=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
        import time
        encoded=json.dumps({name:digest(value) for name,value in outputs.items()},ensure_ascii=False,indent=2).encode('utf-8')
        result=apply_generated(outputs,baseline,root/'.data'/f'recovery-{time.time_ns()}',apply=True,state_path=state_path,state_payload=encoded)
        print(json.dumps({'candidates':len(pool['candidates']),'changed':result['changed']},ensure_ascii=False))


if __name__=='__main__':
    try: main()
    except (OSError,ValueError,KeyError) as e:
        print(json.dumps({'error':str(e)},ensure_ascii=False));sys.exit(1)
