from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.common_crawl_query import iter_backend_events
from scripts.runtime_manager import RuntimeManager
from scripts.searxng_query import iter_searxng_events


LIVE_COMMON_CRAWL = os.environ.get("SEARCHING_AT_SCALE_LIVE_COMMON_CRAWL") == "1"
LIVE_SEARXNG = os.environ.get("SEARCHING_AT_SCALE_LIVE_SEARXNG") == "1"


class LiveAdapterTests(unittest.TestCase):
    @unittest.skipUnless(LIVE_COMMON_CRAWL, "live Common Crawl smoke disabled")
    def test_common_crawl_returns_real_metadata_only_urls(self):
        events = list(
            iter_backend_events(
                {
                    "scope": "domain",
                    "value": "example.com",
                    "workers": 1,
                    "max_pages": 1,
                    "timeout_seconds": 30.0,
                    "query_family": "live-python-docs",
                }
            )
        )
        self.assertEqual(events[-1]["type"], "summary")
        urls = [event for event in events if event.get("type") == "url"]
        self.assertGreater(len(urls), 0)
        self.assertTrue(
            all(
                event["metadata"].get("source_role") == "historical_index"
                for event in urls
            )
        )
        self.assertNotIn("body", repr(events).casefold())

    @unittest.skipUnless(LIVE_SEARXNG, "live SearXNG smoke disabled")
    def test_managed_searxng_searches_and_leaves_no_task_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = RuntimeManager(run_id="live-smoke", temp_parent=tmp)
            owned = manager.task_temp_dir
            unavailable_reason = None
            with manager.searxng() as managed:
                if not managed.available:
                    unavailable_reason = managed.reason
                else:
                    events = list(
                        iter_searxng_events(
                            {
                                "query": "Python documentation",
                                "query_family": "live-searxng",
                                "language": "en",
                                "pageno": 1,
                                "timeout_seconds": 30.0,
                            },
                            base_url=str(managed.base_url),
                        )
                    )
                    self.assertEqual(events[-1]["type"], "summary")
                    self.assertGreater(
                        events[-1]["telemetry"]["successful_pages"], 0
                    )
            self.assertFalse(Path(owned).exists())
            cleanup = manager.cleanup()
            self.assertTrue(cleanup.container_absent)
            self.assertTrue(cleanup.temp_dir_removed)
            if unavailable_reason in {"docker_unavailable", "image_unavailable"}:
                self.skipTest(f"optional SearXNG runtime: {unavailable_reason}")
            if unavailable_reason is not None:
                self.fail(f"managed SearXNG unavailable: {unavailable_reason}")


if __name__ == "__main__":
    unittest.main()
