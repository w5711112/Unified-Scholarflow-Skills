import json
import re
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
ENTRY = SKILL_ROOT / "SKILL.md"
ENTRY_REFS = [
    "references/file-format-spec.md",
    "references/screening-criteria.md",
    "references/venue-white-list.md",
    "references/scoring-rubric.md",
    "references/workflow.md",
    "references/zotero-obsidian-entry-contract.md",
]
class DroneScoutRouteBArchitectureTests(unittest.TestCase):
    def test_entry_has_one_reference_route_and_one_evidence_spine(self):
        text = ENTRY.read_text(encoding="utf-8")
        for ref in ENTRY_REFS:
            self.assertEqual(text.count(ref), 1, ref)
            self.assertTrue((SKILL_ROOT / ref).is_file(), ref)
        for evidence_id in ("CORPUS_AUDIT", "CANDIDATE_EVIDENCE", "DIRECTION_EVIDENCE", "ZOTERO_RECONCILIATION", "CYCLE_ACCEPTANCE"):
            self.assertIn(evidence_id, text)
        self.assertIn("同一证据边界", text)
        self.assertIn("只完整读取一次", text)

    def test_whitelist_and_critical_contract_are_lossless(self):
        authority = json.loads((SKILL_ROOT / "references" / "authority-map.json").read_text(encoding="utf-8"))
        self.assertEqual(authority["unmapped_removed_blocks"], [])
        venue_text = (SKILL_ROOT / "references" / "venue-white-list.md").read_text(encoding="utf-8")
        whitelist = re.findall(r"`([^`]+)`", venue_text.split("Core search coverage", 1)[0])
        self.assertEqual(len(whitelist), 22)
        combined = ENTRY.read_text(encoding="utf-8") + "\n" + "\n".join(
            (SKILL_ROOT / ref).read_text(encoding="utf-8") for ref in ENTRY_REFS
        )
        required = [
            "推荐度 0.05、前景 0.15、可行性 0.25、venue 匹配 0.10、独特性 0.25、证据强度 0.05、学习价值 0.15",
            "RTX 4090 single-digit hours",
            "RTX 5070 Ti within one day",
            "Jetson-class deployment",
            "固定 15 列",
            "完整原始摘要",
            "不得检索新论文",
            "0–15 个方向",
            "[Zotero的PDF]",
            "不得根据 paper ID、年份或 URL 猜 DOI",
            "CSV 是唯一论文事实源",
        ]
        for phrase in required:
            self.assertIn(phrase, combined, phrase)


if __name__ == "__main__":
    unittest.main()
