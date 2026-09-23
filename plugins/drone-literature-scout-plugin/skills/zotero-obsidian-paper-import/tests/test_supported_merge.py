import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
import inspect
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import merge_duplicates as m

def parent(k):return {'key':k,'data':{'key':k,'itemType':'conferencePaper','title':'Paper','tags':[]}}

class SupportedMergeTests(unittest.TestCase):
 def test_native_bridge_preserves_children_and_never_uses_local_put_delete(self):
  self.check_metadata_mode('formal_metadata')

 def test_preprint_correction_uses_separate_explicit_metadata_mode(self):
  self.check_metadata_mode('preprint_metadata')

 def check_metadata_mode(self, mode):
  self.assertIn('client',inspect.signature(m.merge_one).parameters,'native bridge path missing')
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory); evidence=root/'identity.json'
   evidence.write_text(json.dumps({'decision':'same_publication','parent_keys':['MASTER01','OTHER001'],'title':'Paper','source_url':'https://example.org/proceedings/paper',mode:{'title':'Paper','date':'2024'}}))
   plan={'title':'Paper','doi':'','keep_parent_key':'MASTER01','metadata_source_key':'MASTER01','remove_parent_keys':['OTHER001'],
    'identity_evidence_file':str(evidence),'identity_evidence_sha256':hashlib.sha256(evidence.read_bytes()).hexdigest(),'library_id':1}
   before=[parent('MASTER01'),parent('OTHER001'),{'key':'PDF00001','data':{'parentItem':'OTHER001','itemType':'attachment','contentType':'application/pdf'}}]
   after=[parent('MASTER01'),{'key':'PDF00001','data':{'parentItem':'MASTER01','itemType':'attachment','contentType':'application/pdf'}}]
   class Client:
    def _send(self,method,path,body):
     self_test.assertEqual(method,'POST')
     self_test.assertEqual(body.get(mode),{'title':'Paper','date':'2024'})
     if path.endswith('/preflight'):return {'receipt':'fixture','snapshot_digest':'a'*64,'items':[]}
     self_test.assertTrue((root/'journal.json').exists(),'write-ahead evidence missing')
     self_test.assertEqual(body['master_key'],'MASTER01')
     return {'master_key':'MASTER01','merged_keys':['OTHER001']}
   self_test=self
   with patch.object(m,'read_zotero_items',side_effect=[before,after]),patch.object(m,'put_item',side_effect=AssertionError('PUT forbidden')),patch.object(m,'zotero_delete_item',side_effect=AssertionError('DELETE forbidden')):
    result=m.merge_one(plan,True,client=Client(),journal_path=root/'journal.json')
   self.assertEqual(result['status'],'merged_verified')
   self.assertEqual(result['post_merge_pdf_keys'],['PDF00001'])

 def test_missing_identity_evidence_blocks_bridge(self):
  with patch.object(m,'read_zotero_items',side_effect=AssertionError('identity must be checked before library access')):
   result=m.merge_one({'doi':'','title':'Paper','keep_parent_key':'MASTER01','metadata_source_key':'MASTER01','remove_parent_keys':['OTHER001']},True)
  self.assertEqual(result['status'],'manual_review')
  self.assertIn('identity',result['reason'])
