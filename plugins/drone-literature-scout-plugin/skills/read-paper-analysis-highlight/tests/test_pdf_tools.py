import io
import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
from annotate_pdf import annotate_pdf, main  # noqa: E402
from verify_annotation_manifest import verify_manifest  # noqa: E402


FIXTURE_ROOT = Path(__file__).parents[4] / "运行数据" / "read-paper-analysis-highlight-test-fixtures"


class PdfToolTests(unittest.TestCase):
    def setUp(self):
        self.case = FIXTURE_ROOT / self._testMethodName
        self.case.mkdir(parents=True, exist_ok=True)
        for child in self.case.iterdir():
            if child.is_file():
                child.unlink()

    def tearDown(self):
        shutil.rmtree(self.case, ignore_errors=True)

    def _make_pdf(self) -> Path:
        source = self.case / "paper.pdf"
        doc = fitz.open()
        page = doc.new_page(width=300, height=300)
        page.insert_text((30, 30), "Evidence text")
        page.insert_text((30, 60), "The controller converts policy actions into attitude references", fontsize=8)
        page.insert_text((30, 90), "The controller converts policy actions into attitude references", fontsize=8)
        page.insert_text(
            (30, 120),
            "The policy processes depth observations and produces attitude references.",
            fontsize=8,
        )
        page.insert_text((30, 150), "Ada Lovelace", fontsize=8)
        doc.save(source)
        doc.close()
        return source

    def _highlight(self, quote: str, **extra) -> dict:
        item = {
            "id": "fixture-a01",
            "page": 1,
            "annotation_type": "highlight",
            "quote": quote,
            "kind": "method",
            "color": "blue",
            "note_question": "What are the key elements?",
            "claim": "The passage identifies a concrete input, mechanism, output, or measured result.",
            "reason": "The complete selected text remains technically meaningful without adjacent prose.",
            "information_roles": ["method", "mechanism"],
            "evidence": "fixture page 1",
            "confidence": "high",
        }
        item.update(extra)
        return item

    def test_annotation_creates_backup_manifest_and_replaces_requested_pdf(self):
        source = self._make_pdf()
        backup = self.case / "paper.original.pdf"
        manifest = self.case / "manifest.json"
        result = annotate_pdf(
            source,
            source,
            backup,
            manifest,
            [self._highlight(
                "The policy processes depth observations and produces attitude references."
            )],
            overwrite=True,
        )
        self.assertTrue(backup.exists())
        self.assertEqual(result["page_count"], 1)
        self.assertEqual(result["annotation_count"], 1)
        self.assertTrue(verify_manifest(manifest))
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertNotEqual(payload["original_sha256"], payload["annotated_sha256"])
        annotation = payload["annotations"][0]
        self.assertTrue(annotation["quads"])
        self.assertIn("depth observations", annotation["actual_text"])
        self.assertEqual(annotation["match_count"], 1)

    def test_overwrite_requires_explicit_flag(self):
        source = self._make_pdf()
        with self.assertRaises(ValueError):
            annotate_pdf(
                source,
                source,
                self.case / "backup.pdf",
                self.case / "manifest.json",
                [],
                overwrite=False,
            )

    def test_expected_sha256_is_case_insensitive(self):
        source = self._make_pdf()
        backup = self.case / "paper.original.pdf"
        manifest = self.case / "manifest.json"
        actual = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
        annotate_pdf(
            source,
            source,
            backup,
            manifest,
            [],
            overwrite=True,
            expected_sha256=actual.upper(),
        )

    def test_missing_quote_stops_instead_of_guessing_a_rectangle(self):
        source = self._make_pdf()
        with self.assertRaisesRegex(ValueError, "quote"):
            annotate_pdf(
                source,
                self.case / "out.pdf",
                self.case / "backup.pdf",
                self.case / "manifest.json",
                [self._highlight("This sentence does not exist in the PDF.")],
            )

    def test_repeated_quote_requires_occurrence_or_context(self):
        source = self._make_pdf()
        quote = "The controller converts policy actions into attitude references"
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            annotate_pdf(
                source,
                self.case / "out.pdf",
                self.case / "backup.pdf",
                self.case / "manifest.json",
                [self._highlight(quote)],
            )

        result = annotate_pdf(
            source,
            self.case / "out.pdf",
            self.case / "backup.pdf",
            self.case / "manifest.json",
            [self._highlight(quote, occurrence=2)],
        )
        self.assertEqual(result["annotations"][0]["match_count"], 2)

    def test_raw_rectangle_is_rejected_for_text_highlight(self):
        source = self._make_pdf()
        item = self._highlight("Evidence text")
        item["rect"] = [20, 15, 140, 40]
        del item["quote"]
        with self.assertRaisesRegex(ValueError, "quote"):
            annotate_pdf(
                source,
                self.case / "out.pdf",
                self.case / "backup.pdf",
                self.case / "manifest.json",
                [item],
            )

    def test_area_annotation_requires_labeled_visual_evidence(self):
        source = self._make_pdf()
        area = {
            "id": "fixture-area",
            "page": 1,
            "annotation_type": "area",
            "rect": [20, 140, 200, 220],
            "visual_object": "Figure 1 policy architecture",
            "kind": "method",
            "color": "orange",
            "note_question": "How is the method connected?",
            "claim": "The visual region shows the ordered perception, policy, and control modules.",
            "reason": "The diagram topology is not recoverable from a single extracted text line.",
            "information_roles": ["method", "mechanism"],
            "evidence": "Figure 1",
            "confidence": "high",
        }
        result = annotate_pdf(
            source,
            self.case / "area.pdf",
            self.case / "area-backup.pdf",
            self.case / "area-manifest.json",
            [area],
        )
        self.assertEqual(result["annotations"][0]["visual_object"], area["visual_object"])

    def test_area_annotation_is_visual_staging_not_native_import(self):
        source = self._make_pdf()
        area = {
            "id": "fixture-area-staging",
            "page": 1,
            "annotation_type": "area",
            "rect": [20, 140, 200, 220],
            "visual_object": "Figure 1 policy architecture",
            "kind": "method",
            "color": "orange",
            "note_question": "How is the method connected?",
            "claim": "The visual region shows the ordered perception, policy, and control modules.",
            "reason": "The diagram topology is not recoverable from a single extracted text line.",
            "information_roles": ["method", "mechanism"],
            "evidence": "Figure 1",
            "confidence": "high",
        }
        result = annotate_pdf(
            source,
            self.case / "area-staging.pdf",
            self.case / "area-staging-backup.pdf",
            self.case / "area-staging-manifest.json",
            [area],
        )
        with fitz.open(result["annotated_pdf"]) as document:
            page = document[0]
            annotation = page.first_annot
            self.assertEqual(annotation.type[1], "Square")


    def test_annotation_comment_is_written_to_pdf_with_claim_fallback(self):
        source = self._make_pdf()
        quoted = "The policy processes depth observations and produces attitude references."
        with_comment = annotate_pdf(
            source,
            self.case / "with-comment.pdf",
            self.case / "with-comment-backup.pdf",
            self.case / "with-comment-manifest.json",
            [self._highlight(quoted, annotation_comment="Reader-facing annotation text.")],
        )
        with fitz.open(with_comment["annotated_pdf"]) as document:
            self.assertEqual(document[0].first_annot.info["content"], "Reader-facing annotation text.")

        fallback = annotate_pdf(
            source,
            self.case / "fallback.pdf",
            self.case / "fallback-backup.pdf",
            self.case / "fallback-manifest.json",
            [self._highlight(quoted)],
        )
        with fitz.open(fallback["annotated_pdf"]) as document:
            self.assertEqual(
                document[0].first_annot.info["content"],
                "The passage identifies a concrete input, mechanism, output, or measured result.",
            )

    def test_author_background_uses_purple_annotation_color(self):
        source = self._make_pdf()
        author = self._highlight(
            "Ada Lovelace",
            selection_mode="author-name",
            kind="author-background",
            color="purple",
            information_roles=["author_context"],
            author_context="First author; expertise establishes the claimed background context.",
            external_evidence="https://example.org/authors/ada-lovelace",
            verified_at="2026-07-24",
            annotation_comment="\u5916\u90e8\u6838\u9a8c\uff0c\u4e0d\u662f\u8bba\u6587\u6b63\u6587\u4e8b\u5b9e\uff1a\u4f5c\u8005\u80cc\u666f\u4ec5\u4f9d\u636e\u8be5\u5916\u90e8\u6765\u6e90\u3002",
        )
        result = annotate_pdf(
            source,
            self.case / "author.pdf",
            self.case / "author-backup.pdf",
            self.case / "author-manifest.json",
            [author],
        )
        with fitz.open(result["annotated_pdf"]) as document:
            color = document[0].first_annot.colors["stroke"]
        self.assertAlmostEqual(color[0], 0.6)
        self.assertAlmostEqual(color[1], 0.3)
        self.assertAlmostEqual(color[2], 0.8)

    def test_cli_output_is_ascii_safe_for_strict_stdout(self):
        annotations_path = self.case / "annotations.json"
        annotations_path.write_text("[]", encoding="utf-8")
        stdout_bytes = io.BytesIO()
        strict_stdout = io.TextIOWrapper(
            stdout_bytes,
            encoding="ascii",
            errors="strict",
        )
        arguments = [
            "annotate_pdf.py",
            "--input",
            str(self.case / "input.pdf"),
            "--output",
            str(self.case / "output.pdf"),
            "--backup",
            str(self.case / "backup.pdf"),
            "--manifest",
            str(self.case / "manifest.json"),
            "--annotations",
            str(annotations_path),
        ]
        result = {"actual_text": "ﬂight controller"}
        with (
            patch.object(sys, "argv", arguments),
            patch("annotate_pdf.annotate_pdf", return_value=result),
            patch.object(sys, "stdout", strict_stdout),
        ):
            self.assertEqual(main(), 0)
            strict_stdout.flush()
        payload = json.loads(stdout_bytes.getvalue().decode("ascii"))
        self.assertEqual(payload, result)

if __name__ == "__main__":
    unittest.main()
