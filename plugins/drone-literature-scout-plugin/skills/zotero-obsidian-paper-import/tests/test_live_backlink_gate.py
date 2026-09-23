import sys
import unittest
import tempfile
import hashlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import paper_import as p
import run_pipeline as pipeline


class LiveBacklinkTests(unittest.TestCase):
    def test_reuse_selects_matching_bytes_and_preserves_valid_existing_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {'itemType': 'conferencePaper', 'title': 'Paper', 'date': '2024',
                   'creators': [{'lastName': 'Author', 'creatorType': 'author'}],
                   'proceedingsTitle': 'Conference', 'url': 'https://publisher.example/paper'}
            items = [{'key': 'PARENT01', 'data': row}]
            for key, content in [('OLDPDF01', b'x'), ('GOODPDF1', b'y'), ('GOODPDF2', b'y')]:
                path = root / key / 'paper.pdf'
                path.parent.mkdir()
                path.write_bytes(b'%PDF-' + content * 300)
                items.append({'key': key, 'data': {'parentItem': 'PARENT01',
                    'contentType': 'application/pdf', 'linkMode': 'imported_file'},
                    'links': {'enclosure': {'href': path.as_uri()}}})
            good = root / 'GOODPDF1' / 'paper.pdf'
            paper = {'number': 1, 'title': 'Paper', 'parent_key': 'PARENT01',
                'publication_verification': {'publication': dict(row), 'source_url': row['url'],
                    'reviewed_at': '2026-09-21', 'identity_basis': 'Official identity verified',
                    'pdf': {'path': str(good), 'sha256': hashlib.sha256(good.read_bytes()).hexdigest(),
                            'source_url': 'https://publisher.example/paper.pdf', 'version': 'version_of_record'}}}
            self.assertEqual(p.verified_existing_attachment(paper, items), 'GOODPDF1')
            paper['attachment_key'] = 'GOODPDF2'
            self.assertEqual(p.verified_existing_attachment(paper, items), 'GOODPDF2')
            paper['attachment_key'] = 'OLDPDF01'
            with self.assertRaises(ValueError):
                p.verified_existing_attachment(paper, items)

    def test_reuse_without_verified_pdf_does_not_choose_first_attachment(self):
        parent = {'key': 'PARENT01', 'data': {'itemType': 'conferencePaper', 'title': 'Paper'}}
        pdf = {'key': 'OLDPDF01', 'data': {'parentItem': 'PARENT01', 'contentType': 'application/pdf'}}
        with patch.object(pipeline, 'read_zotero_items', return_value=[parent, pdf]), \
             patch.object(pipeline, 'fetch_json', return_value=[pdf]):
            row = pipeline.import_records([{'number': 1, 'title': 'Paper'}], False)[0]
        self.assertFalse(row.get('attachment_key'))
        self.assertEqual(row['status'], 'manual_review')

    def test_backfill_stale_manifest_cannot_modify_note(self):
        records = [{'number': 1, 'title': 'Paper', 'status': 'imported_pdf',
                    'parent_key': 'OLDPAREN', 'attachment_key': 'OLDPDF01'}]
        with patch.object(p, 'load_json', return_value=records), \
             patch.object(p, 'read_zotero_items', return_value=[]), \
             patch.object(p, 'update_obsidian_file', side_effect=AssertionError('Stale link written')):
            with self.assertRaises(ValueError):
                p.main(['backfill', '--manifest', 'unused.json', '--obsidian', 'unused.md'])


if __name__ == '__main__':
    unittest.main()
