import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()
SKILL_ROOT = Path(__file__).resolve().parents[1]

from scripts.render_search_timeline import (
    FunnelStage,
    SearchCheckpoint,
    active_discovery_seconds,
    downsample_checkpoints,
    render_ascii,
    render_mermaid,
    render_svg,
    run_cli,
    summarize_throughput,
)


def point(
    seconds: float,
    raw: int,
    unique: int,
    backend: str = "web",
    backend_kind: str = "search",
    marketplace_candidates: int = 0,
) -> SearchCheckpoint:
    return SearchCheckpoint(
        pure_discovery_seconds=seconds,
        raw_url_observations=raw,
        valid_url_observations=raw,
        normalized_unique_urls=unique,
        unique_objects=min(unique, 10),
        backend=backend,
        backend_kind=backend_kind,
        actual_in_flight=4,
        unique_marketplace_candidates=marketplace_candidates,
    )


def product_payload(chart_format: str = "svg") -> dict[str, object]:
    return {
        "checkpoints": [
            {
                "pure_discovery_seconds": 0,
                "raw_url_observations": 0,
                "valid_url_observations": 0,
                "normalized_unique_urls": 0,
                "unique_objects": 0,
                "backend": "origin",
                "backend_kind": "sitemap",
                "actual_in_flight": 0,
            },
            {
                "pure_discovery_seconds": 10,
                "raw_url_observations": 1000,
                "valid_url_observations": 990,
                "normalized_unique_urls": 900,
                "unique_objects": 50,
                "backend": "product-sitemap",
                "backend_kind": "sitemap",
                "actual_in_flight": 24,
            },
        ],
        "funnel": [
            {"name": "raw_url_observations", "retained_count": 1000},
            {"name": "literal_unique_urls", "retained_count": 950},
            {"name": "normalized_unique_urls", "retained_count": 900},
            {"name": "content_unique_pages", "retained_count": 800},
            {"name": "topic_relevant_pages", "retained_count": 200},
            {"name": "product_page_candidates", "retained_count": 100},
            {"name": "unique_valid_structured_records", "retained_count": 50},
        ],
        "format": chart_format,
    }


class TimelineTests(unittest.TestCase):
    def test_two_point_marketplace_svg_has_visible_green_line_and_markers(self):
        checkpoints = (
            point(0, 0, 0, marketplace_candidates=0),
            point(48.4, 120, 38, marketplace_candidates=38),
        )
        chart = render_svg(
            checkpoints, marketplace=True
        )
        self.assertIn('stroke="#2e7d32" stroke-width="4"', chart)
        self.assertEqual(chart.count("data-discovery-marker"), 2)
        match = re.search(
            r'<polyline data-series="discovery" points="([^"]+)"', chart
        )
        self.assertIsNotNone(match)
        points = [tuple(map(float, value.split(","))) for value in match.group(1).split()]
        self.assertEqual(2, len(points))
        self.assertNotEqual(points[0][1], points[1][1])
        markers = re.findall(
            r'<circle data-discovery-marker="true" '
            r'cx="([^"]+)" cy="([^"]+)"',
            chart,
        )
        self.assertEqual(
            (str(int(points[-1][0])), str(int(points[-1][1]))), markers[-1]
        )

    def test_marketplace_retains_every_checkpoint_beyond_svg_limit(self):
        checkpoints = tuple(
            point(index, index * 10, index, marketplace_candidates=index)
            for index in range(30)
        )
        chart = render_svg(checkpoints, marketplace=True)
        match = re.search(
            r'<polyline data-series="discovery" points="([^"]+)"', chart
        )
        self.assertIsNotNone(match)
        self.assertEqual(30, len(match.group(1).split()))
        self.assertEqual(30, chart.count("data-discovery-marker"))
        ascii_chart = render_ascii(checkpoints, marketplace=True)
        sparkline = ascii_chart.split("字符折线：", 1)[1].split("  ", 1)[0]
        self.assertEqual(30, len(sparkline))

    def test_marketplace_funnel_retains_every_checkpoint_beyond_limit(self):
        checkpoints = tuple(
            point(index, index * 10, index, marketplace_candidates=index)
            for index in range(30)
        )
        funnel = (
            FunnelStage("raw_url_observations", 290),
            FunnelStage("normalized_unique_urls", 29),
            FunnelStage("unique_marketplace_candidates", 29),
            FunnelStage("unique_valid_structured_records", 29),
        )
        chart = render_svg(checkpoints, funnel=funnel, marketplace=True)
        match = re.search(
            r'<polyline data-series="discovery" points="([^"]+)"', chart
        )
        self.assertIsNotNone(match)
        self.assertEqual(30, len(match.group(1).split()))
        self.assertEqual(30, chart.count("data-discovery-marker"))

    def test_nonmarketplace_funnel_keeps_default_downsampling_and_transitions(self):
        checkpoints = tuple(
            point(
                index,
                index * 10,
                index,
                backend=("alternate" if index in {10, 20} else "web"),
            )
            for index in range(30)
        )
        funnel = (
            FunnelStage("raw_url_observations", 290),
            FunnelStage("literal_unique_urls", 280),
            FunnelStage("normalized_unique_urls", 29),
            FunnelStage("content_unique_pages", 29),
            FunnelStage("topic_relevant_pages", 29),
            FunnelStage("product_page_candidates", 29),
            FunnelStage("unique_valid_structured_records", 29),
        )
        chart = render_svg(checkpoints, funnel=funnel)
        match = re.search(
            r'<polyline data-series="discovery" points="([^"]+)"', chart
        )
        self.assertIsNotNone(match)
        rendered = [tuple(map(float, value.split(","))) for value in match.group(1).split()]
        self.assertLessEqual(len(rendered), 24)
        self.assertEqual(82.0, rendered[0][0])
        self.assertEqual(600.0, rendered[-1][0])
        for index in (10, 11, 20, 21):
            expected_x = 82 + (index / 29) * (600 - 82)
            self.assertTrue(
                any(abs(x - expected_x) < 0.001 for x, _ in rendered),
                f"missing backend transition checkpoint {index}",
            )

    def test_marketplace_funnel_uses_green_discovery_and_red_funnel(self):
        checkpoints = (
            point(0, 0, 0, marketplace_candidates=0),
            point(48.4, 120, 38, marketplace_candidates=38),
        )
        funnel = (
            FunnelStage("raw_url_observations", 120),
            FunnelStage("normalized_unique_urls", 38),
            FunnelStage("unique_marketplace_candidates", 38),
            FunnelStage("unique_valid_structured_records", 30),
        )
        chart = render_svg(checkpoints, funnel=funnel, marketplace=True)
        self.assertIn('data-series="discovery"', chart)
        self.assertIn('data-series="funnel"', chart)
        self.assertIn('stroke="#2e7d32"', chart)
        self.assertIn('stroke="#c62828"', chart)
        self.assertEqual(chart.count("data-discovery-marker"), 2)

    def test_shared_funnel_endpoint_keeps_green_ring_above_red_marker(self):
        checkpoints = (
            point(0, 0, 0, marketplace_candidates=0),
            point(48.4, 38, 38, marketplace_candidates=38),
        )
        funnel = (
            FunnelStage("raw_url_observations", 38),
            FunnelStage("normalized_unique_urls", 38),
            FunnelStage("unique_marketplace_candidates", 38),
            FunnelStage("unique_valid_structured_records", 38),
        )
        chart = render_svg(checkpoints, funnel=funnel, marketplace=True)
        red = '<circle cx="600" cy="94.6" r="4" fill="#c62828" />'
        green = (
            '<circle data-discovery-marker="true" cx="600" cy="94.6" r="6" '
            'fill="none" stroke="#2e7d32" stroke-width="3" />'
        )
        self.assertIn(red, chart)
        self.assertIn(green, chart)
        self.assertLess(chart.index(red), chart.index(green))

    def test_marketplace_ascii_fallback_keeps_discovery_and_funnel(self):
        payload = product_payload("ascii")
        payload["run_type"] = "catalog_enumeration"
        payload["checkpoints"][1]["unique_marketplace_candidates"] = 38
        payload["funnel"] = [
            {"name": "raw_url_observations", "retained_count": 1000},
            {"name": "normalized_unique_urls", "retained_count": 900},
            {"name": "unique_marketplace_candidates", "retained_count": 38},
            {"name": "unique_valid_structured_records", "retained_count": 30},
        ]
        chart = run_cli(payload)["chart"]
        self.assertIn("字符折线", chart)
        self.assertIn("10s/38 候选", chart)
        self.assertIn("原始 URL=1000", chart)
        self.assertIn("有效记录=30", chart)

    def test_catalog_chart_uses_deduplicated_candidate_series_and_labels(self):
        payload = {
            "run_type": "catalog_enumeration",
            "checkpoints": [
                {
                    "pure_discovery_seconds": 0,
                    "raw_url_observations": 0,
                    "valid_url_observations": 0,
                    "normalized_unique_urls": 0,
                    "unique_objects": 0,
                    "unique_marketplace_candidates": 0,
                    "backend": "origin",
                    "backend_kind": "search",
                    "actual_in_flight": 0,
                },
                {
                    "pure_discovery_seconds": 30,
                    "raw_url_observations": 1500,
                    "valid_url_observations": 1400,
                    "normalized_unique_urls": 900,
                    "unique_objects": 120,
                    "unique_marketplace_candidates": 120,
                    "backend": "edge:jd",
                    "backend_kind": "page",
                    "actual_in_flight": 2,
                },
                {
                    "pure_discovery_seconds": 60,
                    "raw_url_observations": 3000,
                    "valid_url_observations": 2800,
                    "normalized_unique_urls": 1700,
                    "unique_objects": 240,
                    "unique_marketplace_candidates": 240,
                    "backend": "searxng",
                    "backend_kind": "search",
                    "actual_in_flight": 4,
                },
            ],
            "funnel": [
                {"name": "raw_url_observations", "retained_count": 3000},
                {"name": "normalized_unique_urls", "retained_count": 1700},
                {"name": "unique_marketplace_candidates", "retained_count": 240},
                {"name": "unique_valid_structured_records", "retained_count": 200},
            ],
            "format": "svg",
        }
        result = run_cli(payload)
        self.assertIn("商品候选发现与 L0–L3 漏斗", result["chart"])
        self.assertIn("累计去重商品候选", result["chart"])
        self.assertIn("去重候选/秒", result["chart"])
        self.assertNotIn("平均速度 50 URL/s", result["chart"])
        self.assertEqual(
            result["metrics"]["unique_marketplace_candidates_per_second"],
            4.0,
        )
        self.assertEqual(
            result["metrics"][
                "recent_unique_marketplace_candidates_per_second"
            ],
            4.0,
        )

    def test_html_fragment_is_lightweight_and_zooms_inside_codex(self):
        fragment = run_cli(product_payload("html"))["chart"]
        for token in (
            "data-search-timeline-root",
            'addEventListener("wheel"',
            'addEventListener("pointerdown"',
            'data-action="zoom-in"',
            'data-action="zoom-out"',
            'data-action="reset"',
            "data-zoom-value",
            "MIN_SCALE = 1",
            "MAX_SCALE = 4",
            "viewBox",
        ):
            self.assertIn(token, fragment)
        for forbidden in (
            "window.open",
            "fetch(",
            "XMLHttpRequest",
            "WebSocket",
            "https://",
        ):
            self.assertNotIn(forbidden, fragment)

    def test_html_fragment_has_large_type_and_boundary_wheel_fallthrough(self):
        fragment = run_cli(product_payload("html"))["chart"]
        for token in (
            'font-size="24"',
            'font-size="18"',
            'font-size="16"',
            "atLowerBound",
            "atUpperBound",
            "event.preventDefault()",
        ):
            self.assertIn(token, fragment)

    def test_svg_renders_discovery_and_complete_filter_funnel(self):
        result = run_cli(
            {
                "checkpoints": [
                    {
                        "pure_discovery_seconds": 0,
                        "raw_url_observations": 0,
                        "valid_url_observations": 0,
                        "normalized_unique_urls": 0,
                        "unique_objects": 0,
                        "backend": "origin",
                        "backend_kind": "sitemap",
                        "actual_in_flight": 0,
                    },
                    {
                        "pure_discovery_seconds": 10,
                        "raw_url_observations": 37105,
                        "valid_url_observations": 30000,
                        "normalized_unique_urls": 18141,
                        "unique_objects": 222,
                        "backend": "product-sitemap",
                        "backend_kind": "sitemap",
                        "actual_in_flight": 24,
                    },
                ],
                "funnel": [
                    {"name": "raw_url_observations", "retained_count": 37105},
                    {"name": "literal_unique_urls", "retained_count": 25545},
                    {"name": "normalized_unique_urls", "retained_count": 18141},
                    {"name": "content_unique_pages", "retained_count": 17000},
                    {"name": "topic_relevant_pages", "retained_count": 1664},
                    {"name": "product_page_candidates", "retained_count": 313},
                    {
                        "name": "unique_valid_structured_records",
                        "retained_count": 222,
                    },
                ],
            }
        )
        chart = result["chart"]
        for token in (
            "#2e7d32",
            "#c62828",
            "筛选阶段",
            "筛选后保留 URL / 商品记录",
            "平均速度 3710.5 URL/s",
            "商品命中率 0.598302%",
            "raw_url_observations",
            "37105",
            "unique_valid_structured_records",
            "222",
        ):
            self.assertIn(token, chart)
        self.assertNotIn("<script", chart)
        self.assertNotIn("https://", chart)

    def test_funnel_labels_follow_their_actual_points(self):
        chart = run_cli(product_payload())["chart"]
        matches = re.findall(
            r'<circle cx="[^"]+" cy="([^"]+)"[^>]* />\n'
            r'  <title>([^:]+): \d+</title>\n'
            r'(?:  <line[^>]+data-label-connector[^>]+/>\n)?'
            r'  <text x="[^"]+" y="([^"]+)"',
            chart,
        )
        self.assertEqual(7, len(matches))
        self.assertEqual(7, chart.count("data-label-connector"))
        for point_y, stage, label_y in matches:
            with self.subTest(stage=stage):
                self.assertLessEqual(abs(float(point_y) - float(label_y)), 80)
                self.assertGreaterEqual(float(label_y), 82)
                self.assertLessEqual(float(label_y), 430)
        self.assertGreaterEqual(
            len({round(float(label_y), 1) for _, _, label_y in matches}),
            4,
        )

    def test_svg_is_well_formed_xml(self):
        chart = run_cli(product_payload())["chart"]
        root = ET.fromstring(chart)
        self.assertEqual("{http://www.w3.org/2000/svg}svg", root.tag)

    def test_funnel_rejects_increase_wrong_origin_and_wrong_terminal_stage(self):
        checkpoints = (point(0, 0, 0), point(10, 100, 60))
        invalid = (
            (
                FunnelStage("raw_url_observations", 100),
                FunnelStage("literal_unique_urls", 101),
                FunnelStage("unique_valid_structured_records", 10),
            ),
            (
                FunnelStage("raw_url_observations", 99),
                FunnelStage("unique_valid_structured_records", 10),
            ),
            (
                FunnelStage("raw_url_observations", 100),
                FunnelStage("product_page_candidates", 10),
            ),
        )
        for funnel in invalid:
            payload = {
                "checkpoints": [
                    {
                        "pure_discovery_seconds": p.pure_discovery_seconds,
                        "raw_url_observations": p.raw_url_observations,
                        "valid_url_observations": p.valid_url_observations,
                        "normalized_unique_urls": p.normalized_unique_urls,
                        "unique_objects": p.unique_objects,
                        "backend": p.backend,
                        "backend_kind": p.backend_kind,
                        "actual_in_flight": p.actual_in_flight,
                    }
                    for p in checkpoints
                ],
                "funnel": [
                    {"name": stage.name, "retained_count": stage.retained_count}
                    for stage in funnel
                ],
            }
            with self.subTest(funnel=funnel), self.assertRaises(ValueError):
                run_cli(payload)

    def test_active_time_uses_interval_union(self):
        self.assertEqual(
            active_discovery_seconds(((0.0, 4.0), (1.0, 3.0), (6.0, 8.5))),
            6.5,
        )

    def test_active_time_rejects_invalid_intervals(self):
        for intervals in (
            ((2.0, 1.0),),
            ((-1.0, 1.0),),
            ((0.0, float("inf")),),
        ):
            with self.subTest(intervals=intervals), self.assertRaises(ValueError):
                active_discovery_seconds(intervals)

    def test_checkpoint_rejects_invalid_counts_and_labels(self):
        with self.assertRaises(ValueError):
            point(1.0, 5, 6)
        with self.assertRaises(ValueError):
            point(-1.0, 5, 5)
        with self.assertRaises(ValueError):
            point(1.0, 5, 5, backend=" ")
        with self.assertRaises(ValueError):
            SearchCheckpoint(1.0, True, 1, 1, 1, "web", "search", 1)

    def test_series_rejects_time_or_count_regression(self):
        for series in (
            (point(0, 0, 0), point(2, 10, 8), point(1, 20, 15)),
            (point(0, 0, 0), point(2, 10, 8), point(3, 9, 8)),
            (point(0, 0, 0), point(2, 10, 8), point(3, 12, 7)),
        ):
            with self.subTest(series=series), self.assertRaises(ValueError):
                render_mermaid(series)

    def test_mermaid_uses_raw_url_series_and_pure_seconds(self):
        checkpoints = (
            point(0, 0, 0),
            point(2, 120, 100),
            point(5, 310, 220),
            point(10, 720, 410),
        )
        chart = render_mermaid(checkpoints)
        self.assertIn("xychart-beta", chart)
        self.assertIn('[0, 2, 5, 10]', chart)
        self.assertIn('line [0, 120, 310, 720]', chart)
        self.assertIn('y-axis "累计未去重 URL 数" 0 --> 720', chart)

    def test_cli_defaults_to_lightweight_high_contrast_svg(self):
        result = run_cli(
            {
                "checkpoints": [
                    {
                        "pure_discovery_seconds": 0,
                        "raw_url_observations": 0,
                        "valid_url_observations": 0,
                        "normalized_unique_urls": 0,
                        "unique_objects": 0,
                        "backend": "search",
                        "backend_kind": "search",
                        "actual_in_flight": 4,
                    },
                    {
                        "pure_discovery_seconds": 10,
                        "raw_url_observations": 720,
                        "valid_url_observations": 700,
                        "normalized_unique_urls": 410,
                        "unique_objects": 300,
                        "backend": "open-index",
                        "backend_kind": "open_index",
                        "actual_in_flight": 32,
                    },
                ]
            }
        )
        chart = result["chart"]
        self.assertEqual(result["format"], "svg")
        self.assertIn("<svg", chart)
        self.assertIn("搜索时间—累计未去重 URL", chart)
        self.assertIn("平均速度 72 URL/s", chart)
        self.assertIn('stroke-width="4"', chart)
        self.assertIn('stroke-width="2.5"', chart)
        self.assertIn("#c62828", chart)
        self.assertIn("#111111", chart)
        self.assertNotIn("<script", chart)
        without_svg_namespace = chart.replace(
            'xmlns="http://www.w3.org/2000/svg"', ""
        )
        self.assertNotIn("http://", without_svg_namespace)
        self.assertNotIn("https://", without_svg_namespace)

    def test_summary_keeps_all_rates_separate(self):
        summary = summarize_throughput(
            (point(0, 0, 0), point(10, 720, 410)),
            successful_page_bodies=12,
            page_read_seconds=6,
            unique_valid_structured_records=900,
            structured_request_seconds=3,
        )
        self.assertEqual(summary.raw_url_observations_per_second, 72.0)
        self.assertEqual(summary.url_discovery_per_second, 41.0)
        self.assertEqual(summary.successful_page_bodies_per_second, 2.0)
        self.assertEqual(summary.unique_valid_structured_records_per_second, 300.0)
        self.assertAlmostEqual(summary.duplicate_rate, 310 / 720)

    def test_unexecuted_channels_remain_none(self):
        summary = summarize_throughput((point(0, 0, 0), point(10, 100, 60)))
        self.assertIsNone(summary.successful_page_bodies_per_second)
        self.assertIsNone(summary.unique_valid_structured_records_per_second)

    def test_executed_zero_yield_channel_is_zero_and_zero_time_is_guarded(self):
        summary = summarize_throughput(
            (point(0, 0, 0), point(10, 100, 60)),
            successful_page_bodies=0,
            page_read_seconds=2,
        )
        self.assertEqual(summary.successful_page_bodies_per_second, 0.0)
        with self.assertRaises(ValueError):
            summarize_throughput(
                (point(0, 0, 0), point(10, 100, 60)),
                successful_page_bodies=1,
                page_read_seconds=0,
            )

    def test_ascii_contains_endpoints_and_height_variation(self):
        chart = render_ascii(
            (point(0, 0, 0), point(2, 120, 100), point(10, 720, 410))
        )
        self.assertIn("0s/0 URL", chart)
        self.assertIn("10s/720 URL", chart)
        self.assertGreaterEqual(len(set(chart) & set("▁▂▃▄▅▆▇█")), 2)

    def test_downsampling_preserves_ends_and_backend_transitions(self):
        checkpoints = tuple(
            point(
                float(index),
                index * 10,
                index * 8,
                backend="search" if index < 5 else "common-crawl",
                backend_kind="search" if index < 5 else "open_index",
            )
            for index in range(12)
        )
        sampled = downsample_checkpoints(checkpoints, limit=6)
        self.assertLessEqual(len(sampled), 6)
        self.assertEqual(sampled[0], checkpoints[0])
        self.assertEqual(sampled[-1], checkpoints[-1])
        self.assertIn(checkpoints[5], sampled)

    def test_more_backend_transitions_than_soft_limit_are_all_preserved(self):
        checkpoints = tuple(
            point(
                float(index),
                index * 10,
                index * 8,
                backend=f"backend-{index}",
                backend_kind="sitemap",
            )
            for index in range(30)
        )
        sampled = downsample_checkpoints(checkpoints, limit=24)
        self.assertEqual(sampled, checkpoints)

    def test_cli_reads_json_and_emits_chart_and_metrics(self):
        payload = {
            "checkpoints": [
                {
                    "pure_discovery_seconds": 0,
                    "raw_url_observations": 0,
                    "valid_url_observations": 0,
                    "normalized_unique_urls": 0,
                    "unique_objects": 0,
                    "backend": "search",
                    "backend_kind": "search",
                    "actual_in_flight": 4,
                },
                {
                    "pure_discovery_seconds": 10,
                    "raw_url_observations": 720,
                    "valid_url_observations": 700,
                    "normalized_unique_urls": 410,
                    "unique_objects": 300,
                    "backend": "open-index",
                    "backend_kind": "open_index",
                    "actual_in_flight": 32,
                },
            ],
            "format": "ascii",
        }
        script = Path(SKILL_ROOT) / "scripts" / "render_search_timeline.py"
        completed = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(script)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
            encoding="utf-8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["format"], "ascii")
        self.assertIn("10s/720 URL", result["chart"])
        self.assertEqual(
            result["metrics"]["raw_url_observations_per_second"],
            72.0,
        )


if __name__ == "__main__":
    unittest.main()
