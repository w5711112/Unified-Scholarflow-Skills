from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
ENTRY = SKILL_ROOT / "SKILL.md"
LEGACY = Path(__file__).resolve().parent / "fixtures" / "SKILL.before-route-b.md"
AUTHORITY_MAP = SKILL_ROOT / "references" / "authority-map.json"
MANIFEST = PLUGIN_ROOT / "architecture-manifest.json"

RUNTIME_REFERENCES = (
    "visual-language.md",
    "color-font-archive.md",
    "layout-patterns.md",
    "ppt-figures.md",
    "obsidian-knowledge-figures.md",
    "paper-method-figures.md",
    "data-chart-selector.md",
    "paper-data-figures.md",
    "rss2026-analysis-protocol.md",
    "rss2026-learning-ledger.md",
)


def normalized_blocks(text: str) -> list[str]:
    text = text.replace("\r\n", "\n")
    if text.startswith("---\n"):
        text = text.split("---\n", 2)[2]
    result: list[str] = []
    for raw in re.split(r"\n\s*\n", text):
        lines = [line.rstrip() for line in raw.strip().splitlines()]
        while lines and lines[0].startswith("#"):
            lines.pop(0)
        if lines:
            result.append("\n".join(lines))
    return result


class DrawStyleRouteBArchitectureTests(unittest.TestCase):
    def test_manifest_exposes_runtime_routes_assets_interfaces_and_numeric_guards(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(data["architecture_version"], "2.1.0")
        item = data["skills"]["draw-style"]
        self.assertEqual(item["migration_state"], "modular-v1")
        self.assertEqual(item["interface_version"], "1.0.0")
        self.assertEqual(
            item["references"],
            [f"skills/draw-style/references/{name}" for name in RUNTIME_REFERENCES],
        )
        self.assertEqual(
            item["evidence_assets"],
            {
                "corpus_index": "skills/draw-style/references/rss2026-corpus-index.json",
                "batch_cards": "skills/draw-style/references/rss2026-batches/batch-*.md",
            },
        )
        self.assertEqual(
            item["numeric_guards"],
            {
                "core_color_families": 6,
                "continuous_color_scales": 4,
                "named_templates": 3,
                "chart_candidates_min": 2,
                "chart_candidates_max": 4,
                "ppt_visual_objects_min": 3,
                "ppt_visual_objects_max": 7,
                "auxiliary_master_max": 1,
                "quality_gates": 8,
                "rss_corpus_size": 103,
                "rss_batch_size": 5,
                "rss_accelerated_window": 10,
            },
        )
        self.assertEqual(
            item["calls"],
            {
                "conditional": ["visualizing-and-writing-modeling-papers"],
                "handoffs": ["obsidian-note-style"],
                "failure": ["global.collect-bug-update-accelerate"],
            },
        )

    def test_each_runtime_reference_has_one_direct_route(self):
        text = ENTRY.read_text(encoding="utf-8")
        for name in RUNTIME_REFERENCES:
            self.assertEqual(text.count(f"references/{name}"), 1, name)

    def test_single_pass_evidence_contract_is_explicit(self):
        text = ENTRY.read_text(encoding="utf-8")
        for evidence_id in (
            "VISUAL_SOURCE_EVIDENCE",
            "VISUAL_BLUEPRINT",
            "VISUAL_ACCEPTANCE",
        ):
            self.assertIn(evidence_id, text)
        self.assertIn("同一门内只生成一次", text)
        self.assertIn("新的证据边界", text)
        self.assertIn("整批冻结", text)
        self.assertIn("单条规则确认", text)

    def test_compact_fixture_is_exact_and_full_history_remains_recorded(self):
        mapping = json.loads(AUTHORITY_MAP.read_text(encoding="utf-8"))
        self.assertEqual(mapping["compact_fixture_sha256"], hashlib.sha256(LEGACY.read_bytes()).hexdigest())
        self.assertEqual(mapping["legacy_sha256"], "73772e097ae1274e075d8995a5e5d795596cf218305b7f3ecd533cb64d69411f")
        self.assertLessEqual(LEGACY.stat().st_size, 4096)
        self.assertTrue(LEGACY.read_text(encoding="utf-8").startswith("---\nname:"))
        self.assertTrue(mapping["rewritten_blocks"])


if __name__ == "__main__":
    unittest.main()
