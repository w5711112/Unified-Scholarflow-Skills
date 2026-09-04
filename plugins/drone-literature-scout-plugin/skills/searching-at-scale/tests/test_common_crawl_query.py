from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit
import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.backend_runner import AdapterFailure
from scripts.common_crawl_query import (
    COLLECTIONS_URL,
    CommonCrawlRequest,
    build_query_url,
    iter_backend_events,
)


COLLECTIONS = [
    {
        "id": "CC-MAIN-2026-30",
        "name": "July 2026 Index",
        "cdx-api": "https://index.commoncrawl.org/CC-MAIN-2026-30-index",
    },
    {
        "id": "CC-MAIN-2026-26",
        "name": "June 2026 Index",
        "cdx-api": "https://index.commoncrawl.org/CC-MAIN-2026-26-index",
    },
]


PAGE_ZERO = [
    {
        "url": "https://example.com/products/1",
        "timestamp": "20260701010101",
        "status": "200",
        "mime": "text/html",
        "filename": "crawl-data/CC-MAIN-2026-30/segments/a.warc.gz",
        "offset": "100",
        "length": "50",
    }
]


class FixtureFetcher:
    def __init__(self, *, pages: int = 1):
        self.pages = pages
        self.urls: list[str] = []

    def __call__(self, url: str, *, timeout_seconds: float) -> bytes:
        del timeout_seconds
        self.urls.append(url)
        if url == COLLECTIONS_URL:
            return json.dumps(COLLECTIONS).encode("utf-8")
        query = parse_qs(urlsplit(url).query)
        if query.get("showNumPages") == ["true"]:
            return json.dumps({"pages": self.pages}).encode("utf-8")
        page = int(query["page"][0])
        record = {
            **PAGE_ZERO[0],
            "url": f"https://example.com/products/{page + 1}",
        }
        return (json.dumps(record) + "\n").encode("utf-8")


class ExactFixtureFetcher:
    def __init__(self):
        self.urls: list[str] = []

    def __call__(self, url: str, *, timeout_seconds: float) -> bytes:
        del timeout_seconds
        self.urls.append(url)
        if url == COLLECTIONS_URL:
            return json.dumps(COLLECTIONS).encode("utf-8")
        query = parse_qs(urlsplit(url).query)
        if "showNumPages" in query or "page" in query:
            raise AssertionError("exact lookup must not paginate")
        record = {
            **PAGE_ZERO[0],
            "url": "https://example.com/",
        }
        return (json.dumps(record) + "\n").encode("utf-8")


class CommonCrawlQueryTests(unittest.TestCase):
    def test_bulk_scope_never_calls_cdx_show_num_pages(self):
        cdx_calls = []
        bulk_payloads = []

        def fail_cdx(url, *, timeout_seconds):
            del timeout_seconds
            cdx_calls.append(url)
            raise AssertionError("bulk scope must not call CDX")

        def bulk(payload):
            bulk_payloads.append(dict(payload))
            yield {
                "type": "summary",
                "end_reason": "queue_exhausted",
                "metric_stage": "canonical_url",
                "telemetry": {
                    "raw_url_observations": 0,
                    "successful_pages": 1,
                    "structured_records": 0,
                },
                "new_seeds": [],
                "round": {
                    "query_family": "bulk",
                    "source_class": "open_index",
                    "new_valid_urls": 0,
                    "new_entities": 0,
                    "new_fields": 0,
                    "mostly_duplicates": False,
                },
            }

        events = list(
            iter_backend_events(
                {
                    "scope": "domain",
                    "value": "example.com",
                    "query_family": "bulk",
                },
                fetcher=fail_cdx,
                bulk_adapter=bulk,
            )
        )
        self.assertEqual(cdx_calls, [])
        self.assertEqual(bulk_payloads[0]["scope"], "domain")
        self.assertEqual(events[-1]["end_reason"], "queue_exhausted")

    def test_exact_scope_uses_limit_without_match_type_or_pagination(self):
        fetcher = ExactFixtureFetcher()
        events = list(
            iter_backend_events(
                {
                    "scope": "exact",
                    "value": "https://example.com/",
                    "max_records": 5,
                },
                fetcher=fetcher,
            )
        )
        query = parse_qs(urlsplit(fetcher.urls[-1]).query)
        self.assertEqual(query["url"], ["https://example.com/"])
        self.assertEqual(query["limit"], ["5"])
        self.assertNotIn("matchType", query)
        self.assertNotIn("showNumPages", query)
        self.assertEqual(events[0]["url"], "https://example.com/")

    def test_exact_collection_and_historical_metadata(self):
        fetcher = ExactFixtureFetcher()
        events = list(
            iter_backend_events(
                {
                    "scope": "exact",
                    "value": "https://example.com/",
                    "query_family": "historical-products",
                },
                fetcher=fetcher,
            )
        )
        self.assertEqual(fetcher.urls[0], COLLECTIONS_URL)
        self.assertIn("CC-MAIN-2026-30-index", fetcher.urls[1])
        event = events[0]
        self.assertEqual(event["channels"], ["common_crawl"])
        self.assertEqual(event["metadata"]["source_role"], "historical_index")
        self.assertEqual(event["metadata"]["crawl_timestamp"], "20260701010101")
        self.assertEqual(event["metadata"]["warc_offset"], "100")
        self.assertEqual(event["metadata"]["warc_length"], "50")
        self.assertFalse(
            any("data.commoncrawl.org" in url for url in fetcher.urls),
            "the adapter must not download WARC bodies",
        )

    def test_exact_mode_builds_bounded_index_query(self):
        endpoint = COLLECTIONS[0]["cdx-api"]
        url = build_query_url(
            endpoint,
            CommonCrawlRequest(
                scope="exact",
                value="https://example.com/",
                max_records=7,
            ),
        )
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["url"], ["https://example.com/"])
        self.assertEqual(query["limit"], ["7"])
        self.assertEqual(query["output"], ["json"])
        self.assertNotIn("matchType", query)
        self.assertNotIn("showNumPages", query)

    def test_worker_count_above_two_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "workers"):
            CommonCrawlRequest(scope="domain", value="example.com", workers=3)

    def test_collection_endpoint_must_use_official_https_host(self):
        collections = [
            {**COLLECTIONS[0], "cdx-api": "https://attacker.example/index"}
        ]

        def fetcher(url: str, *, timeout_seconds: float) -> bytes:
            del timeout_seconds
            if url == COLLECTIONS_URL:
                return json.dumps(collections).encode("utf-8")
            self.fail("untrusted endpoint must not be fetched")

        with self.assertRaisesRegex(AdapterFailure, "common_crawl_untrusted_endpoint"):
            list(
                iter_backend_events(
                    {"scope": "exact", "value": "https://example.com/"},
                    fetcher=fetcher,
                )
            )

    def test_invalid_jsonl_and_missing_pages_have_stable_categories(self):
        def invalid_json(url: str, *, timeout_seconds: float) -> bytes:
            del timeout_seconds
            if url == COLLECTIONS_URL:
                return json.dumps(COLLECTIONS).encode("utf-8")
            return b"not-json\n"

        with self.assertRaisesRegex(AdapterFailure, "common_crawl_invalid_jsonl"):
            list(
                iter_backend_events(
                    {"scope": "exact", "value": "https://example.com/"},
                    fetcher=invalid_json,
                )
            )

        def missing_page(url: str, *, timeout_seconds: float) -> bytes:
            del timeout_seconds
            if url == COLLECTIONS_URL:
                return json.dumps(COLLECTIONS).encode("utf-8")
            return b""

        with self.assertRaisesRegex(AdapterFailure, "common_crawl_page_missing"):
            list(
                iter_backend_events(
                    {"scope": "exact", "value": "https://example.com/"},
                    fetcher=missing_page,
                )
            )


if __name__ == "__main__":
    unittest.main()
