from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "references" / "authority-map.json"


class UniversalBehaviorContractTests(unittest.TestCase):
    """Protect the machine-readable behavior boundary, not exact prose."""

    def setUp(self) -> None:
        self.data = json.loads(AUTHORITY.read_text(encoding="utf-8"))

    def test_plain_paragraph_and_dialogue_do_not_fall_back_to_academic_mode(self) -> None:
        scenes = self.data["scene_contracts"]
        self.assertEqual(
            {"paper-notes", "grant-proposal", "work-doc", "general-text", "dialogue"},
            set(scenes),
        )
        self.assertEqual("general-text", self.data["default_scene"])
        self.assertIn("chat turns", scenes["dialogue"]["signals"])
        self.assertIn("ordinary paragraph", scenes["general-text"]["signals"])

    def test_balanced_stance_preserves_required_force_without_servility_or_hostility(self) -> None:
        contract = self.data["universal_behavior_contract"]
        self.assertEqual(
            ["servile", "self-deprecating", "accusatory", "threatening", "provocative"],
            contract["forbidden_stance"],
        )
        self.assertTrue(contract["preserve_required_normative_force"])
        self.assertTrue(contract["forbid_unsupported_absolute_guarantees"])

    def test_source_and_commitment_boundary_is_conditional_not_invented(self) -> None:
        boundary = self.data["universal_behavior_contract"]["source_and_commitment_boundary"]
        self.assertEqual("when-authoritative-material-exists", boundary["condition"])
        self.assertTrue(boundary["preserve_existing_obligations"])
        self.assertTrue(boundary["forbid_scope_expansion"])
        self.assertTrue(boundary["forbid_invented_source_audit"])

    def test_cross_document_consistency_has_one_owner_and_no_duplicate_verification(self) -> None:
        cross_document = self.data["universal_behavior_contract"]["cross_document"]
        self.assertTrue(cross_document["consistent_terms_objects_numbers_and_references"])
        self.assertTrue(cross_document["single_owner_for_repeated_substance"])
        self.assertEqual("one-integrated-delivery-decision", cross_document["verification"])

    def test_table_centering_requires_properties_and_rendered_result(self) -> None:
        table = self.data["universal_behavior_contract"]["table_centering"]
        self.assertEqual(["property-inspection", "word-or-wps-render-inspection"], table["evidence"])
        self.assertEqual(["merged-cells", "multi-paragraph-cells", "save-reopen"], table["edge_cases"])


if __name__ == "__main__":
    unittest.main()
