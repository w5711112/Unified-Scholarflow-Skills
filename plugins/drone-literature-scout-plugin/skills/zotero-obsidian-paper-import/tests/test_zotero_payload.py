import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "skill-with-plugin" / "drone-literature-scout-plugin" / "skills" / "zotero-obsidian-paper-import" / "scripts"))

from paper_import import (
    build_connector_payload,
    find_existing_parent_keys,
    group_duplicate_parents,
    classify_post_write_matches,
    zotero_delete_item,
)


class ZoteroPayloadTests(unittest.TestCase):
    def test_local_api_delete_fails_closed_without_http_request(self):
        with patch(
            "paper_import.urllib.request.urlopen",
            side_effect=AssertionError("local API delete is unsupported"),
        ) as urlopen:
            status, body = zotero_delete_item("NEWLY_CREATED")

        self.assertEqual(status, 501)
        self.assertIn(b"manual Zotero UI review", body)
        urlopen.assert_not_called()

    def test_payload_has_metadata_and_stable_connector_id(self):
        paper = {"number": 12, "title": "EGO-Planner", "doi": "10.1109/lra.2020.3047728", "source_url": "https://ieeexplore.ieee.org/document/9309343", "authors": [{"firstName": "Xin", "lastName": "Zhou"}]}
        payload = build_connector_payload(paper, "session-12", "paper-12")
        self.assertEqual(payload["sessionID"], "session-12")
        self.assertEqual(payload["items"][0]["id"], "paper-12")
        self.assertEqual(payload["items"][0]["DOI"], "10.1109/lra.2020.3047728")

    def test_duplicate_groups_include_all_parent_keys_by_normalized_doi(self):
        items = [
            {"key": "PARENT1", "data": {"itemType": "journalArticle", "DOI": "10.1234/ABC"}},
            {"key": "PARENT2", "data": {"itemType": "journalArticle", "DOI": "https://doi.org/10.1234/abc."}},
            {"key": "ATTACH1", "data": {"itemType": "attachment", "DOI": "10.1234/abc"}},
        ]
        self.assertEqual(group_duplicate_parents(items), {"10.1234/abc": ["PARENT1", "PARENT2"]})
    def test_existing_parent_keys_block_doi_and_title_variant_duplicates(self):
        items = [
            {
                "key": "PARENT1",
                "data": {
                    "itemType": "conferencePaper",
                    "title": "Apprenticeship Learning via Inverse Reinforcement Learning",
                    "DOI": "10.1145/1015330.1015430",
                },
            },
            {
                "key": "PARENT2",
                "data": {
                    "itemType": "conferencePaper",
                    "title": "Apprenticeship Learning via Inverse Reinforcement Learning（ICML, 2004）",
                    "DOI": "",
                },
            },
            {
                "key": "ATTACH1",
                "data": {
                    "itemType": "attachment",
                    "parentItem": "PARENT1",
                    "contentType": "application/pdf",
                },
            },
        ]
        paper = {
            "title": "Apprenticeship Learning via Inverse Reinforcement Learning",
            "doi": "10.1145/1015330.1015430",
        }
        self.assertEqual(find_existing_parent_keys(items, paper), ["PARENT1", "PARENT2"])

    def test_post_write_duplicate_identifies_only_new_parent_for_rollback(self):
        before = [
            {
                "key": "EXISTING",
                "data": {
                    "itemType": "journalArticle",
                    "title": "A verified paper",
                    "DOI": "10.1234/verified",
                },
            }
        ]
        after = before + [
            {
                "key": "NEWLY_CREATED",
                "data": {
                    "itemType": "journalArticle",
                    "title": "A verified paper",
                    "DOI": "10.1234/verified",
                },
            }
        ]
        result = classify_post_write_matches(before, after, {"title": "A verified paper", "doi": "10.1234/verified"})
        self.assertEqual(result["status"], "duplicate_merge_required")
        self.assertEqual(result["duplicate_parent_keys"], ["EXISTING", "NEWLY_CREATED"])
        self.assertEqual(result["rollback_parent_key"], "NEWLY_CREATED")

    def test_post_write_duplicate_does_not_guess_rollback_target(self):
        items = [
            {
                "key": "PARENT1",
                "data": {"itemType": "journalArticle", "title": "A verified paper", "DOI": "10.1234/verified"},
            },
            {
                "key": "PARENT2",
                "data": {"itemType": "journalArticle", "title": "A verified paper", "DOI": "10.1234/verified"},
            },
        ]
        result = classify_post_write_matches(items, items, {"title": "A verified paper", "doi": "10.1234/verified"})
        self.assertEqual(result["status"], "duplicate_merge_required")
        self.assertEqual(result["rollback_parent_key"], "")



if __name__ == "__main__":
    unittest.main()

