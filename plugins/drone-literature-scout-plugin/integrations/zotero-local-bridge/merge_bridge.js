// Fixed native parent-merge operations. Identity research remains the caller's responsibility.
var ZoteroParentMergeBridge = (() => {
  const BASE = '/zotero-local-bridge/v1/merge/';
  const KEY = /^[A-Z0-9]{8}$/;
  const DIGEST = /^[a-f0-9]{64}$/;
  let security, runtime, server;
  const endpoints = {};
  function error(status, code) { const e = new Error(code); e.status = status; e.code = code; return e; }
  function configure(s, r) { security = s; runtime = r; }
  function validate(body, applying = false) {
    const allowed = ['schema_version','operation_id','library_id','master_key','other_keys','identity_evidence_sha256','formal_metadata','preprint_metadata'];
    if (applying) allowed.push('snapshot_digest','receipt');
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw error(400,'invalid_request');
    if (Object.keys(body).some(k => !allowed.includes(k))) throw error(400,'unknown_field');
    if (body.schema_version !== 1 || !/^[A-Za-z0-9._:-]{1,100}$/.test(body.operation_id || '')) throw error(422,'invalid_request');
    if (!Number.isSafeInteger(body.library_id) || body.library_id !== runtime.userLibraryID) throw error(422,'user_library_required');
    if (typeof body.master_key !== 'string' || !KEY.test(body.master_key)
        || !Array.isArray(body.other_keys) || body.other_keys.length < 1 || body.other_keys.length > 9
        || body.other_keys.some(k => typeof k !== 'string' || !KEY.test(k))) throw error(422,'invalid_keys');
    const keys = [body.master_key, ...body.other_keys];
    if (new Set(keys).size !== keys.length) throw error(422,'duplicate_keys');
    if (typeof body.identity_evidence_sha256 !== 'string' || !DIGEST.test(body.identity_evidence_sha256)) throw error(422,'identity_evidence_required');
    if (applying && (typeof body.snapshot_digest !== 'string' || !DIGEST.test(body.snapshot_digest)
        || typeof body.receipt !== 'string' || body.receipt.length > 4096)) throw error(422,'invalid_receipt');
    const plan = {schema_version:1,operation_id:body.operation_id,library_id:body.library_id,
      master_key:body.master_key,other_keys:body.other_keys.slice(),identity_evidence_sha256:body.identity_evidence_sha256};
    if(body.formal_metadata!==undefined && body.preprint_metadata!==undefined)throw error(422,'conflicting_metadata_modes');
    const preprint=body.preprint_metadata!==undefined;
    if (body.formal_metadata !== undefined || preprint) {
      const m=preprint?body.preprint_metadata:body.formal_metadata;
      const fields=preprint?['itemType','title','creators','date','DOI','url','repository','archiveID']:['itemType','title','creators','date','DOI','url','publicationTitle','proceedingsTitle','volume','issue','pages','publisher'];
      if(!m || typeof m!=='object' || Array.isArray(m) || Object.keys(m).some(k=>!fields.includes(k)))throw error(422,'invalid_formal_metadata');
      if(!(preprint?m.itemType==='preprint':['conferencePaper','journalArticle'].includes(m.itemType)) || !m.title || !/^\d{4}(?:-\d{2}){0,2}$/.test(m.date||'')
          || !(preprint?m.repository==='arXiv':m.itemType==='conferencePaper'?m.proceedingsTitle:m.publicationTitle))throw error(422,'incomplete_formal_metadata');
      if(Object.entries(m).some(([k,v])=>k!=='creators'&&(typeof v!=='string'||v.length>4000)))throw error(422,'invalid_formal_metadata');
      if(preprint){
        if(!/^\d{4}\.\d{4,5}$/.test(m.archiveID||'') || m.url!=='https://arxiv.org/abs/'+m.archiveID
           || (m.DOI && doi(m.DOI)!=='10.48550/arxiv.'+m.archiveID))throw error(422,'invalid_preprint_identity');
      }else if(!/^https?:\/\//i.test(m.url||'') || /^https?:\/\/(?:[^/]*\.)?arxiv\.org(?:\/|$)/i.test(m.url))throw error(422,'formal_source_required');
      if(!Array.isArray(m.creators)||!m.creators.length||m.creators.length>100||m.creators.some(c=>
          !c||typeof c!=='object'||Array.isArray(c)||Object.keys(c).some(k=>!['creatorType','firstName','lastName','name'].includes(k))
          ||c.creatorType!=='author'||!(c.lastName||c.name)||Object.values(c).some(v=>typeof v!=='string'||v.length>1000)))throw error(422,'invalid_creators');
      plan[preprint?'preprint_metadata':'formal_metadata']=JSON.parse(JSON.stringify(m));
    }
    return plan;
  }
  function publicationTitle(s) { return title(String(s||'').replace(/\s*[（(][^()（）]*\b(?:19|20)\d{2}[^()（）]*[)）]\s*$/u,'')); }
  function title(s) { return String(s || '').normalize('NFKC').toLowerCase().replace(/[\s\p{P}\p{S}]/gu,''); }
  function doi(s) { return String(s || '').toLowerCase().trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//,'').replace(/[.,;]+$/,''); }
  function keys(plan) { return [plan.master_key,...plan.other_keys]; }
  function digest(rows) { return security.digestCanonical(rows.slice().sort((a,b)=>a.key.localeCompare(b.key))); }
  function checkIdentity(plan, rows) {
    const parents = keys(plan).map(k=>rows.find(r=>r.key===k));
    if (parents.some(p=>!p || p.deleted || p.parentItem || !['conferencePaper','journalArticle','preprint'].includes(p.itemType))) throw error(409,'parent_unavailable');
    const first=parents[0];
    if(plan.formal_metadata || plan.preprint_metadata){
      const m=plan.formal_metadata || plan.preprint_metadata;
      if(!publicationTitle(m.title)||parents.some(p=>publicationTitle(p.title)!==publicationTitle(m.title)))throw error(409,'identity_conflict');
      if(parents.some(p=>doi(p.DOI)&&doi(p.DOI)!==doi(m.DOI)))throw error(409,'identity_conflict');
      return;
    }
    if (!title(first.title) || parents.some(p=>p.itemType!==first.itemType || title(p.title)!==title(first.title))) throw error(409,'identity_conflict');
    const dois=new Set(parents.map(p=>doi(p.DOI)).filter(Boolean));
    if (dois.size>1) throw error(409,'identity_conflict');
  }
  async function preflight(body) {
    const plan=validate(body), rows=await runtime.snapshot(keys(plan));
    checkIdentity(plan,rows);
    const snapshot_digest=digest(rows), plan_digest=security.digestCanonical(plan);
    const receipt=security.signReceipt({schema_version:1,operation_id:'merge:'+plan.operation_id,
      plan_digest,snapshot_digest,expiry:Math.floor(Date.now()/1000)+300});
    return {master_key:plan.master_key,other_keys:plan.other_keys,snapshot_digest,plan_digest,receipt,items:rows};
  }
  function checkPreserved(plan,before,after) {
    const byKey=new Map(after.map(r=>[r.key,r])), master=byKey.get(plan.master_key);
    if (!master || master.deleted || plan.other_keys.some(k=>!byKey.get(k)?.deleted)) throw error(500,'parent_readback_mismatch');
    const tags=new Set((master.tags||[]).map(t=>t.tag)),collections=new Set(master.collections||[]);
    for (const old of before) {
      const now=byKey.get(old.key);
      if (!now) throw error(500,'missing_item_readback');
      if (keys(plan).includes(old.key)) {
        if ((old.tags||[]).some(t=>!tags.has(t.tag)) || (old.collections||[]).some(c=>!collections.has(c))) throw error(500,'membership_readback_mismatch');
        continue;
      }
      if (Boolean(old.deleted)!==Boolean(now.deleted)) throw error(500,'child_deleted');
      const expectedParent=keys(plan).includes(old.parentItem)?plan.master_key:old.parentItem;
      if (now.parentItem!==expectedParent) throw error(500,'child_parent_mismatch');
      if (old.itemType==='attachment' || old.itemType==='annotation') {
        // Native save may change bookkeeping; all payload fields and keys must survive.
        const payload = r => Object.fromEntries(Object.entries(r).filter(([k])=>!['parentItem','version','dateModified','dateAdded'].includes(k)));
        if (security.digestCanonical(payload(old))!==security.digestCanonical(payload(now))) throw error(500,'child_content_changed');
      }
    }
  }
  async function apply(body) {
    const plan=validate(body,true);
    let receipt;
    try { receipt=security.receiptPayloadFromReceipt(body.receipt); } catch (_) {throw error(409,'invalid_receipt');}
    if (receipt.operation_id!=='merge:'+plan.operation_id || receipt.plan_digest!==security.digestCanonical(plan)
        || receipt.snapshot_digest!==body.snapshot_digest || !security.verifyReceipt(body.receipt,receipt)) throw error(409,'invalid_receipt');
    return runtime.transaction(async()=>{
      const before=await runtime.snapshot(keys(plan));
      if(digest(before)!==body.snapshot_digest) throw error(409,'snapshot_changed');
      checkIdentity(plan,before);
      await runtime.mergePreservingAttachments(plan.master_key,plan.other_keys);
      const metadata=plan.formal_metadata || plan.preprint_metadata;
      if(metadata)await runtime.updateMetadata(plan.master_key,metadata);
      const after=await runtime.snapshot(keys(plan));
      checkPreserved(plan,before,after);
      if(metadata){
        const master=after.find(r=>r.key===plan.master_key);
        for(const [field,value] of Object.entries(metadata))
          if(master[field]===undefined||security.digestCanonical(master[field])!==security.digestCanonical(value))throw error(500,'metadata_readback_mismatch');
      }
      return {master_key:plan.master_key,merged_keys:plan.other_keys,attachment_keys:after.filter(r=>r.itemType==='attachment').map(r=>r.key),items:after,snapshot_digest:digest(after)};
    });
  }
  function registerEndpoints(target) {
    if(server) throw error(500,'already_registered');
    for(const mode of ['preflight','apply']) if(target.Endpoints[BASE+mode]) throw error(500,'endpoint_collision');
    for(const mode of ['preflight','apply']) {
      endpoints[mode]=class {
        constructor(){this.supportedMethods=['POST'];this.supportedDataTypes=['application/json'];this.allowRequestsFromUnsafeWebContent=false;}
        async init(request){
          try {security.validateAuthenticatedJSONRequest(request,BASE+mode);
            return [200,'application/json',JSON.stringify(await (mode==='preflight'?preflight:apply)(request.data))];
          }catch(e){return [e.status||500,'application/json',JSON.stringify({error:{code:e.code||'internal_error',message:e.status?e.message:'internal merge error'}})];}
        }
      };
      target.Endpoints[BASE+mode]=endpoints[mode];
    }
    server=target;
  }
  function shutdown(){if(server)for(const mode of ['preflight','apply'])if(server.Endpoints[BASE+mode]===endpoints[mode])delete server.Endpoints[BASE+mode];server=null;runtime=null;security=null;}
  function init(s) {
    const libraryID=Zotero.Libraries.userLibraryID;
    const get=k=>Zotero.Items.getByLibraryAndKey(libraryID,k);
    let restoreTypeOnFailure=null;
    configure(s,{
      userLibraryID:libraryID,
      async snapshot(parentKeys){
        const found=new Map();
        async function add(item){
          if(!item || found.has(item.key))return;
          if(item.libraryID!==libraryID || !item.isEditable())throw error(409,'item_not_editable');
          await item.loadAllData();
          found.set(item.key,item.toJSON());
          if(item.isRegularItem())for(const id of [...item.getAttachments(true),...item.getNotes(true)])await add(await Zotero.Items.getAsync(id));
          if(item.isPDFAttachment())for(const a of item.getAnnotations(true))await add(a);
        }
        for(const key of parentKeys)await add(get(key));
        return [...found.values()];
      },
      transaction:callback=>Zotero.DB.executeTransaction(async()=>{
        restoreTypeOnFailure=null;
        try{return await callback();}
        catch(e){
          // Zotero reloads primary data after DB rollback, but rejects a cached
          // item whose type differs. Restore the cached type before native rollback.
          if(restoreTypeOnFailure)restoreTypeOnFailure();
          throw e;
        }finally{restoreTypeOnFailure=null;}
      }),
      async updateMetadata(key,fields){
        Zotero.DB.requireTransaction();
        const item=get(key),typeID=Zotero.ItemTypes.getID(fields.itemType);
        if(!typeID)throw error(422,'invalid_item_type');
        const oldTypeID=item.itemTypeID;
        restoreTypeOnFailure=()=>item.setType(oldTypeID);
        item.setType(typeID);
        for(const [field,value] of Object.entries(fields)){
          if(field==='itemType'||field==='creators')continue;
          const fieldID=Zotero.ItemFields.getID(field);
          if(!fieldID||!Zotero.ItemFields.isValidForType(fieldID,typeID))throw error(422,'field_not_supported_for_type');
          item.setField(field,value);
        }
        item.setCreators(fields.creators.map(c=>{
          const creator={...c,creatorTypeID:Zotero.CreatorTypes.getID(c.creatorType)};
          delete creator.creatorType;
          return creator;
        }));
        await item.save({skipSelect:true});
      },
      async mergePreservingAttachments(masterKey,otherKeys){
        Zotero.DB.requireTransaction();
        const master=get(masterKey),others=otherKeys.map(get);
        for(const parent of others)for(const id of parent.getAttachments(true)){
          const attachment=await Zotero.Items.getAsync(id);
          attachment.parentID=master.id;
          await attachment.save({skipSelect:true});
        }
        // Zotero 9 mergeItems() owns a transaction and cannot be nested. Keep its
        // parent-merge semantics here using native item/relation APIs only.
        // Reference: Zotero 9.0.6 mergeItems.mjs (Zotero contributors, AGPL-3.0-or-later).
        const replaced=Zotero.Relations.replacedItemPredicate;
        const targetURI=Zotero.URI.getItemURI(master);
        let earliest=master.dateAdded;
        for(const other of others){
          if(other.dateAdded<earliest)earliest=other.dateAdded;
          for(const id of other.getNotes(true)){
            const note=await Zotero.Items.getAsync(id);
            note.parentID=master.id;
            Zotero.Notes.replaceItemKey(note,other.key,master.key);
            await note.save({skipSelect:true});
          }
          for(const id of other.getCollections())master.addToCollection(id);
          for(const tag of other.getTags()){
            if(!master.hasTag(tag.tag) || master.getTagType(tag.tag)!==0)master.addTag(tag.tag,tag.type);
          }
          const oldURI=Zotero.URI.getItemURI(other);
          for(const [predicate,values] of Object.entries(other.getRelations())){
            for(const value of values)if(value!==targetURI)master.addRelation(predicate,value);
          }
          for(const value of other.getRelationsByPredicate(replaced))other.removeRelation(replaced,value);
          for(const relation of await Zotero.Relations.getByObject('item',oldURI)){
            if(relation.predicate===replaced || relation.subject.libraryID!==libraryID || relation.subject.id===master.id)continue;
            relation.subject.removeRelation(relation.predicate,oldURI);
            relation.subject.addRelation(relation.predicate,targetURI);
            await relation.subject.save({skipSelect:true});
          }
          master.addRelation(replaced,oldURI);
          other.deleted=true;
          await other.save({skipSelect:true});
        }
        master.setField('dateAdded',earliest);
        await master.save({skipSelect:true});
      },
    });
    registerEndpoints(Zotero.Server);
  }
  return {configure,preflight,apply,registerEndpoints,init,shutdown};
})();
