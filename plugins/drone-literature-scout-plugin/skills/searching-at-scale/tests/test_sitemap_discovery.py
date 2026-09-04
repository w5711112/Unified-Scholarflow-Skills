"""Contract tests for sitemap parsing, recursive discovery, and readiness."""

import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tracemalloc
import unittest
from unittest.mock import patch

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.discover_sitemaps import (
    DiscoveryConfig,
    FetchOutcome,
    classify_bulk_readiness,
    decode_sitemap_payload,
    fetch_url,
    iter_backend_events,
    iter_discovery_events,
    parse_sitemap_xml,
)


INDEX_WITH_PRODUCT_AND_PAGE_SHARDS = b"""<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://shop.example/sitemap_pages_1.xml</loc></sitemap>
  <sitemap><loc>https://shop.example/sitemap_products_1.xml</loc></sitemap>
</sitemapindex>"""

PRODUCT_URLSET = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://shop.example/products/soft-pillow</loc></url>
</urlset>"""

PRODUCT_WITH_MEDIA_URLSET = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
    xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
  <url>
    <loc>https://shop.example/products/soft-pillow</loc>
    <image:image><image:loc>https://cdn.example/soft-pillow.jpg</image:loc></image:image>
  </url>
</urlset>"""

PAGE_URLSET = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://shop.example/pages/about</loc></url>
</urlset>"""


def ok(url, payload, content_type="application/xml", elapsed_seconds=0.01):
    return FetchOutcome(
        url=url,
        status=200,
        content_type=content_type,
        content_encoding="",
        payload=payload,
        elapsed_seconds=elapsed_seconds,
        error_category=None,
    )


def fake_fetcher(responses):
    def fetch(url, *, timeout_seconds, max_document_bytes):
        del timeout_seconds, max_document_bytes
        return responses.get(
            url,
            FetchOutcome(
                url=url,
                status=404,
                content_type="text/plain",
                content_encoding="",
                payload=b"",
                elapsed_seconds=0.01,
                error_category="not_found",
            ),
        )

    return fetch


class SitemapDiscoveryTests(unittest.TestCase):
    def test_backend_adapter_emits_only_normalized_urls_and_one_summary(self):
        sitemap_url = "https://shop.example/sitemap.xml"
        events = list(
            iter_backend_events(
                {
                    "explicit_sitemaps": [sitemap_url],
                    "scope_mode": "site",
                    "query_family": "site-catalog",
                },
                fetcher=fake_fetcher(
                    {sitemap_url: ok(sitemap_url, PRODUCT_WITH_MEDIA_URLSET)}
                ),
            )
        )
        self.assertEqual([event["type"] for event in events], ["url", "url", "summary"])
        self.assertEqual(events[0]["channels"], ["sitemap"])
        self.assertEqual(events[0]["source_class"], "sitemap")
        self.assertEqual(events[0]["query_family"], "site-catalog")
        self.assertNotIn("body", json.dumps(events).casefold())
        self.assertEqual(events[-1]["telemetry"]["raw_url_observations"], 2)
        self.assertEqual(events[-1]["round"]["new_entities"], 1)

    def test_sitemap_index_returns_only_child_sitemap_urls(self):
        """Treating an index as page content would send sitemap files to the crawler."""
        payload = b"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
        <sitemapindex xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">
          <sitemap><loc>https://example.com/sitemaps/one.xml</loc></sitemap>
          <sitemap><loc>https://example.com/sitemaps/two.xml</loc></sitemap>
          <sitemap><loc>ftp://example.com/sitemaps/ignored.xml</loc></sitemap>
        </sitemapindex>"""

        parsed = parse_sitemap_xml(payload, source_url="https://example.com/sitemap.xml")

        self.assertEqual(parsed.kind, "index")
        self.assertEqual(
            parsed.child_sitemaps,
            ("https://example.com/sitemaps/one.xml", "https://example.com/sitemaps/two.xml"),
        )
        self.assertEqual(parsed.primary_urls, ())
        self.assertEqual(parsed.media_urls, ())

    def test_urlset_separates_immediate_page_loc_from_nested_media_locs(self):
        """Classifying the first child as primary breaks when media precedes the page URL."""
        payload = b"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
        <urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\"
            xmlns:image=\"http://www.google.com/schemas/sitemap-image/1.1\"
            xmlns:video=\"http://www.google.com/schemas/sitemap-video/1.1\"
            xmlns:news=\"http://www.google.com/schemas/sitemap-news/0.9\">
          <url>
            <image:image><image:loc>https://cdn.example.com/hero.jpg</image:loc></image:image>
            <loc>https://example.com/articles/one</loc>
            <video:video><video:loc>https://cdn.example.com/clip.mp4</video:loc></video:video>
            <news:news><news:loc>https://example.com/news-feed</news:loc></news:news>
          </url>
        </urlset>"""

        parsed = parse_sitemap_xml(payload, source_url="https://example.com/sitemap.xml")

        self.assertEqual(parsed.kind, "urlset")
        self.assertEqual(parsed.child_sitemaps, ())
        self.assertEqual(parsed.primary_urls, ("https://example.com/articles/one",))
        self.assertEqual(
            parsed.media_urls,
            (
                "https://cdn.example.com/hero.jpg",
                "https://cdn.example.com/clip.mp4",
                "https://example.com/news-feed",
            ),
        )

    def test_gzip_payload_decodes_from_header_or_gz_source_suffix(self):
        """Ignoring either gzip signal leaves valid sitemap payloads unreadable."""
        compressed = gzip.compress(b"<urlset />")

        from_header = decode_sitemap_payload(
            compressed,
            content_encoding="gzip",
            source_url="https://example.com/sitemap.xml",
        )
        from_suffix = decode_sitemap_payload(
            compressed,
            content_encoding="",
            source_url="https://example.com/sitemap.xml.gz",
        )

        self.assertEqual(from_header, b"<urlset />")
        self.assertEqual(from_suffix, b"<urlset />")

    def test_gzip_expansion_stops_after_one_byte_beyond_document_limit(self):
        """Checking size after gzip.decompress permits an unbounded allocation."""
        compressed = gzip.compress(b"x" * (4 * 1024 * 1024))

        tracemalloc.start()
        try:
            with self.assertRaisesRegex(ValueError, "document_too_large"):
                decode_sitemap_payload(
                    compressed,
                    content_encoding="gzip",
                    source_url="https://example.com/sitemap.xml.gz",
                    max_document_bytes=8192,
                )
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        self.assertLess(peak_bytes, 1024 * 1024)

    def test_nonpositive_document_limit_is_rejected_before_public_entry_io(self):
        """A nonpositive limit must never become read(-1) at any public entry."""
        compressed = gzip.compress(b"x" * (4 * 1024 * 1024))
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "discover_sitemaps.py"
        )

        def unexpected_fetch(url, *, timeout_seconds, max_document_bytes):
            del url, timeout_seconds, max_document_bytes
            self.fail("invalid DiscoveryConfig reached the injected fetcher")

        for invalid_limit in (0, -2):
            with self.subTest(entry="DiscoveryConfig/iter", limit=invalid_limit):
                with self.assertRaisesRegex(
                    ValueError, "max_document_bytes must be greater than zero"
                ):
                    config = DiscoveryConfig(
                        explicit_sitemaps=("https://example.com/sitemap.xml",),
                        max_document_bytes=invalid_limit,
                    )
                    list(
                        iter_discovery_events(
                            config,
                            fetcher=unexpected_fetch,
                        )
                    )

            with self.subTest(entry="fetch_url", limit=invalid_limit):
                with patch(
                    "scripts.discover_sitemaps.build_opener",
                    side_effect=AssertionError("invalid limit reached opener"),
                ):
                    with self.assertRaisesRegex(
                        ValueError, "max_document_bytes must be greater than zero"
                    ):
                        fetch_url(
                            "https://example.com/sitemap.xml",
                            max_document_bytes=invalid_limit,
                        )

            with self.subTest(entry="decode", limit=invalid_limit):
                tracemalloc.start()
                try:
                    with self.assertRaises(ValueError) as raised:
                        decode_sitemap_payload(
                            compressed,
                            content_encoding="gzip",
                            source_url="https://example.com/sitemap.xml.gz",
                            max_document_bytes=invalid_limit,
                        )
                    _, peak_bytes = tracemalloc.get_traced_memory()
                finally:
                    tracemalloc.stop()
                self.assertEqual(
                    str(raised.exception),
                    "max_document_bytes must be greater than zero",
                )
                self.assertLess(peak_bytes, 1024 * 1024)

            with self.subTest(entry="CLI", limit=invalid_limit):
                completed = subprocess.run(
                    [sys.executable, "-X", "utf8", str(script)],
                    input=json.dumps({"max_document_bytes": invalid_limit}),
                    text=True,
                    encoding="utf-8",
                    capture_output=True,
                    check=False,
                    env={
                        **os.environ,
                        "PYTHONUTF8": "1",
                        "PYTHONIOENCODING": "utf-8",
                        "PYTHONDONTWRITEBYTECODE": "1",
                    },
                )
                self.assertNotEqual(completed.returncode, 0)
                self.assertEqual(completed.stdout, "")
                self.assertIn(
                    "max_document_bytes must be greater than zero",
                    completed.stderr,
                )

    def test_robots_product_shard_is_followed_before_page_shard(self):
        """FIFO recursion would visit the page shard before the higher-value product shard."""
        responses = {
            "https://shop.example/robots.txt": ok(
                "https://shop.example/robots.txt",
                b"Sitemap: https://shop.example/sitemap.xml\n",
                "text/plain",
            ),
            "https://shop.example/sitemap.xml": ok(
                "https://shop.example/sitemap.xml",
                INDEX_WITH_PRODUCT_AND_PAGE_SHARDS,
            ),
            "https://shop.example/sitemap_products_1.xml": ok(
                "https://shop.example/sitemap_products_1.xml", PRODUCT_URLSET
            ),
            "https://shop.example/sitemap_pages_1.xml": ok(
                "https://shop.example/sitemap_pages_1.xml", PAGE_URLSET
            ),
        }

        events = list(
            iter_discovery_events(
                DiscoveryConfig(seeds=("https://shop.example",), scope_mode="market"),
                fetcher=fake_fetcher(responses),
            )
        )
        sitemap_urls = [
            event["url"] for event in events if event["type"] == "sitemap"
        ]

        self.assertEqual(
            sitemap_urls[:3],
            [
                "https://shop.example/sitemap.xml",
                "https://shop.example/sitemap_products_1.xml",
                "https://shop.example/sitemap_pages_1.xml",
            ],
        )

    def test_sitemap_cycles_are_visited_once(self):
        """Lacking normalized cycle detection recursively refetches the same indexes."""
        first_index = b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://shop.example/b.xml</loc></sitemap>
        </sitemapindex>"""
        second_index = b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>HTTPS://SHOP.EXAMPLE/a.xml#again</loc></sitemap>
        </sitemapindex>"""
        responses = {
            "https://shop.example/robots.txt": ok(
                "https://shop.example/robots.txt",
                b"Sitemap: https://shop.example/a.xml\n",
                "text/plain",
            ),
            "https://shop.example/a.xml": ok(
                "https://shop.example/a.xml", first_index
            ),
            "https://shop.example/b.xml": ok(
                "https://shop.example/b.xml", second_index
            ),
        }

        events = list(
            iter_discovery_events(
                DiscoveryConfig(seeds=("https://shop.example",)),
                fetcher=fake_fetcher(responses),
            )
        )

        self.assertEqual(
            [
                "https://shop.example/a.xml",
                "https://shop.example/b.xml",
            ],
            [event["url"] for event in events if event["type"] == "sitemap"],
        )

    def test_cycle_closing_edge_at_depth_boundary_uses_in_progress_state(self):
        """A known cycle edge beyond max depth is not a new over-depth document."""
        origin = "https://shop.example"
        responses = {
            f"{origin}/robots.txt": ok(
                f"{origin}/robots.txt",
                f"Sitemap: {origin}/a.xml\n".encode("utf-8"),
                "text/plain",
            ),
            f"{origin}/a.xml": ok(
                f"{origin}/a.xml",
                f"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <sitemap><loc>{origin}/b.xml</loc></sitemap>
                </sitemapindex>""".encode("utf-8"),
            ),
            f"{origin}/b.xml": ok(
                f"{origin}/b.xml",
                f"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <sitemap><loc>{origin}/a.xml</loc></sitemap>
                </sitemapindex>""".encode("utf-8"),
            ),
        }

        events = list(
            iter_discovery_events(
                DiscoveryConfig(seeds=(origin,), max_depth=1),
                fetcher=fake_fetcher(responses),
            )
        )
        summary = events[-1]

        self.assertEqual(
            len([event for event in events if event["type"] == "sitemap"]),
            2,
        )
        self.assertEqual(
            len(
                [
                    event
                    for event in events
                    if event["type"] == "error"
                    and event["error_category"] == "max_depth_exceeded"
                ]
            ),
            0,
        )
        self.assertEqual(summary["exhaustive_seed_count"], 1)

    def test_corrupt_gzip_emits_invalid_xml_and_one_terminal_summary(self):
        """An uncaught deflate error truncates the event stream before its summary."""
        sitemap_url = "https://shop.example/corrupt.xml.gz"
        corrupt_gzip = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xffgarbage"
        responses = {
            sitemap_url: FetchOutcome(
                url=sitemap_url,
                status=200,
                content_type="application/xml",
                content_encoding="gzip",
                payload=corrupt_gzip,
                elapsed_seconds=0.01,
                error_category=None,
            )
        }

        events = list(
            iter_discovery_events(
                DiscoveryConfig(explicit_sitemaps=(sitemap_url,)),
                fetcher=fake_fetcher(responses),
            )
        )

        invalid_xml = [
            event
            for event in events
            if event["type"] == "error"
            and event["error_category"] == "invalid_xml"
        ]
        self.assertEqual(len(invalid_xml), 1)
        self.assertEqual(len([event for event in events if event["type"] == "summary"]), 1)
        self.assertEqual(events[-1]["type"], "summary")

    def test_failed_descendants_do_not_certify_exhaustive_seeds(self):
        """Parsing root indexes alone must not satisfy the two-seed readiness branch."""
        first_origin = "https://one.example"
        second_origin = "https://two.example"
        responses = {
            f"{first_origin}/robots.txt": ok(
                f"{first_origin}/robots.txt",
                f"Sitemap: {first_origin}/sitemap.xml\n".encode("utf-8"),
                "text/plain",
            ),
            f"{second_origin}/robots.txt": ok(
                f"{second_origin}/robots.txt",
                f"Sitemap: {second_origin}/sitemap.xml\n".encode("utf-8"),
                "text/plain",
            ),
            f"{first_origin}/sitemap.xml": ok(
                f"{first_origin}/sitemap.xml",
                f"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <sitemap><loc>{first_origin}/missing-child.xml</loc></sitemap>
                </sitemapindex>""".encode("utf-8"),
            ),
            f"{second_origin}/sitemap.xml": ok(
                f"{second_origin}/sitemap.xml",
                f"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <sitemap><loc>{second_origin}/missing-child.xml</loc></sitemap>
                </sitemapindex>""".encode("utf-8"),
            ),
        }

        summary = list(
            iter_discovery_events(
                DiscoveryConfig(seeds=(first_origin, second_origin)),
                fetcher=fake_fetcher(responses),
            )
        )[-1]

        self.assertEqual(summary["valid_sitemaps"], 2)
        self.assertEqual(summary["exhaustive_seed_count"], 0)
        self.assertEqual(summary["bulk_readiness_state"], "bulk_degraded")

    def test_duplicate_root_candidate_merges_all_seed_origins(self):
        """First-seen deduplication must retain provenance from later seeds."""
        shared_sitemap = "https://shared.example/sitemap.xml"
        responses = {
            "https://one.example/robots.txt": ok(
                "https://one.example/robots.txt",
                f"Sitemap: {shared_sitemap}\n".encode("utf-8"),
                "text/plain",
            ),
            "https://two.example/robots.txt": ok(
                "https://two.example/robots.txt",
                f"Sitemap: {shared_sitemap}\n".encode("utf-8"),
                "text/plain",
            ),
            shared_sitemap: ok(
                shared_sitemap,
                b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://shared.example/item/sku-1</loc></url>
                </urlset>""",
            ),
        }

        summary = list(
            iter_discovery_events(
                DiscoveryConfig(
                    seeds=("https://one.example", "https://two.example")
                ),
                fetcher=fake_fetcher(responses),
            )
        )[-1]

        self.assertEqual(summary["primary_urls"], 1)
        self.assertEqual(summary["exhaustive_seed_count"], 2)
        self.assertEqual(summary["bulk_readiness_state"], "bulk_ready")

    def test_two_exhaustive_empty_seed_roots_are_degraded(self):
        """Exhaustive seed count without positive primary coverage cannot be ready."""
        empty_urlset = (
            b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" />'
        )
        responses = {
            "https://one.example/robots.txt": ok(
                "https://one.example/robots.txt",
                b"Sitemap: https://one.example/sitemap.xml\n",
                "text/plain",
            ),
            "https://two.example/robots.txt": ok(
                "https://two.example/robots.txt",
                b"Sitemap: https://two.example/sitemap.xml\n",
                "text/plain",
            ),
            "https://one.example/sitemap.xml": ok(
                "https://one.example/sitemap.xml", empty_urlset
            ),
            "https://two.example/sitemap.xml": ok(
                "https://two.example/sitemap.xml", empty_urlset
            ),
        }

        summary = list(
            iter_discovery_events(
                DiscoveryConfig(
                    seeds=("https://one.example", "https://two.example")
                ),
                fetcher=fake_fetcher(responses),
            )
        )[-1]

        self.assertEqual(summary["valid_sitemaps"], 2)
        self.assertEqual(summary["primary_urls"], 0)
        self.assertEqual(summary["exhaustive_seed_count"], 2)
        self.assertEqual(summary["bulk_readiness_state"], "bulk_degraded")

    def test_product_sitemap_path_token_is_candidate_evidence(self):
        """Ignoring product-shard identity loses products on nonstandard page paths."""
        product_sitemap = "https://shop.example/sitemap_products_1.xml"
        nonproduct_sitemap = "https://shop.example/sitemap_nonproduct_1.xml"
        responses = {
            product_sitemap: ok(
                product_sitemap,
                b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://shop.example/item/sku-1</loc></url>
                </urlset>""",
            ),
            nonproduct_sitemap: ok(
                nonproduct_sitemap,
                b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://shop.example/item/sku-2</loc></url>
                </urlset>""",
            ),
        }

        events = list(
            iter_discovery_events(
                DiscoveryConfig(
                    explicit_sitemaps=(product_sitemap, nonproduct_sitemap)
                ),
                fetcher=fake_fetcher(responses),
            )
        )
        by_url = {
            event["url"]: event for event in events if event["type"] == "url"
        }

        self.assertTrue(
            by_url["https://shop.example/item/sku-1"]["product_page_candidate"]
        )
        self.assertEqual(
            by_url["https://shop.example/item/sku-1"][
                "product_candidate_evidence"
            ],
            ["sitemap_product_shard"],
        )
        self.assertFalse(
            by_url["https://shop.example/item/sku-2"]["product_page_candidate"]
        )
        self.assertEqual(
            by_url["https://shop.example/item/sku-2"][
                "product_candidate_evidence"
            ],
            [],
        )
        self.assertEqual(events[-1]["product_page_candidates"], 1)

    def test_over_depth_visit_does_not_block_later_shallow_root(self):
        """A deep rejected occurrence must not poison the normalized visited set."""
        origin = "https://shop.example"
        root_url = f"{origin}/sitemap.xml"
        first_index = b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://shop.example/b.xml</loc></sitemap>
        </sitemapindex>"""
        second_index = b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>https://shop.example/sitemap.xml</loc></sitemap>
        </sitemapindex>"""
        responses = {
            f"{origin}/robots.txt": ok(
                f"{origin}/robots.txt",
                f"Sitemap: {origin}/a.xml\n".encode("utf-8"),
                "text/plain",
            ),
            f"{origin}/a.xml": ok(f"{origin}/a.xml", first_index),
            f"{origin}/b.xml": ok(f"{origin}/b.xml", second_index),
            root_url: ok(root_url, PRODUCT_URLSET),
        }

        events = list(
            iter_discovery_events(
                DiscoveryConfig(seeds=(origin,), max_depth=1),
                fetcher=fake_fetcher(responses),
            )
        )
        summary = events[-1]

        self.assertEqual(summary["primary_urls"], 1)
        self.assertEqual(summary["exhaustive_seed_count"], 1)
        self.assertEqual(
            len(
                [
                    event
                    for event in events
                    if event["type"] == "error"
                    and event["error_category"] == "max_depth_exceeded"
                ]
            ),
            1,
        )

    def test_media_counts_as_raw_but_not_primary_or_product(self):
        """Folding nested media locs into pages inflates primary and product counts."""
        urlset = b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
            xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
          <url>
            <loc>https://shop.example/products/soft-pillow</loc>
            <image:image><image:loc>https://cdn.example/soft-pillow.jpg</image:loc></image:image>
          </url>
        </urlset>"""
        responses = {
            "https://shop.example/sitemap.xml": ok(
                "https://shop.example/sitemap.xml", urlset
            )
        }

        events = list(
            iter_discovery_events(
                DiscoveryConfig(
                    explicit_sitemaps=("https://shop.example/sitemap.xml",),
                    scope_mode="site",
                ),
                fetcher=fake_fetcher(responses),
            )
        )
        summary = events[-1]
        url_events = [event for event in events if event["type"] == "url"]

        self.assertEqual(summary["raw_url_observations"], 2)
        self.assertEqual(summary["primary_urls"], 1)
        self.assertEqual(summary["media_url_observations"], 1)
        self.assertEqual(summary["product_page_candidates"], 1)
        self.assertEqual(
            {event["url_kind"] for event in url_events}, {"primary", "media"}
        )
        self.assertTrue(
            all(event.get("discovery_channel") == "sitemap" for event in url_events)
        )

    def test_market_scope_below_target_is_degraded(self):
        """A small slow market sitemap must not be reported as bulk-ready."""
        self.assertEqual(
            classify_bulk_readiness(
                {
                    "scope_mode": "market",
                    "valid_sitemaps": 1,
                    "primary_urls": 10,
                    "raw_url_observations_per_second": 12.0,
                    "exhaustive_seed_count": 1,
                }
            ),
            "bulk_degraded",
        )

    def test_all_failed_bulk_routes_are_unavailable(self):
        """No valid sitemap means there is no bulk route to degrade gracefully."""
        self.assertEqual(
            classify_bulk_readiness(
                {
                    "scope_mode": "market",
                    "valid_sitemaps": 0,
                    "primary_urls": 0,
                    "raw_url_observations_per_second": 0.0,
                    "exhaustive_seed_count": 0,
                }
            ),
            "bulk_unavailable",
        )

    def test_ranked_search_cannot_mark_bulk_ready(self):
        """High ranked-search throughput still cannot satisfy the sitemap bulk gate."""
        self.assertEqual(
            classify_bulk_readiness(
                {
                    "scope_mode": "market",
                    "valid_sitemaps": 5,
                    "primary_urls": 500,
                    "raw_url_observations_per_second": 100.0,
                    "exhaustive_seed_count": 3,
                    "source_kind": "search",
                }
            ),
            "bulk_unavailable",
        )

    def test_cli_streams_json_events_and_terminal_summary_from_fixture(self):
        """Buffering a non-JSON report would break streaming CLI consumers."""
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "discover_sitemaps.py"
        )
        payload = {
            "seeds": [],
            "explicit_sitemaps": ["https://shop.example/sitemap.xml"],
            "scope_mode": "site",
            "timeout_seconds": 15.0,
            "max_document_bytes": 16777216,
            "max_depth": 8,
            "product_path_hints": ["/products/"],
            "fixture_fetches": {
                "https://shop.example/sitemap.xml": {
                    "status": 200,
                    "content_type": "application/xml",
                    "content_encoding": "",
                    "payload": PRODUCT_WITH_MEDIA_URLSET.decode("utf-8"),
                    "elapsed_seconds": 0.01,
                    "error_category": None,
                }
            },
        }

        completed = subprocess.run(
            [sys.executable, "-X", "utf8", str(script)],
            input=json.dumps(payload),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            },
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = completed.stdout.splitlines()
        events = [json.loads(line) for line in lines]
        url_events = [event for event in events if event["type"] == "url"]
        self.assertGreaterEqual(len(events), 3)
        self.assertEqual(events[0]["type"], "backend")
        self.assertEqual(events[-1]["type"], "summary")
        self.assertEqual(events[-1]["bulk_readiness_state"], "bulk_ready")
        self.assertEqual(
            {event["url_kind"] for event in url_events}, {"primary", "media"}
        )
        self.assertTrue(
            all(event.get("discovery_channel") == "sitemap" for event in url_events)
        )


if __name__ == "__main__":
    unittest.main()
