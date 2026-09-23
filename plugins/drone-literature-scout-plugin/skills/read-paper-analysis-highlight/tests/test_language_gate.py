from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from test_support import writable_test_directory  # noqa: E402
from validate_language_gate import validate_language_gate  # noqa: E402


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LanguageGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = writable_test_directory()
        self.root = Path(self._tmp.__enter__())
        self.draft = self.root / "semantic-draft.md"
        self.renhua = self.root / "renhua-output.md"
        self.note = self.root / "note.md"
        self.draft.write_text(
            "策略输出 candidate velocity，安全层检查后再执行。\n",
            encoding="utf-8",
        )
        self.renhua.write_text(
            "策略先给出无人机希望执行的 candidate velocity，安全层随后检查碰撞约束。\n",
            encoding="utf-8",
        )
        self.note.write_text(
            "### Fixture Paper\n"
            "^paper-fixture\n"
            "> [!note]- **来源**：Fixture\n"
            "> - 策略先给出无人机希望执行的 candidate velocity，安全层随后检查碰撞约束。\n"
            "> [!personal]+ 个人理解\n",
            encoding="utf-8",
        )
        self.personal_hash = hashlib.sha256(
            "> [!personal]+ 个人理解".encode("utf-8")
        ).hexdigest()

    def tearDown(self):
        self._tmp.__exit__(None, None, None)

    def receipt(self) -> dict:
        note_block = self.note.read_text(encoding="utf-8")
        return {
            "schema_version": 1,
            "scene": "paper-notes",
            "target_reader": "需要复现无人机规划数据流的研究生",
            "semantic_draft": {
                "path": str(self.draft),
                "sha256": digest(self.draft),
            },
            "renhua_output": {
                "path": str(self.renhua),
                "sha256": digest(self.renhua),
            },
            "final_note": {
                "path": str(self.note),
                "sha256": digest(self.note),
                "block_id": "paper-fixture",
                "block_sha256": hashlib.sha256(
                    note_block.encode("utf-8")
                ).hexdigest(),
            },
            "protection_ledger": {
                "numbers_and_units_preserved": True,
                "formulas_preserved": True,
                "citations_preserved": True,
                "claims_and_boundaries_preserved": True,
                "personal_content_sha256_before": self.personal_hash,
                "personal_content_sha256_after": self.personal_hash,
            },
            "term_decision_ledger": [
                {
                    "term": "candidate velocity",
                    "chosen_form": "candidate velocity",
                    "reason": "中文直译不如领域原词准确",
                    "first_occurrence": "How / 使用的方法是什么？",
                    "meaning_preserved": True,
                    "explanation_present": True,
                }
            ],
            "readthrough_result": {
                "full_ai_block_read": True,
                "flow_continuity_verified": True,
                "section_transitions_verified": True,
                "density_expanded_when_needed": True,
            },
            "delivery_acceptance": {
                "fidelity_verified": True,
                "clarity_verified": True,
                "term_consistency_verified": True,
                "no_hard_translation_verified": True,
                "no_ai_residue_verified": True,
                "flow_continuity_verified": True,
                "personal_content_unchanged": True,
            },
        }

    def write_receipt(self, payload: dict) -> Path:
        path = self.root / "language-gate.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def test_valid_language_gate_passes(self):
        report = validate_language_gate(self.write_receipt(self.receipt()))
        self.assertTrue(report["valid"], report["failures"])
        self.assertEqual(report["scene"], "paper-notes")

    def test_self_report_without_real_files_is_rejected(self):
        payload = self.receipt()
        payload["semantic_draft"]["path"] = str(self.root / "missing.md")
        report = validate_language_gate(self.write_receipt(payload))
        self.assertFalse(report["valid"])
        self.assertIn("semantic_draft path does not exist", report["failures"])

    def test_stale_stage_hash_is_rejected(self):
        payload = self.receipt()
        payload["renhua_output"]["sha256"] = "0" * 64
        report = validate_language_gate(self.write_receipt(payload))
        self.assertFalse(report["valid"])
        self.assertIn("renhua_output sha256 mismatch", report["failures"])

    def test_personal_content_hash_mismatch_is_rejected(self):
        payload = self.receipt()
        payload["protection_ledger"]["personal_content_sha256_after"] = "1" * 64
        report = validate_language_gate(self.write_receipt(payload))
        self.assertFalse(report["valid"])
        self.assertIn("personal content changed", report["failures"])

    def test_retained_english_term_requires_an_in_context_explanation(self):
        payload = self.receipt()
        payload["term_decision_ledger"][0]["explanation_present"] = False
        report = validate_language_gate(self.write_receipt(payload))
        self.assertFalse(report["valid"])
        self.assertIn(
            "term decision needs an in-context explanation: candidate velocity",
            report["failures"],
        )

    def test_wrong_scene_and_incomplete_readthrough_are_rejected(self):
        payload = self.receipt()
        payload["scene"] = "general-text"
        payload["readthrough_result"]["full_ai_block_read"] = False
        report = validate_language_gate(self.write_receipt(payload))
        self.assertFalse(report["valid"])
        self.assertIn("scene must be paper-notes", report["failures"])
        self.assertIn(
            "readthrough_result.full_ai_block_read must be true",
            report["failures"],
        )


if __name__ == "__main__":
    unittest.main()

