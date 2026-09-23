const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');

function fixture() {
  const context = vm.createContext({console});
  vm.runInContext(fs.readFileSync(path.join(root, 'annotation_bridge.js'), 'utf8'), context);
  const security = context.ZoteroNativeAnnotationBridge;
  security.configureSecurity({getProfileSecret: () => 'a'.repeat(64),
    sha256Hex: x => crypto.createHash('sha256').update(x).digest('hex'),
    hmacSha256Hex: (k,x) => crypto.createHmac('sha256',k).update(x).digest('hex'),
    now: () => Math.floor(Date.now()/1000)});
  const file = path.join(root, 'merge_bridge.js');
  assert.ok(fs.existsSync(file), 'restricted merge implementation is missing');
  vm.runInContext(fs.readFileSync(file,'utf8'),context);
  const bridge = context.ZoteroParentMergeBridge;
  let rows = [
    {key:'MASTER01',itemType:'conferencePaper',title:'A Study',DOI:'10.1/test',tags:[{tag:'one'}],collections:['COLL0001']},
    {key:'OTHER001',itemType:'conferencePaper',title:'A Study',DOI:'10.1/test',tags:[{tag:'two'}],collections:['COLL0002']},
    {key:'PDF00001',itemType:'attachment',parentItem:'MASTER01',contentType:'application/pdf'},
    {key:'PDF00002',itemType:'attachment',parentItem:'OTHER001',contentType:'application/pdf'},
    {key:'ANNOT001',itemType:'annotation',parentItem:'PDF00002',annotationComment:'keep this'},
    {key:'NOTE0001',itemType:'note',parentItem:'OTHER001',note:'user note'},
  ];
  let writes=0, fail=false;
  const runtime = {
    userLibraryID:1,
    async snapshot(keys) {return structuredClone(rows.filter(r => keys.includes(r.key) || keys.includes(r.parentItem) || r.itemType==='annotation'));},
    async transaction(fn) {const before=structuredClone(rows); try{return await fn();}catch(e){rows=before;throw e;}},
    async mergePreservingAttachments(master,others) {
      writes++;
      for(const r of rows) if(r.itemType==='attachment' && others.includes(r.parentItem)) r.parentItem=master;
      if(fail) throw new Error('injected native failure');
      for(const r of rows) if(r.itemType==='note' && others.includes(r.parentItem)) r.parentItem=master;
      const m=rows.find(r=>r.key===master), o=rows.find(r=>r.key===others[0]);
      m.tags.push(...o.tags);m.collections.push(...o.collections);
      m.relations={'dc:replaces':['http://zotero.org/users/local/fixture/items/'+o.key]};o.deleted=true;
    },
  };
  bridge.configure(security,runtime);
  const plan={schema_version:1,operation_id:'merge-test',library_id:1,master_key:'MASTER01',other_keys:['OTHER001'],identity_evidence_sha256:'b'.repeat(64)};
  return {bridge,security,plan,runtime,rows:()=>rows,writes:()=>writes,fail:()=>{fail=true;}};
}
function applyBody(plan,pre) {return {...plan,snapshot_digest:pre.snapshot_digest,receipt:pre.receipt};}

test('preflight is read-only and apply keeps every attachment and annotation key',async()=>{
 const f=fixture(), before=structuredClone(f.rows());const p=await f.bridge.preflight(f.plan);
 assert.deepEqual(f.rows(),before);assert.equal(f.writes(),0);
 const result=await f.bridge.apply(applyBody(f.plan,p));
 assert.equal(result.master_key,'MASTER01');assert.equal(f.writes(),1);
 assert.equal(f.rows().find(r=>r.key==='OTHER001').deleted,true);
 assert.equal(f.rows().find(r=>r.key==='PDF00002').parentItem,'MASTER01');
 assert.deepEqual(f.rows().find(r=>r.key==='ANNOT001'),before.find(r=>r.key==='ANNOT001'));
 assert.equal(f.rows().filter(r=>r.itemType==='attachment'&&!r.deleted).length,2);
});
test('changed snapshot blocks apply without writes',async()=>{const f=fixture(),p=await f.bridge.preflight(f.plan);f.rows()[4].annotationComment='new';await assert.rejects(f.bridge.apply(applyBody(f.plan,p)),/snapshot_changed/);assert.equal(f.writes(),0);});
test('different DOI and different item type are blocked',async()=>{const f=fixture();f.rows()[1].DOI='10.2/other';await assert.rejects(f.bridge.preflight(f.plan),/identity_conflict/);f.rows()[1].DOI='10.1/test';f.rows()[1].itemType='journalArticle';await assert.rejects(f.bridge.preflight(f.plan),/identity_conflict/);assert.equal(f.writes(),0);});
test('tampered master or forged receipt cannot write',async()=>{const f=fixture(),p=await f.bridge.preflight(f.plan);await assert.rejects(f.bridge.apply({...applyBody(f.plan,p),master_key:'OTHER001',other_keys:['MASTER01']}),/receipt/);await assert.rejects(f.bridge.apply({...applyBody(f.plan,p),receipt:'bad'}),/receipt/);assert.equal(f.writes(),0);});
test('unknown fields and cross-library requests are rejected',async()=>{const f=fixture();await assert.rejects(f.bridge.preflight({...f.plan,script:'bad'}),/unknown_field/);await assert.rejects(f.bridge.preflight({...f.plan,library_id:2}),/library/);assert.equal(f.writes(),0);});
test('failed native operation rolls back and can be re-preflighted',async()=>{const f=fixture(),before=structuredClone(f.rows()),p=await f.bridge.preflight(f.plan);f.fail();await assert.rejects(f.bridge.apply(applyBody(f.plan,p)),/injected/);assert.deepEqual(f.rows(),before);assert.equal((await f.bridge.preflight(f.plan)).snapshot_digest,p.snapshot_digest);});
test('replaying committed request does not merge twice',async()=>{const f=fixture(),p=await f.bridge.preflight(f.plan);await f.bridge.apply(applyBody(f.plan,p));await assert.rejects(f.bridge.apply(applyBody(f.plan,p)));assert.equal(f.writes(),1);});
test('HTTP merge endpoint rejects missing authentication and browser Origin',async()=>{const f=fixture(),server={Endpoints:{}};f.bridge.registerEndpoints(server);const route='/zotero-local-bridge/v1/merge/preflight',endpoint=new server.Endpoints[route]();const req={method:'POST',pathname:route,headers:{'content-type':'application/json'},data:f.plan};assert.equal((await endpoint.init(req))[0],401);req.headers.origin='https://example.com';assert.equal((await endpoint.init(req))[0],403);delete req.headers.origin;req.headers['x-zotero-local-bridge-auth']=f.security.signRequestAuthentication('POST',route,Math.floor(Date.now()/1000),f.plan);assert.equal((await endpoint.init(req))[0],200);});

function formalPlan(f) {
 return {...f.plan,formal_metadata:{itemType:'conferencePaper',title:'A Study',date:'2024',
  DOI:'10.1/test',creators:[{creatorType:'author',firstName:'A',lastName:'Researcher'}],
  proceedingsTitle:'Verified Conference',url:'https://publisher.example/paper'}};
}
test('reviewed metadata resolves type and venue suffix while preserving child keys',async()=>{
 const f=fixture();f.rows()[0].title='A Study（Conference, 2024）';f.rows()[0].itemType='journalArticle';
 f.runtime.updateMetadata=async(key,fields)=>Object.assign(f.rows().find(r=>r.key===key),structuredClone(fields));
 const plan=formalPlan(f),pre=await f.bridge.preflight(plan);
 assert.equal(f.rows()[0].itemType,'journalArticle');
 await f.bridge.apply(applyBody(plan,pre));
 assert.equal(f.rows()[0].itemType,'conferencePaper');assert.equal(f.rows()[0].title,'A Study');
 assert.equal(f.rows()[0].date,'2024');assert.equal(f.rows()[4].parentItem,'PDF00002');
});
test('metadata receipt cannot authorize unrelated title, DOI or extra fields',async()=>{
 const f=fixture(),plan=formalPlan(f);
 await assert.rejects(f.bridge.preflight({...plan,formal_metadata:{...plan.formal_metadata,deleted:true}}));
 await assert.rejects(f.bridge.preflight({...plan,formal_metadata:{...plan.formal_metadata,title:'Unrelated work'}}));
 await assert.rejects(f.bridge.preflight({...plan,formal_metadata:{...plan.formal_metadata,DOI:'10.2/other'}}));
 assert.equal(f.writes(),0);
});
test('metadata readback mismatch rolls back parent merge',async()=>{
 const f=fixture(),before=structuredClone(f.rows()),plan=formalPlan(f);
 f.runtime.updateMetadata=async()=>{};
 const pre=await f.bridge.preflight(plan);
 await assert.rejects(f.bridge.apply(applyBody(plan,pre)),/metadata_readback_mismatch/);
 assert.deepEqual(f.rows(),before);
});

function preprintPlan(f) {
 return {...f.plan,preprint_metadata:{itemType:'preprint',title:'A Study',date:'2025-10-18',
  DOI:'10.48550/arXiv.2510.16624',repository:'arXiv',archiveID:'2510.16624',
  creators:[{creatorType:'author',firstName:'A',lastName:'Researcher'}],url:'https://arxiv.org/abs/2510.16624'}};
}
test('explicit existing-preprint correction merges erroneous journal classification',async()=>{
 const f=fixture();f.rows()[0].itemType='journalArticle';f.rows()[0].DOI='';f.rows()[1].itemType='preprint';f.rows()[1].DOI='';
 f.runtime.updateMetadata=async(key,fields)=>Object.assign(f.rows().find(r=>r.key===key),structuredClone(fields));
 const plan=preprintPlan(f),pre=await f.bridge.preflight(plan);
 await f.bridge.apply(applyBody(plan,pre));assert.equal(f.rows()[0].itemType,'preprint');assert.equal(f.rows()[0].repository,'arXiv');
 assert.equal(f.rows()[4].parentItem,'PDF00002');
});
test('preprint correction cannot override formal DOI or claim a journal venue',async()=>{
 const f=fixture(),plan=preprintPlan(f);
 await assert.rejects(f.bridge.preflight(plan),/identity_conflict/);
 f.rows()[0].DOI='';f.rows()[1].DOI='';
 await assert.rejects(f.bridge.preflight({...plan,preprint_metadata:{...plan.preprint_metadata,publicationTitle:'Fake Journal'}}));
 await assert.rejects(f.bridge.preflight({...plan,formal_metadata:formalPlan(f).formal_metadata}));
 await assert.rejects(f.bridge.preflight({...plan,preprint_metadata:{...plan.preprint_metadata,url:'https://arxiv.org/abs/2510.99999'}}));
 assert.equal(f.writes(),0);
});
