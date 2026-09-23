"""No Connector creation before a reviewed publication/PDF binding exists."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import paper_import as p


class VerifiedPDFGateTests(unittest.TestCase):
    def test_complete_metadata_without_verified_file_cannot_create(self):
        payload = p.build_connector_payload({'number': 1, 'title': 'Paper', 'date': '2024',
            'itemType': 'conferencePaper', 'authors': [{'lastName': 'Author', 'creatorType': 'author'}],
            'proceedingsTitle': 'Conference', 'formal_source_url': 'https://publisher.example/paper'}, 's', 'i')
        sent = []
        with patch.object(p, 'read_zotero_items', return_value=[]), patch.object(p, '_request_json',
                side_effect=lambda *args: (sent.append(args) or (201, b'{}'))):
            code, _ = p.zotero_connector_save_item(payload)
        self.assertEqual((code, len(sent)), (422, 0))

    def test_verified_file_binding_rejects_changes_and_preprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / 'paper.pdf'
            pdf.write_bytes(b'%PDF-' + b'x' * 300)
            row = {'title': 'Paper', 'date': '2024', 'itemType': 'conferencePaper',
                   'creators': [{'lastName': 'Author', 'creatorType': 'author'}],
                   'proceedingsTitle': 'Conference', 'url': 'https://publisher.example/paper'}
            proof = {'publication': row.copy(), 'source_url': row['url'],
                'reviewed_at': '2026-09-21', 'identity_basis': 'Official page and PDF title, authors, venue and year checked.',
                'pdf': {'path': str(pdf), 'sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
                        'source_url': 'https://publisher.example/paper.pdf', 'version': 'version_of_record'}}
            validator = getattr(p, 'validate_publication_pdf', None)
            self.assertTrue(callable(validator), 'Missing actual publication/PDF binding gate')
            self.assertEqual(validator(row, proof), None)
            changed = dict(row, title='Different paper')
            with self.assertRaises(ValueError):
                validator(changed, proof)
            proof['pdf']['source_url'] = 'https://arxiv.org/pdf/1234'
            with self.assertRaises(ValueError):
                validator(row, proof)
            proof['pdf']['source_url'] = 'https://publisher.example/paper.pdf'
            pdf.write_bytes(b'%PDF-' + b'y' * 300)
            with self.assertRaises(ValueError):
                validator(row, proof)

    def test_attachment_upload_without_verification_never_sends(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / 'paper.pdf'
            pdf.write_bytes(b'%PDF-' + b'x' * 300)
            with patch.object(p.urllib.request, 'urlopen', side_effect=AssertionError('Unverified upload sent')):
                code, _ = p.zotero_connector_upload_attachment('s', 'i', pdf)
            self.assertEqual(code, 422)


if __name__ == '__main__':
    unittest.main()
