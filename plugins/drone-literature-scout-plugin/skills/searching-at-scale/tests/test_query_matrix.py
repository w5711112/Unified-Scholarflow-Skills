from itertools import islice
from pathlib import Path
import json
import subprocess
import sys
import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.build_query_matrix import QueryDimensions, iter_query_matrix, query_batch


class QueryMatrixTests(unittest.TestCase):
    def test_query_batch_is_bounded_and_resumable(self):
        dims = QueryDimensions(
            topics=tuple(f"topic-{index}" for index in range(100)),
            locations=tuple(f"location-{index}" for index in range(100)),
            times=tuple(f"time-{index}" for index in range(100)),
        )
        first = query_batch(dims, offset=0, limit=8)
        second = query_batch(dims, offset=first.next_offset, limit=8)
        self.assertEqual(len(first.queries), 8)
        self.assertEqual(len(second.queries), 8)
        self.assertFalse(set(first.queries) & set(second.queries))
        self.assertFalse(first.exhausted)
        self.assertEqual(second.next_offset, 16)

    def test_query_batch_reports_exhaustion_without_restarting(self):
        dims = QueryDimensions(topics=("one", "two"))
        result = query_batch(dims, offset=1, limit=8)
        self.assertEqual(result.queries, ("two",))
        self.assertEqual(result.next_offset, 2)
        self.assertTrue(result.exhausted)

    def test_covers_all_dimensions_without_duplicates(self):
        dims = QueryDimensions(
            topics=("枕头",), aliases=("睡眠枕", "pillow"),
            locations=("中国", "广州"), times=("2026", "近期"),
            source_facets=("官网", "电商", "评测"), languages=("zh", "en"),
            qualifiers=("价格", "购买"), exclusions=("广告软文",),
        )
        queries = list(iter_query_matrix(dims))
        self.assertEqual(len(queries), len(set(queries)))
        self.assertTrue(any("pillow" in q and "en" in q for q in queries))
        self.assertTrue(any("广州" in q and "电商" in q for q in queries))
        self.assertTrue(all("-广告软文" in q for q in queries))

    def test_collapses_whitespace_collisions_and_includes_times_and_qualifiers(self):
        dims = QueryDimensions(
            topics=(" subject ", "subject"),
            locations=(" region ", "region"),
            times=("past", "current"),
            source_facets=("source",),
            languages=("en",),
            qualifiers=("price", "buy"),
            exclusions=("exclude",),
        )
        self.assertEqual(
            list(iter_query_matrix(dims)),
            [
                "subject region past source en price -exclude",
                "subject region past source en buy -exclude",
                "subject region current source en price -exclude",
                "subject region current source en buy -exclude",
            ],
        )

    def test_generator_is_lazy_for_a_large_universe_and_has_no_ten_thousand_cap(self):
        dims = QueryDimensions(
            topics=tuple(f"topic-{i}" for i in range(100)),
            aliases=tuple(f"alias-{i}" for i in range(100)),
            locations=tuple(f"location-{i}" for i in range(100)),
            times=tuple(f"time-{i}" for i in range(100)),
            source_facets=tuple(f"source-{i}" for i in range(100)),
        )
        self.assertEqual(
            list(islice(iter_query_matrix(dims), 3)),
            [
                "topic-0 location-0 time-0 source-0",
                "topic-0 location-0 time-0 source-1",
                "topic-0 location-0 time-0 source-2",
            ],
        )
        self.assertEqual(len(list(islice(iter_query_matrix(dims), 10_002))), 10_002)

    def test_cli_accepts_omitted_optional_dimensions(self):
        script = Path(__file__).parents[1] / "scripts" / "build_query_matrix.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            input='{"topics":["枕头"],"source_facets":["官网","电商"]}',
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [json.loads(line) for line in result.stdout.splitlines()],
            [{"query": "枕头 官网"}, {"query": "枕头 电商"}],
        )

    def test_cli_can_emit_one_resumable_window(self):
        script = Path(__file__).parents[1] / "scripts" / "build_query_matrix.py"
        result = subprocess.run(
            [sys.executable, str(script), "--offset", "1", "--limit", "1"],
            input='{"topics":["枕头"],"source_facets":["官网","电商","评测"]}',
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [json.loads(line) for line in result.stdout.splitlines()],
            [{"query": "枕头 电商"}],
        )
