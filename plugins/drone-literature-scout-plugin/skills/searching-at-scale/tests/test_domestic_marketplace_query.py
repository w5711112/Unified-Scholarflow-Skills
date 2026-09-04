from __future__ import annotations

from pathlib import Path
import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.domestic_marketplace_query import (
    DEFAULT_EDGE_USER_DATA_DIR,
    EDGE_PAYLOAD_KEYS,
    MarketplaceQueryDimensions,
    edge_pipe_name,
    edge_pipe_path,
    edge_task_batch,
    query_batch,
    query_total,
)


class DomesticMarketplaceQueryTests(unittest.TestCase):
    def test_million_scale_space_materializes_only_requested_window(self):
        dimensions = MarketplaceQueryDimensions(
            topic="手机壳",
            brands=tuple(f"品牌-{index}" for index in range(100)),
            specifications=tuple(f"规格-{index}" for index in range(100)),
            categories=tuple(f"分类-{index}" for index in range(10)),
            price_bands=tuple(f"价格-{index}" for index in range(10)),
        )

        self.assertGreaterEqual(query_total(dimensions, platforms=("jd",)), 1_000_000)
        first = query_batch(
            dimensions,
            offset=0,
            limit=16,
            platforms=("jd",),
        )
        resumed = query_batch(
            dimensions,
            offset=16,
            limit=16,
            platforms=("jd",),
        )

        self.assertEqual(len(first), 16)
        self.assertEqual(first[0].engines, ("360search", "baidu", "sogou", "quark"))
        self.assertIn("site:item.jd.com", first[0].query)
        self.assertNotIn("site:item.taobao.com", first[0].query)
        self.assertEqual(resumed[0].ordinal, 16)
        self.assertEqual(len({cursor.cursor_id for cursor in (*first, *resumed)}), 32)

    def test_taobao_uses_only_verified_product_hosts(self):
        dimensions = MarketplaceQueryDimensions(topic="手机壳")
        cursor = query_batch(
            dimensions,
            offset=0,
            limit=1,
            platforms=("taobao",),
        )[0]

        self.assertEqual(cursor.platform, "taobao")
        self.assertIn("site:item.taobao.com", cursor.query)
        self.assertIn("site:detail.tmall.com", cursor.query)
        self.assertNotIn("s.taobao.com", cursor.query)

    def test_offsets_stop_exactly_at_deterministic_total(self):
        dimensions = MarketplaceQueryDimensions(
            topic="手机壳",
            brands=("A", "B"),
        )
        total = query_total(dimensions, platforms=("jd", "taobao"))
        last = query_batch(
            dimensions,
            offset=total - 1,
            limit=16,
            platforms=("jd", "taobao"),
        )
        exhausted = query_batch(
            dimensions,
            offset=total,
            limit=16,
            platforms=("jd", "taobao"),
        )

        self.assertEqual(len(last), 1)
        self.assertEqual(last[0].ordinal, total - 1)
        self.assertEqual(exhausted, ())

    def test_edge_tasks_use_plain_queries_and_fixed_envelopes(self):
        dimensions = MarketplaceQueryDimensions(
            topic="手机壳",
            brands=("倍思",),
            specifications=("透明",),
        )

        tasks = edge_task_batch(
            dimensions,
            offset=0,
            limit=2,
            platforms=("jd", "taobao"),
        )

        self.assertEqual(len(tasks), 2)
        self.assertEqual({task["adapter"] for task in tasks}, {"edge_marketplace"})
        self.assertEqual(
            {task["backend"] for task in tasks}, {"edge:jd", "edge:taobao"}
        )
        for task in tasks:
            payload = task["payload"]
            self.assertEqual(set(payload), EDGE_PAYLOAD_KEYS)
            self.assertNotIn("site:", payload["query"])
            self.assertIn("手机壳", payload["query"])
            self.assertIn("倍思", payload["query"])
            self.assertIn("透明", payload["query"])
            profile = Path(payload["user_data_dir"])
            self.assertTrue(profile.is_absolute())
            self.assertEqual(
                profile.parts[-3:],
                (".codex-runtime", "searching-at-scale", "edge-profile"),
            )
            self.assertEqual(task["concurrency"], {
                "tier": 1,
                "tool_limit": 1,
                "host_limit": 1,
            })
            self.assertNotIn("source_url", repr(task).casefold())

    def test_edge_task_batch_accepts_user_data_dir_override(self):
        profile = "C:/Profiles/search/edge-profile"
        tasks = edge_task_batch(
            MarketplaceQueryDimensions(topic="手机壳"),
            offset=0,
            limit=1,
            platforms=("jd",),
            user_data_dir=profile,
        )
        self.assertEqual(tasks[0]["payload"]["user_data_dir"], profile)

    def test_edge_task_batch_is_lazy_bounded_and_preserves_offsets(self):
        dimensions = MarketplaceQueryDimensions(
            topic="手机壳",
            brands=tuple(f"品牌-{index}" for index in range(100)),
        )

        first = edge_task_batch(
            dimensions, offset=0, limit=16, platforms=("jd",)
        )
        resumed = edge_task_batch(
            dimensions, offset=16, limit=16, platforms=("jd",)
        )

        self.assertEqual(len(first), 16)
        self.assertEqual(resumed[0]["payload"]["cursor"]["ordinal"], 16)
        self.assertEqual(
            len({task["task_id"] for task in (*first, *resumed)}), 32
        )
        with self.assertRaisesRegex(ValueError, "1 to 64"):
            edge_task_batch(
                dimensions, offset=0, limit=65, platforms=("jd",)
            )

    def test_edge_task_batch_expands_numeric_pages_with_one_logical_cursor(self):
        tasks = edge_task_batch(
            MarketplaceQueryDimensions(topic="枕头"),
            offset=0,
            limit=1,
            platforms=("jd",),
            page_numbers=(1, 2, 3),
            pagination_enabled=True,
        )

        self.assertEqual(
            [task["payload"]["cursor"]["page_number"] for task in tasks],
            [1, 2, 3],
        )
        self.assertEqual(
            [task["payload"]["session_action"] for task in tasks],
            ["start", "next", "next"],
        )
        self.assertEqual(
            len({task["payload"]["cursor"]["cursor_id"] for task in tasks}), 1
        )
        self.assertEqual(len({task["task_id"] for task in tasks}), 3)

        boundary = edge_task_batch(
            MarketplaceQueryDimensions(topic="枕头"),
            offset=0,
            limit=1,
            platforms=("jd",),
            page_numbers=(512,),
            pagination_enabled=True,
        )
        self.assertEqual(boundary[0]["payload"]["cursor"]["page_number"], 512)
        self.assertEqual(boundary[0]["payload"]["session_action"], "next")

        with self.assertRaisesRegex(ValueError, "1 to 512"):
            edge_task_batch(
                MarketplaceQueryDimensions(topic="枕头"),
                offset=0,
                limit=1,
                platforms=("jd",),
                page_numbers=(1, 513),
                pagination_enabled=True,
            )

    def test_edge_pipe_name_keeps_default_pipe_only_for_unspecified_profile(self):
        self.assertIsNone(edge_pipe_name(None))
        self.assertIsNone(edge_pipe_path(None))

    def test_edge_pipe_name_is_per_profile_deterministic(self):
        profile = DEFAULT_EDGE_USER_DATA_DIR.replace(
            "edge-profile", "profile-b/edge-profile"
        )
        first = edge_pipe_name(profile)
        self.assertIsNotNone(first)
        self.assertTrue(first.startswith("codex.searching_at_scale."))
        self.assertEqual(edge_pipe_name(profile), first)
        self.assertNotEqual(edge_pipe_name(profile), edge_pipe_name(DEFAULT_EDGE_USER_DATA_DIR))
        self.assertEqual(
            edge_pipe_path(profile),
            rf"\\.\pipe\{first}",
        )


if __name__ == "__main__":
    unittest.main()
