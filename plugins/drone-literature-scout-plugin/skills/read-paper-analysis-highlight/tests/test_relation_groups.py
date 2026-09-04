from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from semantic_selection import (  # noqa: E402
    SemanticSelectionError,
    information_failures,
    validate_relation_groups,
)


def relation_item(
    quote: str,
    role: str,
    relation_type: str = "constrains",
    group_id: str = "rel-001",
) -> dict:
    return {
        "id": f"paper-001-{group_id}-{role}",
        "page": 1,
        "annotation_type": "highlight",
        "selection_mode": "semantic-span",
        "quote": quote,
        "kind": "problem",
        "color": "yellow",
        "note_question": "问题为什么成立？",
        "claim": "该片段承担技术关系中的一个明确语义角色。",
        "reason": "与同组证据合并后可还原研究对象、约束及其后果。",
        "information_roles": ["problem"],
        "evidence": "Introduction",
        "confidence": "high",
        "relation_group_id": group_id,
        "relation_role": role,
        "relation_type": relation_type,
        "relation_summary": (
            "Learning-based approaches are constrained by missing theoretical "
            "safety guarantees."
        ),
        "connector_mode": "shared-id",
    }


class RelationGroupTests(unittest.TestCase):
    def test_accepts_entity_and_predicate_group(self):
        items = [
            relation_item("learning-based approaches", "entity"),
            relation_item("lack theoretical safety guarantees", "predicate"),
        ]
        report = validate_relation_groups(items)
        self.assertTrue(report["valid"])
        self.assertEqual(report["relation_group_count"], 1)
        self.assertEqual(report["relation_annotation_count"], 2)
        for item in items:
            self.assertEqual(information_failures(item), [])

    def test_accepts_same_entity_in_two_distinct_failure_relations(self):
        first = [
            relation_item(
                "learning-based approaches",
                "entity",
                group_id="rel-guarantee",
            ),
            relation_item(
                "lack theoretical safety guarantees",
                "predicate",
                group_id="rel-guarantee",
            ),
        ]
        second = [
            relation_item(
                "learning-based approaches",
                "entity",
                group_id="rel-ood",
            ),
            relation_item(
                "out-of-distribution generalization failures",
                "predicate",
                group_id="rel-ood",
            ),
        ]
        report = validate_relation_groups(first + second)
        self.assertEqual(report["relation_group_count"], 2)

    def test_rejects_discourse_scaffolding_at_span_start(self):
        items = [
            relation_item(
                "Despite these advantages, learning-based approaches",
                "entity",
            ),
            relation_item("lack theoretical safety guarantees", "predicate"),
        ]
        with self.assertRaisesRegex(
            SemanticSelectionError,
            "discourse scaffolding",
        ):
            validate_relation_groups(items)

    def test_accepts_truth_bearing_scope_condition(self):
        items = [
            relation_item("privileged map rewards", "entity"),
            relation_item("are used", "predicate"),
            relation_item("only during the training phase", "condition"),
        ]
        report = validate_relation_groups(items)
        self.assertTrue(report["valid"])

    def test_rejects_group_without_predicate(self):
        items = [
            relation_item("learning-based approaches", "entity"),
            relation_item(
                "out-of-distribution conditions",
                "condition",
            ),
        ]
        with self.assertRaisesRegex(
            SemanticSelectionError,
            "requires at least one predicate",
        ):
            validate_relation_groups(items)

    def test_rejects_group_without_participant(self):
        items = [
            relation_item("lack", "predicate"),
            relation_item("cannot guarantee", "predicate"),
        ]
        with self.assertRaisesRegex(
            SemanticSelectionError,
            "requires at least one entity, effect, or condition",
        ):
            validate_relation_groups(items)

    def test_rejects_inconsistent_relation_types(self):
        items = [
            relation_item("learning-based approaches", "entity"),
            relation_item(
                "lack theoretical safety guarantees",
                "predicate",
                relation_type="causes",
            ),
        ]
        with self.assertRaisesRegex(
            SemanticSelectionError,
            "inconsistent relation_type",
        ):
            validate_relation_groups(items)

    def test_rejects_blank_relation_summary(self):
        items = [
            relation_item("learning-based approaches", "entity"),
            relation_item("lack theoretical safety guarantees", "predicate"),
        ]
        items[0]["relation_summary"] = "   "
        with self.assertRaisesRegex(
            SemanticSelectionError,
            "non-empty relation_summary",
        ):
            validate_relation_groups(items)

    def test_legacy_annotations_remain_valid(self):
        legacy = relation_item(
            "The actor processes a depth image and outputs attitude references.",
            "predicate",
        )
        for field in (
            "relation_group_id",
            "relation_role",
            "relation_type",
            "relation_summary",
            "connector_mode",
        ):
            legacy.pop(field)
        report = validate_relation_groups([legacy])
        self.assertTrue(report["valid"])
        self.assertEqual(report["relation_group_count"], 0)
        self.assertEqual(information_failures(legacy), [])

    def test_shared_id_connector_needs_no_ink_proof(self):
        items = [
            relation_item("learning-based approaches", "entity"),
            relation_item("lack theoretical safety guarantees", "predicate"),
        ]
        self.assertTrue(validate_relation_groups(items)["valid"])

    def test_native_ink_requires_complete_capability_proof(self):
        items = [
            relation_item("learning-based approaches", "entity"),
            relation_item("lack theoretical safety guarantees", "predicate"),
        ]
        for item in items:
            item["connector_mode"] = "native-ink"
        with self.assertRaisesRegex(
            SemanticSelectionError,
            "native-ink requires",
        ):
            validate_relation_groups(items)

        for item in items:
            item.update(
                {
                    "ink_native_key": "INKKEY1",
                    "editable_verified": True,
                    "deletable_verified": True,
                    "position_verified": True,
                    "refresh_verified": True,
                    "text_overlap_verified": False,
                }
            )
        self.assertTrue(validate_relation_groups(items)["valid"])

    def test_partial_relation_metadata_is_rejected(self):
        item = relation_item("learning-based approaches", "entity")
        item.pop("relation_type")
        failures = information_failures(item)
        self.assertTrue(
            any("partial relation metadata" in failure for failure in failures)
        )


if __name__ == "__main__":
    unittest.main()
