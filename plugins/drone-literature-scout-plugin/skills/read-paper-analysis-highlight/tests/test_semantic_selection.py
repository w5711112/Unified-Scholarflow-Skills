from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from semantic_selection import (  # noqa: E402
    SemanticSelectionError,
    information_failures,
    validate_semantic_annotation,
)


def complete_item(quote: str) -> dict:
    return {
        "id": "paper-001-a01",
        "page": 1,
        "annotation_type": "highlight",
        "quote": quote,
        "kind": "method",
        "color": "blue",
        "note_question": "方法为什么这样设计？",
        "claim": "该片段完整说明方法的输入、处理机制或输出。",
        "reason": "脱离上下文后仍能识别研究对象、技术动作及其作用。",
        "information_roles": ["method", "mechanism"],
        "evidence": "Section III",
        "confidence": "high",
    }


class SemanticSelectionTests(unittest.TestCase):
    def test_rejects_low_information_fragments(self):
        fragments = (
            "we propose",
            "formal safety guarantees",
            "mass-normalized collective thrust",
            "Quadratic Program",
            "success rate remains",
            "moving obstacles",
        )
        for fragment in fragments:
            with self.subTest(fragment=fragment):
                failures = information_failures(complete_item(fragment))
                self.assertTrue(failures, fragment)
                with self.assertRaises(SemanticSelectionError):
                    validate_semantic_annotation(complete_item(fragment))

    def test_rejects_context_free_number_for_text_highlight(self):
        item = complete_item("90.61")
        item["information_roles"] = ["metric"]
        with self.assertRaises(SemanticSelectionError):
            validate_semantic_annotation(item)

    def test_accepts_complete_architecture_statement(self):
        quote = (
            "The actor utilizes a heterogeneous neural architecture that processes "
            "a 100 × 60 depth image with a convolutional encoder."
        )
        result = validate_semantic_annotation(complete_item(quote))
        self.assertEqual(result["quote"], quote)

    def test_missing_selection_mode_defaults_to_semantic_span(self):
        item = complete_item(
            "The policy receives the current proprioceptive state and the previous action."
        )
        result = validate_semantic_annotation(item)
        self.assertEqual(result["selection_mode"], "semantic-span")

    def test_accepts_key_term_with_context_and_annotation_comment(self):
        item = complete_item("HOCBF correction")
        item.update(
            {
                "selection_mode": "key-term",
                "context_summary": "The controller applies this correction to keep the trajectory safe.",
                "annotation_comment": "Safety mechanism used by the controller.",
            }
        )
        result = validate_semantic_annotation(item)
        self.assertEqual(result["selection_mode"], "key-term")

    def test_key_term_requires_context_and_annotation_comment(self):
        item = complete_item("HOCBF correction")
        item.update({"selection_mode": "key-term"})
        failures = information_failures(item)
        self.assertIn("key-term requires non-empty context_summary", failures)
        self.assertIn("key-term requires non-empty annotation_comment", failures)

    def test_accepts_short_key_metric_with_complete_context(self):
        item = complete_item("90.61 μs")
        item.update(
            {
                "selection_mode": "key-metric",
                "kind": "experiment",
                "information_roles": ["metric", "condition", "result"],
                "metric_context": "Average HOCBF correction computation time.",
                "condition": "Measured during the reported closed-loop experiments.",
                "annotation_comment": "Runtime result under the stated evaluation condition.",
            }
        )
        result = validate_semantic_annotation(item)
        self.assertEqual(result["quote"], "90.61 μs")

    def test_key_metric_requires_number_context_condition_and_comment(self):
        item = complete_item("HOCBF runtime")
        item.update({"selection_mode": "key-metric", "information_roles": ["metric"]})
        failures = information_failures(item)
        self.assertIn("key-metric quote must contain a number", failures)
        self.assertIn("key-metric requires non-empty metric_context", failures)
        self.assertIn("key-metric requires non-empty condition", failures)
        self.assertIn("key-metric requires non-empty annotation_comment", failures)

    def test_accepts_author_name_with_external_verification(self):
        item = complete_item("Ada Lovelace")
        item.update(
            {
                "selection_mode": "author-name",
                "kind": "author-background",
                "color": "purple",
                "information_roles": ["author_context"],
                "author_context": "First author; expertise establishes the claimed background context.",
                "external_evidence": "https://example.org/authors/ada-lovelace",
                "verified_at": "2026-07-24",
                "annotation_comment": "\u5916\u90e8\u6838\u9a8c\uff0c\u4e0d\u662f\u8bba\u6587\u6b63\u6587\u4e8b\u5b9e\uff1a\u4f5c\u8005\u80cc\u666f\u4ec5\u4f9d\u636e\u8be5\u5916\u90e8\u6765\u6e90\u3002",
            }
        )
        result = validate_semantic_annotation(item)
        self.assertEqual(result["selection_mode"], "author-name")

    def test_author_name_rejects_invalid_external_verification_fields(self):
        item = complete_item("Ada Lovelace")
        item.update(
            {
                "selection_mode": "author-name",
                "kind": "author-background",
                "information_roles": ["author_context"],
                "author_context": "First author; expertise establishes the claimed background context.",
                "external_evidence": "ftp://example.org/authors/ada-lovelace",
                "verified_at": "24-07-2026",
                "annotation_comment": "Author background checked externally.",
            }
        )
        failures = information_failures(item)
        self.assertIn("author-name external_evidence must be a public HTTP(S) URL", failures)
        self.assertIn("author-name verified_at must be an ISO date", failures)
        self.assertIn(
            "author-name annotation_comment must start with '\u5916\u90e8\u6838\u9a8c\uff0c\u4e0d\u662f\u8bba\u6587\u6b63\u6587\u4e8b\u5b9e\uff1a'",
            failures,
        )

    def test_author_name_requires_all_external_verification_fields(self):
        item = complete_item("Ada Lovelace")
        item.update(
            {
                "selection_mode": "author-name",
                "kind": "author-background",
                "information_roles": ["author_context"],
            }
        )
        failures = information_failures(item)
        self.assertIn("author-name requires non-empty author_context", failures)
        self.assertIn("author-name requires non-empty external_evidence", failures)
        self.assertIn("author-name requires non-empty verified_at", failures)
        self.assertIn("author-name requires non-empty annotation_comment", failures)
    def test_mode_specific_text_fields_reject_non_strings_and_blank_text(self):
        key_term = complete_item("HOCBF correction")
        key_term.update(
            {
                "selection_mode": "key-term",
                "context_summary": "Safety correction applied by the controller.",
                "annotation_comment": "Controller safety mechanism.",
            }
        )
        key_metric = complete_item("90.61 μs")
        key_metric.update(
            {
                "selection_mode": "key-metric",
                "information_roles": ["metric", "condition", "result"],
                "metric_context": "Average HOCBF correction computation time.",
                "condition": "Measured during closed-loop evaluation.",
                "annotation_comment": "Runtime under the reported condition.",
            }
        )
        author_name = complete_item("Ada Lovelace")
        author_name.update(
            {
                "selection_mode": "author-name",
                "kind": "author-background",
                "information_roles": ["author_context"],
                "author_context": "First author background.",
                "external_evidence": "https://example.org/authors/ada-lovelace",
                "verified_at": "2026-07-24",
                "annotation_comment": "\u5916\u90e8\u6838\u9a8c\uff0c\u4e0d\u662f\u8bba\u6587\u6b63\u6587\u4e8b\u5b9e\uff1a\u4f5c\u8005\u80cc\u666f\u3002",
            }
        )
        cases = (
            ("key-term", key_term, ("quote", "context_summary", "annotation_comment")),
            (
                "key-metric",
                key_metric,
                ("quote", "metric_context", "condition", "annotation_comment"),
            ),
            (
                "author-name",
                author_name,
                (
                    "quote",
                    "author_context",
                    "external_evidence",
                    "verified_at",
                    "annotation_comment",
                ),
            ),
        )
        for mode, valid_item, fields in cases:
            for field in fields:
                for invalid_value in ([], {}, 0, "   "):
                    with self.subTest(mode=mode, field=field, value=invalid_value):
                        failures = information_failures(
                            {**valid_item, field: invalid_value}
                        )
                        self.assertIn(
                            f"{mode} requires non-empty {field}",
                            failures,
                        )

    def test_semantic_span_text_fields_reject_non_strings_and_blank_text(self):
        valid_item = complete_item(
            "The actor processes a depth image and produces attitude control references."
        )
        for field in ("quote", "claim", "reason"):
            invalid_values = (
                None,
                ["The", "actor", "processes", "depth", "and", "control", "references"],
                {"text": "This object contains enough words to pass the old word counter"},
                0,
                "   ",
            )
            for invalid_value in invalid_values:
                with self.subTest(field=field, value=invalid_value):
                    failures = information_failures(
                        {**valid_item, field: invalid_value}
                    )
                    self.assertTrue(
                        failures,
                        f"semantic-span accepted invalid {field}: {invalid_value!r}",
                    )

    def test_area_rejects_non_semantic_selection_modes(self):
        for selection_mode in ("key-term", "key-metric", "author-name"):
            with self.subTest(selection_mode=selection_mode):
                item = complete_item("")
                item.update(
                    {
                        "annotation_type": "area",
                        "selection_mode": selection_mode,
                        "rect": [40, 40, 280, 120],
                        "visual_object": "Table I metric headers and result rows",
                        "information_roles": ["metric", "comparison", "result"],
                    }
                )
                failures = information_failures(item)
                self.assertIn(
                    "non-semantic selection_mode requires annotation_type=highlight",
                    failures,
                )

    def test_author_name_rejects_urls_without_a_valid_host(self):
        item = complete_item("Ada Lovelace")
        item.update(
            {
                "selection_mode": "author-name",
                "kind": "author-background",
                "information_roles": ["author_context"],
                "author_context": "First author background.",
                "external_evidence": "https://example.org/authors/ada-lovelace",
                "verified_at": "2026-07-24",
                "annotation_comment": "\u5916\u90e8\u6838\u9a8c\uff0c\u4e0d\u662f\u8bba\u6587\u6b63\u6587\u4e8b\u5b9e\uff1a\u4f5c\u8005\u80cc\u666f\u3002",
            }
        )
        for invalid_url in ("https://", "http://", "https:// example.org"):
            with self.subTest(external_evidence=invalid_url):
                failures = information_failures(
                    {**item, "external_evidence": invalid_url}
                )
                self.assertIn(
                    "author-name external_evidence must be a public HTTP(S) URL",
                    failures,
                )

    def test_author_name_rejects_non_public_or_malformed_http_urls(self):
        item = complete_item("Ada Lovelace")
        item.update(
            {
                "selection_mode": "author-name",
                "kind": "author-background",
                "information_roles": ["author_context"],
                "author_context": "First author background.",
                "external_evidence": "https://example.org/authors/ada-lovelace",
                "verified_at": "2026-07-24",
                "annotation_comment": "\u5916\u90e8\u6838\u9a8c\uff0c\u4e0d\u662f\u8bba\u6587\u6b63\u6587\u4e8b\u5b9e\uff1a\u4f5c\u8005\u80cc\u666f\u3002",
            }
        )
        invalid_urls = (
            "https://localhost/profile",
            "https://127.0.0.1/profile",
            "https://[::1]/profile",
            "https://192.168.1.10/profile",
            "https://[fd00::1]/profile",
            "https://example.com\\@evil.com/profile",
            "https://example.com:/profile",
            "https://example.com/\x00profile",
        )
        for invalid_url in invalid_urls:
            with self.subTest(external_evidence=invalid_url):
                failures = information_failures(
                    {**item, "external_evidence": invalid_url}
                )
                self.assertIn(
                    "author-name external_evidence must be a public HTTP(S) URL",
                    failures,
                )


    def test_accepts_metric_with_unit_and_runtime_context(self):

        item = complete_item(
            "The average and maximum computation times of the HOCBF correction "
            "are 90.61 μs and 384.5 μs, respectively."
        )
        item["kind"] = "experiment"
        item["information_roles"] = ["metric", "condition", "result"]
        result = validate_semantic_annotation(item)
        self.assertIn("90.61", result["quote"])

    def test_area_annotation_requires_visual_context(self):
        item = complete_item("")
        item.update(
            {
                "annotation_type": "area",
                "rect": [40, 40, 280, 120],
                "visual_object": "Table I, reward ablation rows and metric headers",
                "information_roles": ["metric", "comparison", "result"],
            }
        )
        result = validate_semantic_annotation(item)
        self.assertEqual(result["annotation_type"], "area")

        del item["visual_object"]
        with self.assertRaises(SemanticSelectionError):
            validate_semantic_annotation(item)

    def test_accepts_precise_relation_spans_and_truth_bearing_scope(self):
        cases = (
            ("incurs cumulative latency", "predicate"),
            (
                "alleviates local minima in Euclidean distance objectives",
                "predicate",
            ),
            (
                "only during the training phase and not during deployment",
                "condition",
            ),
        )
        for quote, relation_role in cases:
            with self.subTest(quote=quote):
                item = complete_item(quote)
                item.update(
                    {
                        "relation_group_id": "rel-regression",
                        "relation_role": relation_role,
                        "relation_type": "constrains",
                        "relation_summary": (
                            "The selected atom preserves a precise predicate or "
                            "truth-bearing deployment condition."
                        ),
                        "connector_mode": "shared-id",
                    }
                )
                result = validate_semantic_annotation(item)
                self.assertEqual(result["quote"], quote)

    def test_no_annotation_density_quota_is_encoded(self):
        self.assertEqual(validate_semantic_annotation(complete_item(
            "The policy receives the current proprioceptive state and the previous action."
        ))["page"], 1)


if __name__ == "__main__":
    unittest.main()
