from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import URLError

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.backend_runner import AdapterFailure
from scripts.common_crawl_url_index import (
    UrlIndexRequest,
    build_query_plan,
    build_shard_map_plan,
    iter_backend_events as iter_url_index_events,
    manifest_url,
    parse_manifest,
    parse_shard_map,
    select_candidate_parquet_urls,
)
from scripts.duckdb_runtime import (
    DuckDBExecutionResult,
    DuckDBResourceProfile,
    ResourceSnapshot,
)


INDEX_ID = "CC-MAIN-2026-30"
RELATIVE_PARQUET = (
    "cc-index/table/cc-main/warc/crawl=CC-MAIN-2026-30/"
    "subset=warc/part-00000.c000.gz.parquet"
)
PARQUET_URL = f"https://data.commoncrawl.org/{RELATIVE_PARQUET}"
PARQUET_URL_1 = PARQUET_URL.replace("part-00000", "part-00001")
PARQUET_URL_2 = PARQUET_URL.replace("part-00000", "part-00002")

RESULT_RECORD = {
    "url": "https://docs.python.org/3/library/",
    "fetch_time": "2026-07-01 00:00:00+00",
    "fetch_status": 200,
    "content_mime_type": "text/html",
    "content_digest": "sha1:TEST",
    "warc_filename": "crawl-data/a.warc.gz",
    "warc_record_offset": 1,
    "warc_record_length": 2,
    "crawl": INDEX_ID,
    "subset": "warc",
}


class ManifestFetcher:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.urls: list[str] = []

    def __call__(self, url: str, *, timeout_seconds: float) -> bytes:
        del timeout_seconds
        self.urls.append(url)
        if url.endswith("/collinfo.json"):
            return json.dumps([{"id": INDEX_ID}]).encode("utf-8")
        if url == manifest_url(INDEX_ID):
            return self.payload
        raise AssertionError(f"unexpected network fetch: {url}")


class FixtureRuntime:
    def __init__(
        self,
        output: bytes,
        *,
        result: DuckDBExecutionResult | None = None,
        stderr: str = "",
    ):
        self.output = output
        self.result = result or DuckDBExecutionResult(0, False, False, 12.5, None)
        self.stderr = stderr
        self.run_calls = 0
        self.sql_names: list[str] = []

    def probe_resources(self, task_temp_parent: Path) -> ResourceSnapshot:
        self.probe_path = Path(task_temp_parent)
        return ResourceSnapshot(16, 64 << 30, 48 << 30, 2 << 40)

    def choose_resource_profile(self, snapshot, **kwargs) -> DuckDBResourceProfile:
        del snapshot, kwargs
        return DuckDBResourceProfile(8, 8 << 30, 32 << 30, 600.0)

    def ensure_duckdb(self, **kwargs) -> Path:
        return Path(kwargs["cache_root"]) / "duckdb" / "duckdb.exe"

    def run_duckdb(
        self,
        duckdb_path,
        sql_path,
        stdout_path,
        stderr_path,
        **kwargs,
    ) -> DuckDBExecutionResult:
        del duckdb_path, stdout_path, kwargs
        self.run_calls += 1
        sql_file = Path(sql_path)
        self.sql_names.append(sql_file.name)
        if sql_file.name == "shard-map.sql":
            shard_row = {
                "file_name": PARQUET_URL,
                "min_host": "a",
                "max_host": "zzzz",
            }
            (sql_file.parent / "shard-map.ndjson").write_text(
                json.dumps(shard_row) + "\n", encoding="utf-8"
            )
            Path(stderr_path).write_text("", encoding="utf-8")
            return DuckDBExecutionResult(0, False, False, 1.5, None)
        (sql_file.parent / "result.ndjson").write_bytes(self.output)
        Path(stderr_path).write_text(self.stderr, encoding="utf-8")
        return self.result


class CommonCrawlUrlIndexTests(unittest.TestCase):
    def test_manifest_url_is_bound_to_one_validated_crawl(self):
        self.assertEqual(
            manifest_url(INDEX_ID),
            "https://data.commoncrawl.org/crawl-data/"
            "CC-MAIN-2026-30/cc-index-table.paths.gz",
        )
        with self.assertRaisesRegex(ValueError, "index_id"):
            manifest_url("latest")

    def test_manifest_accepts_selected_crawl_parquet_and_deduplicates(self):
        payload = gzip.compress(
            f"{RELATIVE_PARQUET}\n{RELATIVE_PARQUET}\n".encode("utf-8")
        )
        self.assertEqual(parse_manifest(payload, INDEX_ID), (PARQUET_URL,))

    def test_manifest_ignores_other_trusted_subsets_and_returns_only_warc(self):
        diagnostics = (
            "cc-index/table/cc-main/warc/crawl=CC-MAIN-2026-30/"
            "subset=crawldiagnostics/part-00000.c000.zstd.parquet"
        )
        payload = gzip.compress(
            f"{diagnostics}\n{RELATIVE_PARQUET}\n".encode("utf-8")
        )
        self.assertEqual(parse_manifest(payload, INDEX_ID), (PARQUET_URL,))

    def test_manifest_rejects_cross_crawl_traversal_absolute_and_non_parquet(self):
        invalid_lines = (
            "cc-index/table/cc-main/warc/crawl=CC-MAIN-2026-25/"
            "subset=warc/part.parquet",
            "../../outside.parquet",
            "https://attacker.example/part.parquet",
            "cc-index/table/cc-main/warc/crawl=CC-MAIN-2026-30/"
            "subset=warc/file.exe",
        )
        for line in invalid_lines:
            with self.subTest(line=line), self.assertRaisesRegex(
                AdapterFailure, "common_crawl_manifest_invalid"
            ):
                parse_manifest(gzip.compress(f"{line}\n".encode("utf-8")), INDEX_ID)

    def test_empty_or_corrupt_manifest_has_stable_category(self):
        for payload in (gzip.compress(b"\n"), b"not-gzip"):
            with self.subTest(payload=payload), self.assertRaisesRegex(
                AdapterFailure, "common_crawl_manifest_invalid"
            ):
                parse_manifest(payload, INDEX_ID)

    def test_subdomain_plan_uses_reversed_host_and_dynamic_limits(self):
        request = UrlIndexRequest(
            "subdomain",
            "Docs.Python.org.",
            INDEX_ID,
            900,
            420.0,
            "docs",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = build_query_plan(
                request,
                (PARQUET_URL,),
                root / "result.ndjson",
                threads=4,
                memory_limit_bytes=8 << 30,
                max_temp_directory_size_bytes=32 << 30,
                temp_directory=root / "duckdb-temp",
                extension_directory=root / "extensions",
            )
        self.assertIn("url_host_tld = 'org'", plan.sql)
        self.assertIn("url_host_name_reversed = 'org.python.docs'", plan.sql)
        self.assertIn(
            "starts_with(url_host_name_reversed, 'org.python.docs.')", plan.sql
        )
        self.assertIn("SET threads = 4", plan.sql)
        self.assertIn("SET memory_limit = '8589934592B'", plan.sql)
        self.assertIn("LIMIT 900", plan.sql)
        self.assertNotIn("showNumPages", plan.sql)
        self.assertEqual(plan.parquet_file_count, 1)

    def test_shard_map_plan_reads_only_hostname_footer_statistics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = build_shard_map_plan(
                INDEX_ID,
                (PARQUET_URL, PARQUET_URL_1),
                root / "shard-map.ndjson",
                threads=4,
                memory_limit_bytes=8 << 30,
                max_temp_directory_size_bytes=32 << 30,
                temp_directory=root / "duckdb-temp",
                extension_directory=root / "extensions",
            )
        self.assertIn("parquet_metadata", plan.sql)
        self.assertIn("path_in_schema = 'url_host_name_reversed'", plan.sql)
        self.assertNotIn("SELECT url,", plan.sql)
        self.assertEqual(plan.parquet_file_count, 2)

    def test_complete_shard_map_selects_only_overlapping_hostname_files(self):
        rows = (
            {"file_name": PARQUET_URL, "min_host": "com.a", "max_host": "com.zzz"},
            {
                "file_name": PARQUET_URL_1,
                "min_host": "org.a",
                "max_host": "org.python.zzz",
            },
            {"file_name": PARQUET_URL_2, "min_host": "ru.a", "max_host": "ru.zzz"},
        )
        payload = b"".join(
            (json.dumps(row) + "\n").encode("utf-8") for row in rows
        )
        shard_map = parse_shard_map(
            payload,
            INDEX_ID,
            (PARQUET_URL, PARQUET_URL_1, PARQUET_URL_2),
        )
        exact = UrlIndexRequest(
            "domain", "example.com", INDEX_ID, 10, 600, "exact-host"
        )
        subdomain = UrlIndexRequest(
            "subdomain", "python.org", INDEX_ID, 10, 600, "subdomains"
        )
        self.assertEqual(
            select_candidate_parquet_urls(exact, shard_map), (PARQUET_URL,)
        )
        self.assertEqual(
            select_candidate_parquet_urls(subdomain, shard_map),
            (PARQUET_URL_1,),
        )

    def test_incomplete_shard_map_is_rejected_instead_of_claiming_coverage(self):
        row = {"file_name": PARQUET_URL, "min_host": "com.a", "max_host": "com.z"}
        payload = (json.dumps(row) + "\n").encode("utf-8")
        with self.assertRaisesRegex(
            AdapterFailure, "common_crawl_shard_map_invalid"
        ):
            parse_shard_map(
                payload,
                INDEX_ID,
                (PARQUET_URL, PARQUET_URL_1),
            )

    def test_domain_plan_handles_multi_label_suffix_without_psl_guessing(self):
        request = UrlIndexRequest(
            "domain", "shop.example.co.uk", INDEX_ID, 300, 300.0, "catalog"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sql = build_query_plan(
                request,
                (PARQUET_URL,),
                root / "result.ndjson",
                threads=2,
                memory_limit_bytes=2 << 30,
                max_temp_directory_size_bytes=8 << 30,
                temp_directory=root / "duckdb-temp",
                extension_directory=root / "extensions",
            ).sql
        self.assertIn("url_host_tld = 'uk'", sql)
        self.assertIn("url_host_name_reversed = 'uk.co.example.shop'", sql)

    def test_prefix_plan_idna_normalizes_host_and_escapes_quote(self):
        request = UrlIndexRequest(
            "prefix",
            "https://例子.测试/产品/o'hare/",
            INDEX_ID,
            120,
            240.0,
            "idn",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sql = build_query_plan(
                request,
                (PARQUET_URL,),
                root / "result.ndjson",
                threads=2,
                memory_limit_bytes=2 << 30,
                max_temp_directory_size_bytes=8 << 30,
                temp_directory=root / "duckdb-temp",
                extension_directory=root / "extensions",
            ).sql
        self.assertIn("url_host_tld = 'xn--0zwm56d'", sql)
        self.assertIn(
            "url_host_name_reversed = 'xn--0zwm56d.xn--fsqu00a'", sql
        )
        self.assertIn("o''hare", sql)
        self.assertNotIn("o'hare/');", sql)

    def test_request_rejects_invalid_scope_url_control_and_limits(self):
        cases = (
            ("domain", "https://example.com", 10, 30.0),
            ("prefix", "ftp://example.com/files/", 10, 30.0),
            ("prefix", "https://example.com/\x00", 10, 30.0),
            ("domain", "example.com", 0, 30.0),
            ("domain", "example.com", 10, 0.0),
        )
        for scope, value, limit, timeout in cases:
            with self.subTest(scope=scope, value=value), self.assertRaises(ValueError):
                UrlIndexRequest(
                    scope,
                    value,
                    INDEX_ID,
                    limit,
                    timeout,
                    "invalid",
                )

    def test_bulk_success_emits_historical_metadata_and_complete_summary(self):
        manifest = gzip.compress(f"{RELATIVE_PARQUET}\n".encode("utf-8"))
        fetcher = ManifestFetcher(manifest)
        runtime = FixtureRuntime((json.dumps(RESULT_RECORD) + "\n").encode("utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = list(
                iter_url_index_events(
                    {
                        "scope": "subdomain",
                        "value": "docs.python.org",
                        "index_id": INDEX_ID,
                        "raw_result_limit": 3,
                        "timeout_seconds": 600,
                        "query_family": "python-docs",
                    },
                    fetcher=fetcher,
                    runtime=runtime,
                    cache_root=root,
                )
            )
            self.assertEqual(
                list((root / "common-crawl" / "batches").glob("batch-*")), []
            )
        self.assertEqual(fetcher.urls, [manifest_url(INDEX_ID)])
        self.assertEqual(events[0]["url"], RESULT_RECORD["url"])
        self.assertEqual(events[0]["channels"], ["common_crawl"])
        self.assertEqual(events[0]["metadata"]["source_role"], "historical_index")
        self.assertEqual(events[0]["metadata"]["crawl"], INDEX_ID)
        self.assertEqual(events[0]["metadata"]["warc_offset"], 1)
        self.assertEqual(events[-1]["end_reason"], "queue_exhausted")
        self.assertTrue(events[-1]["deterministic_scope_complete"])
        self.assertEqual(events[-1]["telemetry"]["raw_url_observations"], 1)
        self.assertEqual(events[-1]["duckdb_profile"]["threads"], 8)
        self.assertEqual(events[-1]["parquet_file_count"], 1)
        self.assertEqual(events[-1]["candidate_parquet_file_count"], 1)
        self.assertFalse(events[-1]["shard_map_cache_hit"])
        self.assertEqual(runtime.run_calls, 2)
        self.assertEqual(runtime.sql_names, ["shard-map.sql", "query.sql"])

    def test_reaching_raw_limit_is_explicit_partial(self):
        manifest = gzip.compress(f"{RELATIVE_PARQUET}\n".encode("utf-8"))
        lines = b"".join(
            (json.dumps({**RESULT_RECORD, "url": f"https://example.com/{rank}"}) + "\n").encode("utf-8")
            for rank in range(2)
        )
        with tempfile.TemporaryDirectory() as tmp:
            events = list(
                iter_url_index_events(
                    {
                        "scope": "domain",
                        "value": "example.com",
                        "index_id": INDEX_ID,
                        "raw_result_limit": 2,
                    },
                    fetcher=ManifestFetcher(manifest),
                    runtime=FixtureRuntime(lines),
                    cache_root=Path(tmp),
                )
            )
        self.assertEqual(events[-1]["end_reason"], "partial")
        self.assertEqual(events[-1]["incomplete_reason"], "result_limit")
        self.assertFalse(events[-1]["deterministic_scope_complete"])

    def test_timeout_keeps_complete_lines_and_discards_trailing_fragment(self):
        manifest = gzip.compress(f"{RELATIVE_PARQUET}\n".encode("utf-8"))
        output = (json.dumps(RESULT_RECORD) + "\n").encode("utf-8") + b'{"url":"broken'
        timed_out = DuckDBExecutionResult(None, True, False, 600.0, None)
        with tempfile.TemporaryDirectory() as tmp:
            events = list(
                iter_url_index_events(
                    {
                        "scope": "prefix",
                        "value": "https://docs.python.org/3/",
                        "index_id": INDEX_ID,
                        "raw_result_limit": 50,
                    },
                    fetcher=ManifestFetcher(manifest),
                    runtime=FixtureRuntime(output, result=timed_out),
                    cache_root=Path(tmp),
                )
            )
        self.assertEqual(len([event for event in events if event["type"] == "url"]), 1)
        self.assertEqual(events[-1]["end_reason"], "partial")
        self.assertEqual(events[-1]["incomplete_reason"], "timeout")
        self.assertEqual(events[-1]["telemetry"]["raw_url_observations"], 1)

    def test_timeout_without_a_complete_line_is_retryable_failure(self):
        manifest = gzip.compress(f"{RELATIVE_PARQUET}\n".encode("utf-8"))
        timed_out = DuckDBExecutionResult(None, True, False, 600.0, None)
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            AdapterFailure, "common_crawl_timeout"
        ):
            list(
                iter_url_index_events(
                    {
                        "scope": "domain",
                        "value": "example.com",
                        "index_id": INDEX_ID,
                    },
                    fetcher=ManifestFetcher(manifest),
                    runtime=FixtureRuntime(b'{"url":', result=timed_out),
                    cache_root=Path(tmp),
                )
            )

    def test_nonzero_exit_maps_to_stable_failure_categories(self):
        manifest = gzip.compress(f"{RELATIVE_PARQUET}\n".encode("utf-8"))
        cases = (
            ("Out of Memory Error", "common_crawl_resource_limit"),
            ("HTTP GET failed: connection refused", "common_crawl_network_error"),
            ("Binder Error: Referenced column missing", "common_crawl_schema_changed"),
            ("Extension httpfs could not load", "common_crawl_dependency"),
        )
        for stderr, category in cases:
            with self.subTest(stderr=stderr), tempfile.TemporaryDirectory() as tmp:
                failed = DuckDBExecutionResult(1, False, False, 2.0, None)
                with self.assertRaisesRegex(AdapterFailure, category):
                    list(
                        iter_url_index_events(
                            {
                                "scope": "domain",
                                "value": "example.com",
                                "index_id": INDEX_ID,
                            },
                            fetcher=ManifestFetcher(manifest),
                            runtime=FixtureRuntime(
                                b"", result=failed, stderr=stderr
                            ),
                            cache_root=Path(tmp),
                        )
                    )

    def test_duckdb_download_urlerror_is_retryable_network_failure(self):
        manifest = gzip.compress(f"{RELATIVE_PARQUET}\n".encode("utf-8"))
        runtime = FixtureRuntime(b"")

        def fail_download(**kwargs):
            del kwargs
            raise URLError("release redirect timed out")

        runtime.ensure_duckdb = fail_download
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(
            AdapterFailure
        ) as raised:
            list(
                iter_url_index_events(
                    {
                        "scope": "domain",
                        "value": "example.com",
                        "index_id": INDEX_ID,
                    },
                    fetcher=ManifestFetcher(manifest),
                    runtime=runtime,
                    cache_root=Path(tmp),
                )
            )
        self.assertEqual(raised.exception.category, "common_crawl_network_error")
        self.assertTrue(raised.exception.retryable)

    def test_duckdb_download_connection_reset_is_retryable_network_failure(self):
        manifest = gzip.compress(f"{RELATIVE_PARQUET}\n".encode("utf-8"))
        runtime = FixtureRuntime(b"")

        def fail_download(**kwargs):
            del kwargs
            raise ConnectionResetError("release connection reset")

        runtime.ensure_duckdb = fail_download
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(
            AdapterFailure
        ) as raised:
            list(
                iter_url_index_events(
                    {
                        "scope": "domain",
                        "value": "example.com",
                        "index_id": INDEX_ID,
                    },
                    fetcher=ManifestFetcher(manifest),
                    runtime=runtime,
                    cache_root=Path(tmp),
                )
            )
        self.assertEqual(raised.exception.category, "common_crawl_network_error")
        self.assertTrue(raised.exception.retryable)

    def test_verified_manifest_cache_is_reused_without_network(self):
        manifest = gzip.compress(f"{RELATIVE_PARQUET}\n".encode("utf-8"))
        payload = {
            "scope": "domain",
            "value": "example.com",
            "index_id": INDEX_ID,
            "raw_result_limit": 3,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            list(
                iter_url_index_events(
                    payload,
                    fetcher=ManifestFetcher(manifest),
                    runtime=FixtureRuntime(b""),
                    cache_root=root,
                )
            )

            def fail_fetch(*args, **kwargs):
                raise AssertionError("verified manifest should be reused")

            second_runtime = FixtureRuntime(b"")
            events = list(
                iter_url_index_events(
                    payload,
                    fetcher=fail_fetch,
                    runtime=second_runtime,
                    cache_root=root,
                )
            )
            cached = root / "common-crawl" / "manifests" / f"{INDEX_ID}.paths.gz"
            shard_cache = root / "common-crawl" / "shard-maps" / f"{INDEX_ID}.ndjson"
            self.assertTrue(cached.is_file())
            self.assertTrue(shard_cache.is_file())
        self.assertEqual(events[-1]["end_reason"], "queue_exhausted")
        self.assertTrue(events[-1]["shard_map_cache_hit"])
        self.assertEqual(second_runtime.sql_names, ["query.sql"])

    def test_missing_index_selects_first_official_collection(self):
        manifest = gzip.compress(f"{RELATIVE_PARQUET}\n".encode("utf-8"))
        fetcher = ManifestFetcher(manifest)
        with tempfile.TemporaryDirectory() as tmp:
            events = list(
                iter_url_index_events(
                    {"scope": "domain", "value": "example.com"},
                    fetcher=fetcher,
                    runtime=FixtureRuntime(b""),
                    cache_root=Path(tmp),
                )
            )
        self.assertTrue(fetcher.urls[0].endswith("/collinfo.json"))
        self.assertEqual(events[-1]["scope_completion"]["crawl"], INDEX_ID)


if __name__ == "__main__":
    unittest.main()
