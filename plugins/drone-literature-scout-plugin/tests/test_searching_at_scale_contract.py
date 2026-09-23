from __future__ import annotations
import subprocess
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILL = PLUGIN_ROOT / "skills" / "searching-at-scale" / "SKILL.md"


class SearchingAtScaleContractTests(unittest.TestCase):
    def test_canonical_skill_exists(self):
        self.assertTrue(SKILL.is_file(), SKILL)

    def test_uncapped_discovery_and_run_specific_stop_reasons(self):
        text = SKILL.read_text(encoding="utf-8")
        for token in (
            "不设置固定 URL 数量上限", "搜索饱和停止前必须经验证",
            "10 分钟（600 秒）", "纯搜索时间", "规范化去重有效 URL",
            "正常成功路径不写故障库", "references/skill-collaboration-contract.md",
            "quick_direct", "open_web_research", "catalog_enumeration",
            "bounded_dataset_extract", "deterministic_scope_complete",
            "10 分钟（600 秒）硬上限",
        ):
            self.assertIn(token, text)
        self.assertNotIn("达到 10,000 后停止", text)
        self.assertNotIn("max_urls", text)

    def test_domestic_marketplace_edge_and_lightweight_contract(self):
        text = SKILL.read_text(encoding="utf-8")
        for token in (
            "Edge-only", "JD mandatory", "6,000", "10 去重商品候选/秒",
            "任意连续 30 秒", "不读取凭证", "不回退 Chrome", "日常 Edge",
            "Manifest V3", "Native Messaging", "不启用远程调试",
            "命名管道", "当前 Windows SID", "当前用户 HKCU",
            "一个 C# Native Host", "不读取 Cookie", "一次性 Node",
            "active:false", "operation: detail", "optional_host_permissions",
            "不跟踪价格",
            "--enable-jd-pagination", "真实翻页默认关闭",
            "--max-pages-per-topic", "可重复传入 `--topic`",
            "projection schema v4", "verified_pagination_v1",
        ):
            self.assertIn(token, text)

    def test_required_resources_are_linked(self):
        text = SKILL.read_text(encoding="utf-8")
        for path in (
            "references/source-routing.md", "references/adaptive-schema.md",
            "references/verification-contract.md", "references/report-contract.md",
            "scripts/build_query_matrix.py", "scripts/normalize_and_dedupe.py",
            "scripts/aggregate_evidence.py", "scripts/compute_timeseries.py",
            "scripts/validate_report.py", "scripts/render_search_timeline.py",
            "scripts/backend_runner.py", "scripts/runtime_manager.py",
            "scripts/searxng_query.py", "scripts/common_crawl_query.py",
            "scripts/edge_marketplace_query.py", "scripts/edge_extension_client.mjs",
            "scripts/install_edge_native_host.ps1", "edge-extension/manifest.json",
        ):
            self.assertIn(path, text)

    def test_focused_suite_runs_from_project_root(self):
        focused_tests = PLUGIN_ROOT / "skills" / "searching-at-scale" / "tests"
        completed = subprocess.run(
            [
                __import__("sys").executable, "-B", "-m", "unittest",
                "discover", "-s", str(focused_tests), "-v",
            ],
            cwd=PLUGIN_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
