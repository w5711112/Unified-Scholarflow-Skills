from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.marketplace_candidates import (
    candidate_from_url,
)
from scripts.edge_marketplace_query import EdgeWorkerFailure, iter_edge_marketplace_events


EDGE_PAYLOAD = {
    "platform": "jd",
    "query": "手机壳",
    "query_family": "手机壳:default",
    "cursor": {"cursor_id": "jd:手机壳:default:page-1", "ordinal": 0, "page_number": 1},
    "user_data_dir": "",
    "deadline_seconds": 600.0,
    "max_items": 1000,
    "session_action": "start",
    "pagination_enabled": False,
}


JD_READY_BATCH = {
    "projection_schema_version": 4,
    "capabilities": [
        "stable_card_fields_v2",
        "verified_pagination_v1",
        "resilient_pagination_v1",
    ],
    "platform": "jd",
    "page_state": "ready",
    "source_url": "https://search.jd.com/Search",
    "query_family": "手机壳:default",
    "cursor": {
        "cursor_id": "jd:手机壳:default:page-1",
        "page_number": 1,
        "status": "advanced",
    },
    "observed_page_number": 1,
    "pagination_state": "pagination_unverified",
    "has_next_page": False,
    "sku_digest": "100123456789",
    "diagnostics": {
        "document_ready_state": "complete",
        "data_sku_node_count": 1,
        "candidate_anchor_count": 1,
        "valid_item_count": 1,
        "collection_elapsed_ms": 20000,
        "stable_rounds": 40,
        "observed_page_number": 1,
        "recovery_stage": "initial",
        "recovery_attempt": 0,
        "source_path": "/Search",
    },
    "items": [
        {
            "product_id": "100123456789",
            "title": "透明防摔手机壳",
            "url": "https://item.jd.com/100123456789.html?cu=true",
            "price": None,
            "shop": None,
            "commit": None,
            "good_rate": None,
            "promo": None,
            "stock": None,
            "image": None,
        }
    ],
}


class MarketplaceCandidateTests(unittest.TestCase):
    @staticmethod
    def _events(batch):
        return tuple(
            iter_edge_marketplace_events(
                EDGE_PAYLOAD,
                worker_runner=lambda payload, **kwargs: batch,
            )
        )

    def test_ready_browser_batch_emits_public_projection_and_summary_only(self):
        events = self._events(JD_READY_BATCH)

        self.assertEqual([event["type"] for event in events], ["url", "summary"])
        item = events[0]
        self.assertEqual(item["channels"], ["edge:jd"])
        self.assertEqual(item["source_class"], "marketplace_list")
        self.assertEqual(
            item["metadata"],
            {
                "source_role": "marketplace_store",
                "platform": "jd",
                "product_id": "100123456789",
                "card_fields": {},
            },
        )
        summary = events[1]
        self.assertNotIn("items", summary)
        self.assertNotIn("source_url", summary)
        self.assertEqual(
            summary["cursor_evidence"],
            {
                "platform": "jd",
                "cursor_id": "jd:手机壳:default:page-1",
                "page_number": 1,
                "status": "advanced",
                "observed_page_number": 1,
                "pagination_state": "pagination_unverified",
                "has_next_page": False,
                "sku_digest": "100123456789",
            },
        )

    def test_browser_batch_rejects_page_evidence_mismatch(self):
        value = dict(JD_READY_BATCH)
        value["cursor"] = dict(JD_READY_BATCH["cursor"])
        value["observed_page_number"] = 2

        with self.assertRaisesRegex(EdgeWorkerFailure, "observed_page_number"):
            self._events(value)

    def test_browser_batch_rejects_unknown_or_inconsistent_item_before_yield(self):
        invalid_items = (
            {
                "product_id": "100123456789",
                "title": "透明防摔手机壳",
                "url": "https://item.jd.com/100123456789.html",
                "unknown_field": "should be rejected",
            },
            {
                "product_id": "100123456789",
                "title": "",
                "url": "https://item.jd.com/100123456789.html",
            },
            {
                "product_id": "999999999999",
                "title": "透明防摔手机壳",
                "url": "https://item.jd.com/100123456789.html",
            },
        )
        for item in invalid_items:
            value = dict(JD_READY_BATCH)
            value["cursor"] = dict(JD_READY_BATCH["cursor"])
            value["items"] = [item]
            with self.subTest(item=item), self.assertRaisesRegex(
                EdgeWorkerFailure, "browser_batch_invalid"
            ):
                self._events(value)

    def test_ready_browser_batch_preserves_public_card_fields(self):
        value = dict(JD_READY_BATCH)
        value["cursor"] = dict(JD_READY_BATCH["cursor"])
        value["items"] = [
            {
                "product_id": "100123456789",
                "title": "透明防摔手机壳",
                "url": "https://item.jd.com/100123456789.html",
                "price": "9.90",
                "shop": "京东自营",
                "commit": "2.1万+条评价",
                "good_rate": None,
                "promo": None,
                "stock": "有货",
                "image": "https://img.example.com/a.jpg",
            }
        ]
        events = self._events(value)
        self.assertEqual(events[0]["metadata"]["card_fields"]["price"], "9.90")
        self.assertEqual(events[0]["metadata"]["card_fields"]["shop"], "京东自营")
        self.assertEqual(events[0]["metadata"]["card_fields"]["commit"], "2.1万+条评价")
        self.assertEqual(events[0]["metadata"]["card_fields"]["stock"], "有货")
        self.assertEqual(
            events[0]["metadata"]["card_fields"]["image"],
            "https://img.example.com/a.jpg",
        )

    def test_ready_browser_batch_rejects_non_string_card_field(self):
        value = dict(JD_READY_BATCH)
        value["cursor"] = dict(JD_READY_BATCH["cursor"])
        value["items"] = [
            {
                "product_id": "100123456789",
                "title": "透明防摔手机壳",
                "url": "https://item.jd.com/100123456789.html",
                "price": 9.9,
                "shop": None,
                "commit": None,
                "good_rate": None,
                "promo": None,
                "stock": None,
                "image": None,
            }
        ]
        with self.assertRaisesRegex(EdgeWorkerFailure, "price"):
            self._events(value)

    def test_browser_item_requires_all_stable_card_field_keys(self):
        value = dict(JD_READY_BATCH)
        value["cursor"] = dict(JD_READY_BATCH["cursor"])
        item = dict(JD_READY_BATCH["items"][0])
        del item["stock"]
        value["items"] = [item]

        with self.assertRaisesRegex(EdgeWorkerFailure, "missing=stock"):
            self._events(value)

    def test_rate_limited_page_has_a_stable_failure_category(self):
        value = dict(JD_READY_BATCH)
        value["cursor"] = dict(JD_READY_BATCH["cursor"])
        value["page_state"] = "rate_limited"
        value["items"] = []
        value["diagnostics"] = {
            **JD_READY_BATCH["diagnostics"],
            "valid_item_count": 0,
        }

        with self.assertRaises(EdgeWorkerFailure) as raised:
            self._events(value)
        self.assertEqual(raised.exception.category, "browser_rate_limited")

    def test_jd_mobile_and_tracking_urls_collapse_to_one_sku(self):
        values = (
            "https://item.jd.com/100123456789.html?utm_source=test",
            "https://item.m.jd.com/product/100123456789.html?utm_source=test",
        )
        candidates = tuple(
            candidate_from_url(
                url=value,
                title="透明防摔手机壳",
                discovery_channel="edge:jd",
                query_family="手机壳:default",
                observed_at="2026-08-04T08:00:00Z",
            )
            for value in values
        )

        self.assertTrue(all(candidate is not None for candidate in candidates))
        self.assertEqual(
            {candidate.product_id for candidate in candidates if candidate},
            {"100123456789"},
        )
        self.assertEqual(
            {candidate.canonical_url for candidate in candidates if candidate},
            {"https://item.jd.com/100123456789.html"},
        )
        self.assertEqual(
            {candidate.platform for candidate in candidates if candidate},
            {"jd"},
        )

    def test_taobao_and_tmall_links_require_a_stable_numeric_id(self):
        taobao = candidate_from_url(
            url="https://item.taobao.com/item.htm?id=812345678901&spm=test",
            title="凯夫拉手机壳",
            discovery_channel="searxng:baidu",
            query_family="手机壳:taobao",
            observed_at="2026-08-04T08:00:00Z",
        )
        tmall = candidate_from_url(
            url="https://detail.tmall.com/item.htm?abbucket=1&id=712345678901",
            title="液态硅胶手机壳",
            discovery_channel="searxng:baidu",
            query_family="手机壳:tmall",
            observed_at="2026-08-04T08:00:00Z",
        )

        self.assertIsNotNone(taobao)
        self.assertEqual(taobao.platform, "taobao")
        self.assertEqual(taobao.product_id, "812345678901")
        self.assertEqual(
            taobao.canonical_url,
            "https://item.taobao.com/item.htm?id=812345678901",
        )
        self.assertIsNotNone(tmall)
        self.assertEqual(tmall.platform, "taobao")
        self.assertEqual(
            tmall.canonical_url,
            "https://detail.tmall.com/item.htm?id=712345678901",
        )
        for url in (
            "https://s.taobao.com/search?q=手机壳",
            "https://item.taobao.com/item.htm?id=not-numeric",
            "https://uland.taobao.com/coupon/edetail?e=redirect",
        ):
            with self.subTest(url=url):
                self.assertIsNone(
                    candidate_from_url(
                        url=url,
                        title="手机壳",
                        discovery_channel="searxng:baidu",
                        query_family="手机壳:taobao",
                        observed_at="2026-08-04T08:00:00Z",
                    )
                )

    def test_empty_title_is_plain_url_but_other_context_is_required(self):
        self.assertIsNone(
            candidate_from_url(
                url="https://item.jd.com/100123456789.html",
                title="  ",
                discovery_channel="edge:jd",
                query_family="手机壳:default",
                observed_at="2026-08-04T08:00:00Z",
            )
        )
        for field in ("discovery_channel", "query_family", "observed_at"):
            values = {
                "url": "https://item.jd.com/100123456789.html",
                "title": "透明防摔手机壳",
                "discovery_channel": "edge:jd",
                "query_family": "手机壳:default",
                "observed_at": "2026-08-04T08:00:00Z",
            }
            values[field] = ""
            with self.subTest(field=field), self.assertRaises(ValueError):
                candidate_from_url(**values)

    def test_candidate_is_an_immutable_detached_value(self):
        candidate = candidate_from_url(
            url="https://item.jd.com/100123456789.html",
            title="  透明防摔手机壳  ",
            discovery_channel=" edge:jd ",
            query_family=" 手机壳:default ",
            observed_at=" 2026-08-04T08:00:00Z ",
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.title, "透明防摔手机壳")
        with self.assertRaises(FrozenInstanceError):
            candidate.title = "mutated"


if __name__ == "__main__":
    unittest.main()
