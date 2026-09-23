from __future__ import annotations

import hashlib
import json
import os
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "SKILL.md"
DEFAULT_DRAFT_ROOT = Path(
    r"C:\Users\w5711112\.zcode\workspace\default\humanize-compare\renhua-draft"
)
DRAFT_ROOT = Path(os.environ.get("RENHUA_DRAFT_ROOT", str(DEFAULT_DRAFT_ROOT)))
DRAFT_ENTRY = DRAFT_ROOT / "SKILL.md"
MAIN_FIXTURE = ROOT / "tests" / "fixtures" / "SKILL.main.before-route-b.md"
DRAFT_FIXTURE = ROOT / "tests" / "fixtures" / "SKILL.draft.before-route-b.md"
AUTHORITY = ROOT / "references" / "authority-map.json"

DIRECT_REFERENCES = (
    "references/core-authority-and-scenarios.md",
    "references/rewrite-rules-r1-r8.md",
    "references/rewrite-rules-r9-r17.md",
    "references/execution-and-delivery-contract.md",
    "references/document-table-format.md",
)

EVIDENCE_OBJECTS = (
    "SOURCE_BASELINE",
    "PROTECTION_LEDGER",
    "EDIT_LEDGER",
    "READTHROUGH_RESULT",
    "DELIVERY_ACCEPTANCE",
)


def authority_text(root: Path = ROOT) -> str:
    return "\n".join(
        [root.joinpath("SKILL.md").read_text(encoding="utf-8")]
        + [root.joinpath(route).read_text(encoding="utf-8") for route in DIRECT_REFERENCES]
    )


class RouteBArchitectureTests(unittest.TestCase):
    def test_legacy_fixtures_are_compact_and_exact(self) -> None:
        data = json.loads(AUTHORITY.read_text(encoding="utf-8"))
        self.assertEqual(
            hashlib.sha256(MAIN_FIXTURE.read_bytes()).hexdigest(),
            data["main_compact_fixture_sha256"],
        )
        self.assertEqual(
            hashlib.sha256(DRAFT_FIXTURE.read_bytes()).hexdigest(),
            data["draft_compact_fixture_sha256"],
        )
        self.assertEqual(
            data["main_legacy_sha256"],
            "30a843373b1006e991282d9c9e3773ab2fd46a5104e2d39960755a4a59c00d85",
        )
        self.assertEqual(
            data["draft_legacy_sha256"],
            "9ff6d14c59a9a388561281682fbf074ab542979733ce9a5759d2cf9c714a86a9",
        )
        for fixture in (MAIN_FIXTURE, DRAFT_FIXTURE):
            self.assertLessEqual(fixture.stat().st_size, 4096)
            self.assertTrue(fixture.read_text(encoding="utf-8").startswith("---\nname:"))

    def test_entry_is_a_bounded_one_level_router(self) -> None:
        text = ENTRY.read_text(encoding="utf-8")
        self.assertLessEqual(len(ENTRY.read_bytes()), 9000)
        for route in DIRECT_REFERENCES:
            self.assertEqual(text.count(route), 1, route)
        self.assertIn("直接参考不得继续路由第二层参考", text)

    def test_single_evidence_spine_and_one_pass_model_are_explicit(self) -> None:
        text = ENTRY.read_text(encoding="utf-8")
        for name in EVIDENCE_OBJECTS:
            self.assertIn(name, text)
        self.assertIn("只刷新受影响对象及下游", text)
        self.assertIn("主循环", text)
        self.assertIn("一轮通读", text)
        self.assertIn("对账输出", text)
        self.assertIn("禁止重新发起全文重扫", text)

    def test_all_rules_scenes_and_numeric_guards_remain_authoritative(self) -> None:
        combined = authority_text()
        rule_ids = {int(value) for value in re.findall(r"^### R(\d+)\b", combined, re.M)}
        self.assertEqual(rule_ids, set(range(1, 18)))
        for token in (
            "paper-notes",
            "grant-proposal",
            "work-doc",
            "general-text",
            "dialogue",
            "每 300 字 ≤1 个",
            "约 40 字",
            "同段同构 ≤2 处",
            "同段 2+ 个才处理",
            "±20% 以内",
            "连续 ≥3 个同构标签段",
            "三线表默认",
            "约1.5pt",
            "约0.75pt",
            "firstLineChars=0",
            "相邻两张表格之间必须插入一个空段落",
        ):
            self.assertIn(token, combined)

    def test_authority_map_has_no_missing_main_requirements(self) -> None:
        data = json.loads(AUTHORITY.read_text(encoding="utf-8"))
        self.assertEqual(data["architecture_version"], "route-b-v3")
        self.assertEqual(data["main_compact_fixture_sha256"], hashlib.sha256(MAIN_FIXTURE.read_bytes()).hexdigest())
        self.assertEqual(data["draft_compact_fixture_sha256"], hashlib.sha256(DRAFT_FIXTURE.read_bytes()).hexdigest())
        self.assertEqual(data["direct_references"], list(DIRECT_REFERENCES))
        self.assertEqual(data["evidence_objects"], list(EVIDENCE_OBJECTS))
        self.assertEqual(data["rule_count"], 17)
        self.assertEqual(data["scene_count"], 5)
        self.assertEqual(data["iron_law_count"], 5)
        self.assertEqual(data["delivery_gate_count"], 6)
        self.assertEqual(data["missing_main_requirements"], [])

    def test_draft_is_byte_identical_to_main_skill_package(self) -> None:
        self.assertEqual(ENTRY.read_bytes(), DRAFT_ENTRY.read_bytes())
        for route in DIRECT_REFERENCES:
            self.assertEqual(
                ROOT.joinpath(route).read_bytes(),
                (DRAFT_ROOT / route).read_bytes(),
            )
        self.assertEqual(
            AUTHORITY.read_bytes(),
            (DRAFT_ROOT / "references" / "authority-map.json").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
