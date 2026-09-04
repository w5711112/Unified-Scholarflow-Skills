"""Contract tests for author-research JSON validation.

Each negative case names a validator branch whose absence would wrongly accept
an evidence record that the research workflow must reject.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from scripts.validate_author_research import validate_document  # noqa: E402
from test_support import writable_test_directory  # noqa: E402


def verified(value: str) -> dict[str, object]:
    return {
        "status": "verified",
        "value": value,
        "sources": ["https://public.example/evidence"],
    }


def valid_document() -> dict[str, object]:
    roles = ["first_author", "corresponding_author"]
    return {
        "paper_id": "doi:10.1000/example",
        "verified_at": "2026-07-24",
        "designated_authors": [{"name": "Ada Example", "roles": roles}],
        "authors": [
            {
                "name": "Ada Example",
                "roles": roles,
                "education": verified("PhD in Robotics"),
                "current_position": verified("Associate Professor"),
                "qs_ranking": {
                    **verified("12"),
                    "edition": "QS World University Rankings 2026",
                },
                "scholar": {**verified("1234 citations"), "as_of": "2026-07-24"},
                "memberships": {
                    "status": "not_publicly_verified",
                    "searched_sources": ["https://public.example/profile"],
                },
                "standing_assessment": {
                    "status": "inference",
                    "value": "established researcher",
                    "basis": "Publication and citation record",
                },
            }
        ],
    }


def cli_temporary_directory():
    return writable_test_directory()


class AuthorResearchContractTests(unittest.TestCase):
    def assert_invalid(self, document: dict[str, object], fragment: str) -> None:
        errors = validate_document(document)
        self.assertTrue(errors, "invalid evidence document was accepted")
        self.assertTrue(
            any(fragment in error for error in errors),
            f"expected an error mentioning {fragment!r}, got {errors!r}",
        )

    def test_accepts_complete_evidenced_document(self) -> None:
        self.assertEqual(validate_document(valid_document()), [])

    def test_rejects_designated_author_missing_from_authors(self) -> None:
        document = valid_document()
        document["authors"] = []
        self.assert_invalid(document, "authors")

    def test_rejects_designated_author_role_mismatch(self) -> None:
        document = valid_document()
        document["authors"][0]["roles"] = ["first_author"]
        self.assert_invalid(document, "roles")

    def test_rejects_duplicate_name_in_designated_authors_even_when_roles_are_split(self) -> None:
        document = valid_document()
        document["designated_authors"] = [
            {"name": "Ada Example", "roles": ["first_author"]},
            {"name": "Ada Example", "roles": ["corresponding_author"]},
        ]
        self.assert_invalid(document, "duplicate")

    def test_rejects_duplicate_name_in_authors_even_when_roles_are_split(self) -> None:
        document = valid_document()
        first_entry = document["authors"][0]
        second_entry = {
            **first_entry,
            "roles": ["corresponding_author"],
        }
        first_entry["roles"] = ["first_author"]
        document["authors"] = [first_entry, second_entry]
        self.assert_invalid(document, "duplicate")

    def test_rejects_trim_equivalent_duplicate_name_in_designated_authors(self) -> None:
        document = valid_document()
        document["designated_authors"] = [
            {"name": "Ada Example", "roles": ["first_author"]},
            {"name": " Ada Example ", "roles": ["corresponding_author"]},
        ]
        self.assert_invalid(document, "duplicate")

    def test_rejects_trim_equivalent_duplicate_name_in_authors(self) -> None:
        document = valid_document()
        first_entry = document["authors"][0]
        second_entry = {
            **first_entry,
            "name": " Ada Example ",
            "roles": ["corresponding_author"],
        }
        first_entry["roles"] = ["first_author"]
        document["authors"] = [first_entry, second_entry]
        self.assert_invalid(document, "duplicate")

    def test_rejects_invalid_top_level_verified_at(self) -> None:
        for invalid_value in (" ", 0, "not-a-date"):
            with self.subTest(verified_at=invalid_value):
                document = valid_document()
                document["verified_at"] = invalid_value
                self.assert_invalid(document, "verified_at")

    def test_rejects_non_iso_datetime_separator_in_verified_at(self) -> None:
        for invalid_value in ("2026-07-24x12:00:00", "2026-07-24_12:00:00"):
            with self.subTest(verified_at=invalid_value):
                document = valid_document()
                document["verified_at"] = invalid_value
                self.assert_invalid(document, "verified_at")

    def test_rejects_verified_positive_fact_without_public_url(self) -> None:
        document = valid_document()
        document["authors"][0]["education"] = {
            "status": "verified",
            "value": "PhD in Robotics",
            "sources": ["not-a-url"],
        }
        self.assert_invalid(document, "education")

    def test_rejects_verified_positive_fact_with_malformed_url_host(self) -> None:
        document = valid_document()
        document["authors"][0]["education"]["sources"] = ["https:// "]
        self.assert_invalid(document, "education")

    def test_rejects_malformed_or_non_public_verified_url(self) -> None:
        invalid_urls = (
            "https://example.com:",
            "https://example.com\\@evil.com/evidence",
            "https://127.0.0.1/evidence",
            "https://[::1]/evidence",
            "https://10.0.0.1/evidence",
            "https://localhost/evidence",
            "https://example.com/\x00",
        )
        for invalid_url in invalid_urls:
            with self.subTest(url=invalid_url):
                document = valid_document()
                document["authors"][0]["education"]["sources"] = [invalid_url]
                self.assert_invalid(document, "education")

    def test_rejects_verified_value_that_is_not_a_nonblank_string(self) -> None:
        for invalid_value in (" ", 0):
            with self.subTest(value=invalid_value):
                document = valid_document()
                document["authors"][0]["education"]["value"] = invalid_value
                self.assert_invalid(document, "education")

    def test_rejects_verified_scholar_without_as_of_date(self) -> None:
        document = valid_document()
        del document["authors"][0]["scholar"]["as_of"]
        self.assert_invalid(document, "scholar")

    def test_rejects_invalid_verified_scholar_as_of(self) -> None:
        for invalid_value in (" ", 0, "not-a-date"):
            with self.subTest(as_of=invalid_value):
                document = valid_document()
                document["authors"][0]["scholar"]["as_of"] = invalid_value
                self.assert_invalid(document, "scholar")

    def test_rejects_non_iso_datetime_separator_in_verified_scholar_as_of(self) -> None:
        for invalid_value in ("2026-07-24x12:00:00", "2026-07-24_12:00:00"):
            with self.subTest(as_of=invalid_value):
                document = valid_document()
                document["authors"][0]["scholar"]["as_of"] = invalid_value
                self.assert_invalid(document, "scholar")

    def test_rejects_verified_qs_ranking_without_edition(self) -> None:
        document = valid_document()
        del document["authors"][0]["qs_ranking"]["edition"]
        self.assert_invalid(document, "qs_ranking")

    def test_rejects_verified_qs_ranking_with_non_string_or_blank_edition(self) -> None:
        for invalid_value in (" ", 0):
            with self.subTest(edition=invalid_value):
                document = valid_document()
                document["authors"][0]["qs_ranking"]["edition"] = invalid_value
                self.assert_invalid(document, "qs_ranking")

    def test_rejects_unknown_fact_written_as_zero(self) -> None:
        document = valid_document()
        document["authors"][0]["memberships"] = {
            "status": "not_publicly_verified",
            "value": 0,
            "searched_sources": ["https://public.example/profile"],
        }
        self.assert_invalid(document, "memberships")

    def test_rejects_standing_assessment_claimed_as_verified(self) -> None:
        document = valid_document()
        document["authors"][0]["standing_assessment"] = verified("field leader")
        self.assert_invalid(document, "standing_assessment")

    def test_rejects_standing_basis_that_is_not_a_nonblank_string(self) -> None:
        for invalid_value in (" ", 0):
            with self.subTest(basis=invalid_value):
                document = valid_document()
                document["authors"][0]["standing_assessment"]["basis"] = invalid_value
                self.assert_invalid(document, "standing_assessment")

    def test_cli_emits_json_report_for_valid_document(self) -> None:
        with cli_temporary_directory() as temporary_directory:
            json_path = Path(temporary_directory) / "author-research.json"
            json_path.write_text(json.dumps(valid_document()), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SKILL_ROOT / "scripts" / "validate_author_research.py"), str(json_path)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"valid": True, "errors": []})

    def test_cli_reports_contract_failure_as_json(self) -> None:
        with cli_temporary_directory() as temporary_directory:
            json_path = Path(temporary_directory) / "author-research.json"
            document = valid_document()
            document["verified_at"] = "not-a-date"
            json_path.write_text(json.dumps(document), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SKILL_ROOT / "scripts" / "validate_author_research.py"), str(json_path)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["valid"])
        self.assertTrue(any("verified_at" in error for error in report["errors"]))

    def test_cli_reports_invalid_utf8_without_traceback(self) -> None:
        with cli_temporary_directory() as temporary_directory:
            json_path = Path(temporary_directory) / "invalid-utf8.json"
            json_path.write_bytes(b"\xff")
            result = subprocess.run(
                [sys.executable, str(SKILL_ROOT / "scripts" / "validate_author_research.py"), str(json_path)],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unable to read JSON evidence record", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_temporary_directory_is_outside_source_tree(self) -> None:
        with cli_temporary_directory() as temporary_directory:
            self.assertFalse(
                Path(temporary_directory).resolve().is_relative_to(SKILL_ROOT.resolve()),
                "CLI test fixtures must not require a writable source tree",
            )


if __name__ == "__main__":
    unittest.main()
