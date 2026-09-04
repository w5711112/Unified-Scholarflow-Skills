from __future__ import annotations

from io import BytesIO
import json
import socket
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.backend_runner import AdapterFailure
from scripts.searxng_query import iter_searxng_events, probe_searxng_engines


SEARCH_RESPONSE = {
    "query": "memory foam pillow",
    "results": [
        {
            "url": "https://example.com/pillow/1",
            "title": "Pillow One",
            "content": "Short public result snippet",
            "engine": "bing",
            "engines": ["bing", "brave"],
            "positions": [1, 3],
        }
    ],
    "unresponsive_engines": [["google", "timeout"]],
}


class SearxngQueryTests(unittest.TestCase):
    def test_partial_engine_failures_keep_healthy_results_and_separate_health(self):
        response = {
            "query": "手机壳",
            "results": [
                {
                    "url": "https://item.jd.com/100123456789.html",
                    "title": "透明防摔手机壳",
                    "content": "京东公开搜索结果",
                    "engine": "baidu",
                    "engines": ["baidu"],
                    "positions": [1],
                }
            ],
            "unresponsive_engines": [
                ["sogou", "timeout"],
                ["quark", "HTTP 429"],
            ],
        }

        def open_url(request, *, timeout):
            del request, timeout
            return BytesIO(json.dumps(response).encode("utf-8"))

        events = list(
            iter_searxng_events(
                {
                    "query": "手机壳",
                    "engines": ["baidu", "sogou", "quark"],
                },
                base_url="http://127.0.0.1:8888",
                open_url=open_url,
            )
        )
        self.assertEqual([event["type"] for event in events], ["url", "summary"])
        self.assertEqual(events[0]["channels"], ["searxng:baidu"])
        telemetry = events[-1]["telemetry"]
        self.assertEqual(
            telemetry["unresponsive_engines"],
            [["sogou", "timeout"], ["quark", "HTTP 429"]],
        )
        self.assertEqual(
            telemetry["engine_health"],
            {
                "baidu": "available",
                "quark": "rate_limited",
                "sogou": "unresponsive",
            },
        )
        self.assertEqual(telemetry["cooldown_engines"], ["quark", "sogou"])

    def test_engine_probe_partitions_health_without_disabling_runtime(self):
        def open_url(request, *, timeout):
            del timeout
            engine = parse_qs(urlsplit(request.full_url).query)["engines"][0]
            if engine == "sogou":
                raise socket.timeout("slow")
            if engine == "quark":
                raise HTTPError(request.full_url, 429, "limited", {}, None)
            if engine == "360search":
                response = {
                    "results": [],
                    "unresponsive_engines": [["360search", "CAPTCHA required"]],
                }
            else:
                response = {
                    "results": [
                        {
                            "url": "https://example.com/health",
                            "title": "health",
                        }
                    ],
                    "unresponsive_engines": [],
                }
            return BytesIO(json.dumps(response).encode("utf-8"))

        probe = probe_searxng_engines(
            base_url="http://127.0.0.1:8888",
            engines=("360search", "baidu", "sogou", "quark"),
            open_url=open_url,
        )
        self.assertEqual(probe.available, ("baidu",))
        self.assertEqual(probe.unresponsive, ("sogou",))
        self.assertEqual(probe.rate_limited, ("quark",))
        self.assertEqual(probe.captcha, ("360search",))
        self.assertEqual(
            probe.cooldown_engines,
            ("360search", "quark", "sogou"),
        )
        self.assertEqual(probe.next_engines, ("baidu",))
        self.assertTrue(probe.runtime_available)

    def test_json_query_encodes_controls_and_preserves_engine_intersection(self):
        requests = []

        def open_url(request, *, timeout):
            del timeout
            requests.append(request.full_url)
            return BytesIO(json.dumps(SEARCH_RESPONSE).encode("utf-8"))

        events = list(
            iter_searxng_events(
                {
                    "query": "memory foam pillow",
                    "query_family": "product-search",
                    "language": "en-US",
                    "pageno": 2,
                    "time_range": "month",
                    "engines": ["bing", "brave"],
                },
                base_url="http://127.0.0.1:8888",
                open_url=open_url,
            )
        )
        query = parse_qs(urlsplit(requests[0]).query)
        self.assertEqual(query["q"], ["memory foam pillow"])
        self.assertEqual(query["format"], ["json"])
        self.assertEqual(query["language"], ["en-US"])
        self.assertEqual(query["pageno"], ["2"])
        self.assertEqual(query["time_range"], ["month"])
        self.assertEqual(query["engines"], ["bing,brave"])
        self.assertEqual(
            events[0]["channels"], ["searxng:bing", "searxng:brave"]
        )
        self.assertEqual(events[0]["metadata"]["engines"], ["bing", "brave"])
        self.assertEqual(
            events[-1]["telemetry"]["unresponsive_engines"],
            [["google", "timeout"]],
        )

    def test_each_result_is_one_observation_and_snippet_is_bounded(self):
        response = {
            **SEARCH_RESPONSE,
            "results": [
                {**SEARCH_RESPONSE["results"][0], "content": "x" * 3000}
            ],
        }

        def open_url(request, *, timeout):
            del request, timeout
            return BytesIO(json.dumps(response).encode("utf-8"))

        events = list(
            iter_searxng_events(
                {"query": "pillow"},
                base_url="http://localhost:9999",
                open_url=open_url,
            )
        )
        self.assertEqual([event["type"] for event in events], ["url", "summary"])
        self.assertEqual(len(events[0]["snippet"]), 2000)
        self.assertEqual(events[-1]["telemetry"]["raw_url_observations"], 1)

    def test_only_loopback_runtime_endpoints_are_allowed(self):
        for base_url in (
            "https://public.example",
            "http://192.168.1.2:8080",
            "http://127.0.0.1",
            "http://user@127.0.0.1:8080",
        ):
            with self.subTest(base_url=base_url):
                with self.assertRaisesRegex(ValueError, "base_url"):
                    list(
                        iter_searxng_events(
                            {"query": "pillow"},
                            base_url=base_url,
                            open_url=lambda request, timeout: None,
                        )
                    )

    def test_429_is_classified_once_without_retry_loop(self):
        calls = 0

        def open_url(request, *, timeout):
            nonlocal calls
            del request, timeout
            calls += 1
            raise HTTPError(
                "http://127.0.0.1:8888/search", 429, "limited", {}, None
            )

        with self.assertRaisesRegex(AdapterFailure, "searxng_rate_limited"):
            list(
                iter_searxng_events(
                    {"query": "pillow"},
                    base_url="http://127.0.0.1:8888",
                    open_url=open_url,
                )
            )
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
