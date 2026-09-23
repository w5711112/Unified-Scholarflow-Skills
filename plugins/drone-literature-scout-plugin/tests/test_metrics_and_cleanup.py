import sys
import unittest
from pathlib import Path
from test_support import writable_test_directory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from clean_cycle import clean_cycle
from generate_core_docs import generate_analysis
from research_metrics import WEIGHTS, direction_hard_gate, rank_directions, score_direction


DIMENSIONS = {
    "recommendation": 3,
    "prospect": 3,
    "feasibility": 3,
    "venue_fit": 3,
    "uniqueness": 3,
    "evidence": 3,
    "learning_fit": 3,
}


class MetricsAndCleanupTests(unittest.TestCase):
    def test_scheme_a_weights_prioritize_feasibility_novelty_and_learning_fit(self):
        self.assertEqual(
            WEIGHTS,
            {
                "recommendation": 0.05,
                "prospect": 0.15,
                "feasibility": 0.25,
                "venue_fit": 0.10,
                "uniqueness": 0.25,
                "evidence": 0.05,
                "learning_fit": 0.15,
            },
        )

    def test_direction_hard_gate_rejects_overbudget_above_jetson_and_generic_topics(self):
        cases = (
            ({"hard_gate": True, "training_budget_status": "over_budget"}, "训练预算"),
            ({"hard_gate": True, "deployment_status": "above_jetson"}, "部署"),
            ({"hard_gate": True, "generic_topic": True}, "传统低新颖性"),
        )
        for candidate, reason_fragment in cases:
            accepted, reasons = direction_hard_gate(candidate)
            self.assertFalse(accepted)
            self.assertTrue(any(reason_fragment in reason for reason in reasons))

    def test_direction_hard_gate_keeps_unknown_budget_as_hold_not_pass(self):
        accepted, reasons = direction_hard_gate(
            {
                "hard_gate": True,
                "training_budget_status": "unknown",
                "deployment_status": "unknown",
            }
        )
        self.assertTrue(accepted)
        self.assertTrue(any("待核验" in reason for reason in reasons))

    def test_direction_score_uses_the_approved_weights(self):
        self.assertEqual(score_direction(DIMENSIONS), 3.0)
        high_learning = {**DIMENSIONS, "learning_fit": 5}
        self.assertGreater(score_direction(high_learning), 3.0)

    def test_direction_score_preserves_two_decimal_places(self):
        precise = {name: 3.33 for name in DIMENSIONS}
        self.assertEqual(score_direction(precise), 3.33)

    def test_analysis_requires_detailed_evidence_sections(self):
        rows = [{
            "title": "Safe Navigation with Control Barrier Functions",
            "venue_time": "2025",
            "source": "ICRA",
            "abstract": "This is a complete original abstract with enough detail to describe the method and results." * 4,
            "url": "https://doi.org/10.1109/ICRA.2025.1234567",
            "abstract_source_url": "https://doi.org/10.1109/ICRA.2025.1234567",
            "fulltext_status": "abstract_only",
            "fulltext_url": "",
            "method_evidence": "",
            "compute_evidence": "",
            "experiment_evidence": "",
        }]
        output = generate_analysis(rows, "2026-07-13")
        for heading in ("技术路线", "量化算力与部署可行性", "最小可行实验", "证据缺口与主要风险"):
            self.assertIn(heading, output)

    def test_direction_pool_is_dynamic_and_capped_at_fifteen(self):
        candidates = [
            {"name": str(i), "dimensions": DIMENSIONS.copy(), "hard_gate": True}
            for i in range(20)
        ]
        self.assertEqual(len(rank_directions(candidates, limit=15)), 15)

    def test_cleanup_preserves_only_three_core_files_and_plugin(self):
        with writable_test_directory() as temp:
            workspace = Path(temp)
            plugin_root = workspace / "drone-literature-scout-plugin"
            plugin_root.mkdir()
            for name in (
                "论文库统一.csv",
                "论文总结.md",
                "研究方向分析.md",
                "tmp-search.json",
                "_encoding_probe.txt",
                "corpus.tmp.csv",
                "corpus.repaired.csv",
            ):
                (workspace / name).write_text("x", encoding="utf-8")
            (plugin_root / "SKILL.md").write_text("x", encoding="utf-8")
            cache = plugin_root / "__pycache__"
            cache.mkdir()
            (cache / "stale.pyc").write_bytes(b"x")

            clean_cycle(workspace, {"论文库统一.csv", "论文总结.md", "研究方向分析.md"}, plugin_root)

            self.assertFalse((workspace / "tmp-search.json").exists())
            self.assertFalse((workspace / "_encoding_probe.txt").exists())
            self.assertFalse((workspace / "corpus.tmp.csv").exists())
            self.assertFalse((workspace / "corpus.repaired.csv").exists())
            self.assertTrue((workspace / "论文库统一.csv").exists())
            self.assertTrue((plugin_root / "SKILL.md").exists())
            self.assertFalse(cache.exists())


if __name__ == "__main__":
    unittest.main()
