"""Run only against the dedicated disposable profile, never the production port."""
import argparse
import json
import sys
import urllib.request
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--client-scripts',type=Path,required=True)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--preprint',action='store_true')
    args=parser.parse_args()
    assert args.profile.name=='merge-isolated-profile' and (args.profile/'MERGE_TEST_ONLY').is_file()
    sys.path.insert(0,str(args.client_scripts))
    from zotero_local_bridge_client import ZoteroLocalBridgeClient, BridgeError
    base='http://127.0.0.1:23129'
    client=ZoteroLocalBridgeClient(token_path=args.profile/'zotero-local-bridge'/'auth-token',base_url=base,timeout=30)
    def fixture(action=None):
        data=None if action is None else json.dumps({'action':action}).encode()
        req=urllib.request.Request(base+'/test/merge-fixture',data=data,headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(exc.read().decode('utf-8',errors='replace')) from exc
    health=client.health()
    assert health['plugin_version']=='2.1.0',health
    original=fixture()
    master,other=original['parents']
    plan={'schema_version':1,'operation_id':'native-merge-fixture','library_id':original['library_id'],
          'master_key':master,'other_keys':[other],'identity_evidence_sha256':'b'*64}
    plan['formal_metadata']={'itemType':'journalArticle','title':'Preserve keys merge fixture',
        'DOI':'10.9999/fixture','date':'2026','publicationTitle':'Verified Fixture Journal',
        'url':'https://publisher.example/fixture','creators':[{'creatorType':'author','firstName':'A','lastName':'Tester'}]}
    if args.preprint:
        plan.pop('formal_metadata')
        plan['preprint_metadata']={'itemType':'preprint','title':'Preserve keys merge fixture',
            'DOI':'10.48550/arXiv.2510.16624','date':'2025-10-18','repository':'arXiv','archiveID':'2510.16624',
            'url':'https://arxiv.org/abs/2510.16624','creators':[{'creatorType':'author','firstName':'A','lastName':'Tester'}]}
    pre=client._send('POST','/zotero-local-bridge/v1/merge/preflight',plan)
    assert fixture()==original,'preflight wrote data'
    body={**plan,'snapshot_digest':pre['snapshot_digest'],'receipt':pre['receipt']}
    assert fixture('fail')['armed'] is True,'failure injection was not armed'
    try:
        try:client._send('POST','/zotero-local-bridge/v1/merge/apply',body)
        except BridgeError as e:assert e.status==500,(e.status,e.code)
        else:raise AssertionError('injected failure did not stop merge')
    finally:fixture('disarm')
    assert fixture()==original,'native transaction failed to restore original state'
    result=client._send('POST','/zotero-local-bridge/v1/merge/apply',body)
    after=fixture()
    bykey={r['key']:r for r in after['items']}
    assert bykey[other]['deleted'] is True
    assert not bykey[master].get('deleted')
    metadata=plan.get('preprint_metadata',plan.get('formal_metadata'))
    for key,value in metadata.items():assert bykey[master][key]==value,(key,bykey[master].get(key),value)
    for r in original['items']:
        now=bykey[r['key']]
        if r['itemType']=='attachment':
            assert now['parentItem']==master and not now.get('deleted')
        if r['itemType']=='annotation':assert now==r,'annotation content/key changed'
        if r['itemType']=='note':assert now['note']==r['note'] and now['parentItem']==master
    tags={t['tag'] for t in bykey[master]['tags']}
    assert tags=={'fixture-0','fixture-1'},tags
    assert len(bykey[master]['collections'])==2
    relations=str(bykey[master]['relations'])
    assert other in relations,'replaced-item relation missing'
    try:client._send('POST','/zotero-local-bridge/v1/merge/apply',body)
    except BridgeError as e:assert e.status==409,(e.status,e.code)
    else:raise AssertionError('committed request replay accepted')
    report={'health':health,'metadata_correction_verified':True,'preflight_no_write':True,'native_failure_rollback':True,
            'attachment_keys_preserved':True,'annotations_and_notes_preserved':True,
            'tags_collections_relations_preserved':True,'replay_blocked':True,
            'parents':original['parents'],'before':original['items'],'after':after['items']}
    if args.report:
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'before','after'}},ensure_ascii=False))

if __name__=='__main__':main()
