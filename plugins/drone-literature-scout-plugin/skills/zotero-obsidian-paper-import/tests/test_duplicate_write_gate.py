"""Regression cases for missing-DOI imports and the final Connector boundary."""
import sys
import unittest
import tempfile
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import paper_import as p
import run_pipeline as pipeline
import merge_duplicates as merge
import safe_download


def parent(key, title='Paper', doi='', number=82):
    return {'key': key, 'data': {'itemType': 'conferencePaper', 'title': title,
        'DOI': doi, 'tags': [{'tag': f'obsidian-paper-{number}'}]}}


class DuplicateBoundaryTests(unittest.TestCase):
    def test_both_download_entrypoints_prefer_formal_and_exclude_arxiv(self):
        paper={'source_url':'https://arxiv.org/abs/1707.01495',
               'formal_pdf_url':'https://proceedings.example.org/paper.pdf'}
        self.assertEqual(safe_download.candidate_urls(paper),['https://proceedings.example.org/paper.pdf'])

    def test_formal_page_is_used_in_connector_payload(self):
        paper={'number':82,'title':'Paper','source_url':'https://arxiv.org/abs/1234',
               'formal_source_url':'https://proceedings.example.org/paper'}
        self.assertEqual(p.build_connector_payload(paper,'s','i')['items'][0]['url'],paper['formal_source_url'])

    def test_crossref_publication_date_survives_enrichment(self):
        row=p.crossref_item_to_candidate({'title':['Paper'],'published':{'date-parts':[[2024,5,3]]}})
        self.assertEqual(row.get('date'),'2024-05-03')

    def test_valid_create_is_sent_once_and_reconciled(self):
        payload=p.build_connector_payload({'number':82,'title':'Paper','date':'2024','itemType':'conferencePaper',
            'authors':[{'lastName':'Tester','creatorType':'author'}],
            'proceedingsTitle':'Conference','formal_source_url':'https://proceedings.example.org/paper'},'s','i')
        calls=[]
        with tempfile.TemporaryDirectory() as tmp:
            pdf=Path(tmp)/'verified.pdf'
            pdf.write_bytes(b'%PDF-'+b'x'*300)
            row=payload['items'][0]
            payload['_publication_verification']={'publication':dict(row),'source_url':row['url'],
                'reviewed_at':'2026-09-21','identity_basis':'Official publication and exact PDF checked',
                'pdf':{'path':str(pdf),'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),
                       'source_url':'https://proceedings.example.org/paper.pdf','version':'version_of_record'}}
            with patch.object(p,'read_zotero_items',side_effect=[[],[parent('A')]]), \
                 patch.object(p,'_request_json',side_effect=lambda *a:(calls.append(a) or (201,b'{}'))):
                reconciliation={}
                status,_=p.zotero_connector_save_item(payload,reconciliation=reconciliation)
        self.assertEqual((status,len(calls)),(201,1))
        self.assertNotIn('_publication_verification',calls[0][1])
        self.assertEqual(reconciliation['after'],[parent('A')])
        self.assertEqual(reconciliation['decision']['status'],'unique_parent')

    def test_doi_free_duplicate_is_in_library_audit(self):
        groups = p.group_duplicate_parents([parent('A'), parent('B')])
        self.assertTrue(any(set(keys) == {'A', 'B'} for keys in groups.values()))

    def test_same_number_with_changed_title_blocks_creation(self):
        self.assertEqual(p.find_existing_parent_keys([parent('A', 'Old title')],
            {'number': 82, 'title': 'New title'}), ['A'])

    def test_ambiguous_find_existing_never_picks_first(self):
        with self.assertRaises(ValueError):
            p.find_existing([parent('A'), parent('B')], {'title': 'Paper'})

    def test_matching_conflicting_doi_is_not_silently_reused(self):
        existing = parent('A', doi='10.1234/first')
        with patch.object(pipeline, 'read_zotero_items', return_value=[existing]), \
             patch.object(pipeline, 'fetch_json', return_value=[]):
            row = pipeline.import_records([{'number': 82, 'title': 'Paper',
                                           'doi': '10.1234/second'}], False)[0]
        self.assertEqual(row['status'], 'metadata_conflict')

    def test_final_write_boundary_rechecks_existing_title(self):
        payload = p.build_connector_payload({'number':82, 'title':'Paper'}, 's', 'i')
        sent = []
        with patch.object(p, 'read_zotero_items', return_value=[parent('A')]), \
             patch.object(p, '_request_json', side_effect=lambda *a: (sent.append(a) or (201,b'{}'))):
            status, _ = p.zotero_connector_save_item(payload)
        self.assertEqual((status, len(sent)), (409, 0))

    def test_missing_metadata_never_reaches_connector(self):
        payload = p.build_connector_payload({'number':82, 'title':'Paper'}, 's', 'i')
        sent = []
        with patch.object(p, 'read_zotero_items', return_value=[]), \
             patch.object(p, '_request_json', side_effect=lambda *a: (sent.append(a) or (201,b'{}'))):
            status, _ = p.zotero_connector_save_item(payload)
        self.assertEqual((status, len(sent)), (422, 0))

    def test_arxiv_is_not_an_automatic_formal_pdf_candidate(self):
        self.assertEqual(pipeline.pdf_candidates({'source_url':'https://arxiv.org/abs/1707.01495'}), [])

    def test_formal_pdf_precedes_original_preprint_url(self):
        paper = {'source_url':'https://arxiv.org/pdf/1707.01495.pdf',
                 'formal_pdf_url':'https://proceedings.example.org/paper.pdf'}
        self.assertEqual(pipeline.pdf_candidates(paper),
                         ['https://proceedings.example.org/paper.pdf'])

    def test_local_metadata_update_fails_closed_without_http(self):
        sent = []
        response = MagicMock()
        response.__enter__.return_value.status = 204
        response.__enter__.return_value.read.return_value = b''
        with patch.object(merge.urllib.request, 'urlopen',
                          side_effect=lambda *a, **kw: (sent.append(a) or response)):
            status, _ = merge.put_item('A', {}, 1)
        self.assertEqual((status, len(sent)), (501, 0))

    def test_note_and_annotation_are_not_duplicate_parents(self):
        note = parent('NOTE', doi='10.1234/x'); note['data']['itemType'] = 'note'
        article = parent('PAPER', doi='10.1234/x')
        self.assertEqual(p.group_duplicate_parents([note, article]), {})


if __name__ == '__main__':
    unittest.main()
