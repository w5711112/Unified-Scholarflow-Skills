from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "SKILL.md"
FIXTURE = ROOT / "tests" / "fixtures" / "SKILL.before-route-b.md"
AUTHORITY = ROOT / "references" / "authority-map.json"

DIRECT_REFERENCES = (
    "references/source-routing.md",
    "references/domestic-marketplace-edge-contract.md",
    "references/global-scheduler.md",
    "references/adaptive-schema.md",
    "references/verification-contract.md",
    "references/report-contract.md",
    "references/runtime-lifecycle-and-cleanup.md",
)

EVIDENCE_OBJECTS = (
    "SEARCH_SCOPE",
    "BACKEND_CAPABILITIES",
    "MARKET_RUN",
    "DISCOVERY_LEDGER",
    "COVERAGE_STATE",
    "EVIDENCE_PACKAGE",
    "REPORT_PACKAGE",
    "RUN_ACCEPTANCE",
)


class RouteBArchitectureTests(unittest.TestCase):
    def test_legacy_fixture_is_compact_and_exact(self) -> None:
        data = json.loads(AUTHORITY.read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), data["compact_fixture_sha256"])
        self.assertLessEqual(FIXTURE.stat().st_size, 4096)
        self.assertTrue(FIXTURE.read_text(encoding="utf-8").startswith("---\nname:"))

    def test_entry_is_a_bounded_one_level_router(self) -> None:
        text = ENTRY.read_text(encoding="utf-8")
        self.assertLessEqual(len(ENTRY.read_bytes()), 22000)
        for route in DIRECT_REFERENCES:
            self.assertEqual(text.count(route), 1, route)
        self.assertIn("直接参考不得继续路由第二层参考", text)

    def test_single_evidence_spine_is_explicit(self) -> None:
        text = ENTRY.read_text(encoding="utf-8")
        for name in EVIDENCE_OBJECTS:
            self.assertIn(name, text)
        self.assertIn("只刷新受影响对象及下游", text)
        self.assertIn("最终新鲜验证", text)

    def test_authority_map_preserves_whitelists_and_numeric_guards(self) -> None:
        data = json.loads(AUTHORITY.read_text(encoding="utf-8"))
        self.assertEqual(data["compact_fixture_sha256"], hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
        self.assertEqual(data["direct_references"], list(DIRECT_REFERENCES))
        self.assertEqual(data["evidence_objects"], list(EVIDENCE_OBJECTS))
        self.assertEqual(data["whitelist_counts"]["backend_kinds"], 6)
        self.assertEqual(data["whitelist_counts"]["run_types"], 4)
        self.assertEqual(data["whitelist_counts"]["bulk_states"], 4)
        self.assertEqual(data["whitelist_counts"]["source_roles"], 5)
        self.assertEqual(data["whitelist_counts"]["jd_query_families"], 5)
        self.assertEqual(data["whitelist_counts"]["jd_session_actions"], 3)
        self.assertEqual(data["whitelist_counts"]["jd_diagnostic_keys"], 11)
        self.assertEqual(data["whitelist_counts"]["jd_card_fields"], 7)
        self.assertEqual(data["missing_legacy_requirements"], [])

    def test_exact_operational_guards_remain_in_the_authority_set(self) -> None:
        combined = ENTRY.read_text(encoding="utf-8") + "\n" + "\n".join(
            (ROOT / route).read_text(encoding="utf-8")
            for route in DIRECT_REFERENCES
        )
        for token in (
            "10 分钟（600 秒）硬上限",
            "900 秒",
            "raw_url_observations_per_second >= 50",
            "至少两个批次",
            "5 秒",
            "15 秒",
            "6,000",
            "10 去重商品候选/秒",
            "30 秒",
            "90 秒",
            "1 可复核卡片/秒（60/min）",
            "1..512",
            "200KB",
            "protocol_version: 3",
            "projection schema v4",
            "45 秒慢启动",
            "30 秒下限",
            "25%",
            "±35%",
            "≥1800s",
            "≥3600s",
            "2 → 4",
            "1 → 2",
            "4 → 8 → 16",
            "24 → 32 → 40",
        ):
            self.assertIn(token, combined)


if __name__ == "__main__":
    unittest.main()
