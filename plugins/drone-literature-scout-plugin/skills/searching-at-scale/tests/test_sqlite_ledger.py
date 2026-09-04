from __future__ import annotations

from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.normalize_and_dedupe import (
    BatchSpec,
    SqliteUrlLedger,
    UrlObservation,
)


def batch_spec(batch_id: str = "batch-1") -> BatchSpec:
    return BatchSpec(
        batch_id=batch_id,
        run_id="run-1",
        task_id="task-1",
        adapter="test",
        scope_fingerprint="scope-1",
    )


def observation(
    url: str,
    *,
    title: str = "One",
    channels: tuple[str, ...] = ("searxng:bing",),
    metadata: dict[str, object] | None = None,
) -> UrlObservation:
    return UrlObservation(
        url=url,
        title=title,
        snippet="short evidence snippet",
        channels=channels,
        source_class="search",
        query_family="broad",
        observed_at="2026-08-03T00:00:00Z",
        metadata=metadata or {},
    )


def summary(
    *,
    raw_url_observations: int = 1,
    valid_urls: int = 1,
    unique_additions: int = 1,
    unique_candidate_additions: int = 0,
) -> dict[str, object]:
    return {
        "end_reason": "queue_exhausted",
        "raw_url_observations": raw_url_observations,
        "valid_urls": valid_urls,
        "unique_additions": unique_additions,
        "unique_candidate_additions": unique_candidate_additions,
    }


class SqliteLedgerTests(unittest.TestCase):
    def test_recovery_event_is_compact_query_family_scoped_and_migration_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.sqlite"
            with SqliteUrlLedger(path) as ledger:
                ledger.record_marketplace_recovery(
                    run_id="run-1",
                    platform="jd",
                    query_family="机械键盘:型号",
                    page_number=5,
                    recovery_stage="reload",
                    attempt=2,
                    category="browser_page_structure_changed",
                    disposition="rotate_family",
                )
                columns = tuple(
                    row[1]
                    for row in ledger._connection.execute(
                        "PRAGMA table_info(marketplace_recovery_events)"
                    )
                )
                self.assertEqual(
                    columns,
                    (
                        "event_id",
                        "run_id",
                        "platform",
                        "query_family",
                        "page_number",
                        "recovery_stage",
                        "attempt",
                        "category",
                        "disposition",
                    ),
                )
                self.assertEqual(ledger.marketplace_candidate_count(), 0)

            with SqliteUrlLedger(path) as ledger:
                row = ledger.recovery_events()[0]
                self.assertEqual(
                    set(row),
                    {
                        "event_id",
                        "run_id",
                        "platform",
                        "query_family",
                        "page_number",
                        "recovery_stage",
                        "attempt",
                        "category",
                        "disposition",
                    },
                )
                self.assertEqual(row["page_number"], 5)
                self.assertEqual(row["disposition"], "rotate_family")
                for forbidden in ("html", "text", "cookie", "url", "query"):
                    self.assertNotIn(forbidden, row)
                row["category"] = "mutated"
                self.assertEqual(
                    ledger.recovery_events()[0]["category"],
                    "browser_page_structure_changed",
                )

    def test_recovery_event_rejects_invalid_bounds_enums_and_control_text(self):
        valid = {
            "run_id": "run-1",
            "platform": "jd",
            "query_family": "机械键盘:型号",
            "page_number": 1,
            "recovery_stage": "initial",
            "attempt": 0,
            "category": "pagination_page_transient_empty",
            "disposition": "retry_same_page",
        }
        invalid = (
            {"page_number": 0},
            {"page_number": 513},
            {"recovery_stage": "initial", "attempt": 1},
            {"recovery_stage": "reproject", "attempt": 0},
            {"recovery_stage": "reload", "attempt": 1},
            {"platform": "amazon"},
            {"category": "arbitrary_failure"},
            {"disposition": "ignore"},
            {"disposition": "hard_block"},
            {"run_id": "run\nsecret"},
            {"query_family": "x" * 513},
        )
        with tempfile.TemporaryDirectory() as tmp:
            with SqliteUrlLedger(Path(tmp) / "run.sqlite") as ledger:
                for changes in invalid:
                    with self.subTest(changes=changes), self.assertRaises(ValueError):
                        ledger.record_marketplace_recovery(**{**valid, **changes})
                self.assertEqual(ledger.recovery_events(), ())

    def test_new_marketplace_table_stores_and_non_destructively_merges_card_fields(self):
        sku = "100123456789"
        url = f"https://item.jd.com/{sku}.html"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.sqlite"
            with SqliteUrlLedger(path) as ledger:
                columns = {
                    row[1]
                    for row in ledger._connection.execute(
                        "PRAGMA table_info(marketplace_candidates)"
                    )
                }
                self.assertIn("card_fields_json", columns)
                metadata = {
                    "platform": "jd",
                    "product_id": sku,
                    "card_fields": {"price": "99.00", "stock": "有货"},
                }
                with ledger.batch(batch_spec("card-1")) as writer:
                    writer.add(observation(url, title="枕头", metadata=metadata))
                    writer.finish(summary(unique_candidate_additions=1))
                with ledger.batch(batch_spec("card-2")) as writer:
                    writer.add(
                        observation(
                            url,
                            title="枕头",
                            metadata={
                                "platform": "jd",
                                "product_id": sku,
                                "card_fields": {
                                    "price": "88.00",
                                    "shop": "京东自营",
                                },
                            },
                        )
                    )
                    writer.finish(
                        summary(
                            unique_additions=0,
                            unique_candidate_additions=0,
                        )
                    )

                row = ledger._connection.execute(
                    "SELECT card_fields_json FROM marketplace_candidates"
                ).fetchone()
                self.assertEqual(
                    json.loads(row["card_fields_json"]),
                    {"price": "99.00", "shop": "京东自营", "stock": "有货"},
                )
                candidate = ledger.marketplace_candidate("jd", sku)
                self.assertEqual(
                    candidate.card_fields,
                    {"price": "99.00", "shop": "京东自营", "stock": "有货"},
                )
                self.assertEqual(
                    ledger.marketplace_card_field_coverage(),
                    {
                        "price": 1,
                        "shop": 1,
                        "commit": 0,
                        "good_rate": 0,
                        "promo": 0,
                        "stock": 1,
                        "image": 0,
                        "candidates_with_any_card_field": 1,
                    },
                )

    def test_old_marketplace_table_is_upgraded_without_losing_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.sqlite"
            connection = sqlite3.connect(path)
            connection.execute(
                """
                CREATE TABLE marketplace_candidates (
                    platform TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    url_id INTEGER NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    first_observed_at TEXT NOT NULL,
                    first_batch_id TEXT NOT NULL,
                    PRIMARY KEY (platform, product_id)
                )
                """
            )
            connection.execute(
                "INSERT INTO marketplace_candidates VALUES (?, ?, ?, ?, ?, ?)",
                ("jd", "1", 1, "旧商品", "2026-08-01T00:00:00Z", "old"),
            )
            connection.commit()
            connection.close()

            with SqliteUrlLedger(path) as ledger:
                columns = {
                    row[1]
                    for row in ledger._connection.execute(
                        "PRAGMA table_info(marketplace_candidates)"
                    )
                }
                self.assertIn("card_fields_json", columns)
                row = ledger._connection.execute(
                    "SELECT product_id, card_fields_json FROM marketplace_candidates"
                ).fetchone()
                self.assertEqual(tuple(row), ("1", "{}"))

    def test_marketplace_cursor_summary_separates_open_exhausted_and_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.sqlite"
            with SqliteUrlLedger(path) as ledger:
                additions = (1, 0, 0)
                statuses = ("advanced", "exhausted", "blocked")
                for index, (candidate_additions, status) in enumerate(
                    zip(additions, statuses, strict=True)
                ):
                    batch_id = f"cursor-batch-{index}"
                    with ledger.batch(batch_spec(batch_id)) as writer:
                        if candidate_additions:
                            writer.add(
                                observation(
                                    "https://item.jd.com/100123456789.html",
                                    title="透明防摔手机壳",
                                    metadata={
                                        "platform": "jd",
                                        "product_id": "100123456789",
                                    },
                                )
                            )
                        writer.finish(
                            summary(
                                raw_url_observations=candidate_additions,
                                valid_urls=candidate_additions,
                                unique_additions=candidate_additions,
                                unique_candidate_additions=candidate_additions,
                            )
                        )
                    ledger.record_marketplace_cursor(
                        cursor_id=f"jd:cursor-{index}",
                        source="edge:jd",
                        query_family="手机壳:default",
                        status=status,
                        last_batch_id=batch_id,
                        unique_candidate_additions=candidate_additions,
                    )

                scope = ledger.marketplace_scope_summary()
                self.assertEqual(
                    scope["sources"]["edge:jd"],
                    {"attempted": 3, "exhausted": 1, "blocked": 1, "open": 1},
                )
                self.assertEqual(scope["last_three_candidate_additions"], (0, 0, 1))
                with self.assertRaises(ValueError):
                    ledger.record_marketplace_cursor(
                        cursor_id="bad",
                        source="edge:jd",
                        query_family="手机壳:default",
                        status="complete",
                        last_batch_id="cursor-batch-2",
                        unique_candidate_additions=0,
                    )

    def test_same_jd_sku_is_one_candidate_with_all_channels(self):
        sku = "100123456789"
        url = f"https://item.jd.com/{sku}.html?utm_source=batch"
        routes = (
            ("edge:jd", "browser"),
            ("searxng:baidu", "search"),
            ("common_crawl", "open_index"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.sqlite"
            with SqliteUrlLedger(path) as ledger:
                for index, (channel, source_class) in enumerate(routes):
                    candidate_added = index == 0
                    item = UrlObservation(
                        url=url,
                        title="透明防摔手机壳",
                        snippet="public listing projection",
                        channels=(channel,),
                        source_class=source_class,
                        query_family=f"手机壳:route-{index}",
                        observed_at=f"2026-08-04T08:0{index}:00Z",
                        metadata={"platform": "jd", "product_id": sku},
                    )
                    with ledger.batch(batch_spec(f"jd-{index}")) as writer:
                        outcome = writer.add(item)
                        writer.finish(
                            summary(
                                unique_additions=1 if index == 0 else 0,
                                unique_candidate_additions=(
                                    1 if candidate_added else 0
                                ),
                            )
                        )
                    self.assertEqual(outcome.candidate_added, candidate_added)
                    self.assertEqual(
                        ledger.batch_stats(f"jd-{index}").unique_candidate_additions,
                        1 if candidate_added else 0,
                    )

                self.assertEqual(ledger.marketplace_candidate_count(), 1)
                candidate = ledger.marketplace_candidate("jd", sku)
                self.assertIsNotNone(candidate)
                self.assertEqual(candidate.platform, "jd")
                self.assertEqual(candidate.product_id, sku)
                self.assertEqual(
                    candidate.canonical_url,
                    f"https://item.jd.com/{sku}.html",
                )
                self.assertEqual(
                    ledger.marketplace_candidate_counts_by_channel(),
                    (
                        ("common_crawl", 1),
                        ("edge:jd", 1),
                        ("searxng:baidu", 1),
                    ),
                )
                provenance = ledger.provenance_for(url)
                self.assertEqual(
                    provenance.discovery_channels,
                    ("common_crawl", "edge:jd", "searxng:baidu"),
                )

                with ledger.batch(batch_spec("jd-0")) as writer:
                    replay = writer.add(
                        UrlObservation(
                            url=url,
                            title="透明防摔手机壳",
                            snippet="public listing projection",
                            channels=("edge:jd",),
                            source_class="browser",
                            query_family="手机壳:route-0",
                            observed_at="2026-08-04T08:00:00Z",
                            metadata={"platform": "jd", "product_id": sku},
                        )
                    )
                    writer.finish(
                        summary(
                            unique_additions=1,
                            unique_candidate_additions=1,
                        )
                    )
                self.assertTrue(replay.duplicate)
                self.assertFalse(replay.candidate_added)
                self.assertEqual(ledger.marketplace_candidate_count(), 1)

    def test_candidate_metadata_is_rechecked_against_the_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.sqlite"
            with SqliteUrlLedger(path) as ledger:
                with ledger.batch(batch_spec("mismatch-candidate")) as writer:
                    outcome = writer.add(
                        observation(
                            "https://item.jd.com/100123456789.html",
                            title="透明防摔手机壳",
                            metadata={
                                "platform": "jd",
                                "product_id": "999999999999",
                            },
                        )
                    )
                    writer.finish(summary(unique_candidate_additions=0))
                self.assertFalse(outcome.candidate_added)
                self.assertEqual(ledger.marketplace_candidate_count(), 0)
                self.assertEqual(ledger.stats().unique_urls, 1)

    def test_empty_title_keeps_url_without_promoting_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.sqlite"
            with SqliteUrlLedger(path) as ledger:
                with ledger.batch(batch_spec("empty-title")) as writer:
                    outcome = writer.add(
                        observation(
                            "https://item.jd.com/100123456789.html",
                            title="",
                            metadata={
                                "platform": "jd",
                                "product_id": "100123456789",
                            },
                        )
                    )
                    writer.finish(summary(unique_candidate_additions=0))
                self.assertFalse(outcome.candidate_added)
                self.assertEqual(ledger.marketplace_candidate_count(), 0)
                self.assertEqual(ledger.stats().unique_urls, 1)

    def test_old_batches_table_is_upgraded_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.sqlite"
            connection = sqlite3.connect(path)
            connection.execute(
                """
                CREATE TABLE batches (
                    batch_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    scope_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    end_reason TEXT NOT NULL,
                    raw_url_observations INTEGER NOT NULL,
                    valid_urls INTEGER NOT NULL,
                    unique_additions INTEGER NOT NULL,
                    terminal_summary_json TEXT NOT NULL
                )
                """
            )
            connection.commit()
            connection.close()

            with SqliteUrlLedger(path) as ledger:
                columns = {
                    row[1]
                    for row in ledger._connection.execute("PRAGMA table_info(batches)")
                }
                self.assertIn("unique_candidate_additions", columns)
                with ledger.batch(batch_spec("after-migration")) as writer:
                    writer.add(observation("https://example.com/item/1"))
                    writer.finish(summary())
                self.assertEqual(
                    ledger.batch_stats(
                        "after-migration"
                    ).unique_candidate_additions,
                    0,
                )

    def test_duplicate_url_keeps_all_discovery_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.sqlite"
            with SqliteUrlLedger(path) as ledger:
                with ledger.batch(batch_spec("batch-1")) as writer:
                    writer.add(
                        observation(
                            "https://example.com/item/1?utm_source=a",
                            channels=("searxng:bing",),
                        )
                    )
                    writer.finish(summary())
                with ledger.batch(batch_spec("batch-2")) as writer:
                    writer.add(
                        UrlObservation(
                            url="https://example.com/item/1",
                            title="One",
                            snippet="second",
                            channels=("common_crawl",),
                            source_class="open_index",
                            query_family="historical",
                            observed_at="2026-08-03T00:01:00Z",
                            metadata={"source_role": "historical_index"},
                        )
                    )
                    writer.finish(summary(unique_additions=0))
                provenance = ledger.provenance_for(
                    "https://example.com/item/1"
                )
                self.assertIsNotNone(provenance)
                self.assertEqual(
                    provenance.discovery_channels,
                    ("common_crawl", "searxng:bing"),
                )
                self.assertEqual(
                    provenance.source_classes, ("open_index", "search")
                )
                self.assertEqual(ledger.stats().unique_urls, 1)
                self.assertEqual(ledger.stats().raw_results, 2)

    def test_batch_without_terminal_summary_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.sqlite"
            with SqliteUrlLedger(path) as ledger:
                with self.assertRaisesRegex(
                    ValueError,
                    "terminal-summary-required",
                ):
                    with ledger.batch(batch_spec("partial")) as writer:
                        writer.add(observation("https://example.com/a"))
                self.assertEqual(ledger.stats().unique_urls, 0)
                self.assertFalse(ledger.has_batch("partial"))

    def test_duplicate_batch_id_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.sqlite"
            with SqliteUrlLedger(path) as ledger:
                for _ in range(2):
                    with ledger.batch(batch_spec("same")) as writer:
                        writer.add(observation("https://example.com/a"))
                        writer.finish(summary())
                self.assertEqual(ledger.stats().raw_results, 1)
                self.assertEqual(ledger.stats().unique_urls, 1)
                stats = ledger.batch_stats("same")
                self.assertIsNotNone(stats)
                self.assertEqual(stats.unique_additions, 1)

    def test_invalid_url_rolls_back_the_whole_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.sqlite"
            with SqliteUrlLedger(path) as ledger:
                with self.assertRaisesRegex(ValueError, "invalid-http-url"):
                    with ledger.batch(batch_spec("invalid")) as writer:
                        writer.add(observation("https://example.com/a"))
                        writer.add(observation("javascript:alert(1)"))
                        writer.finish(summary(raw_url_observations=2))
                self.assertEqual(ledger.stats().unique_urls, 0)
                self.assertFalse(ledger.has_batch("invalid"))

    def test_body_and_secret_metadata_are_rejected(self):
        for key in ("body", "html", "secret", "token", "cookie", "authorization"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "run.sqlite"
                with SqliteUrlLedger(path) as ledger:
                    with self.assertRaisesRegex(ValueError, "metadata-key-not-allowed"):
                        with ledger.batch(batch_spec(key)) as writer:
                            writer.add(
                                observation(
                                    "https://example.com/a",
                                    metadata={key: "sensitive-or-large"},
                                )
                            )
                            writer.finish(summary())
                    self.assertEqual(ledger.stats().unique_urls, 0)

    def test_summary_count_mismatch_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.sqlite"
            with SqliteUrlLedger(path) as ledger:
                with self.assertRaisesRegex(ValueError, "summary-count-mismatch"):
                    with ledger.batch(batch_spec("mismatch")) as writer:
                        writer.add(observation("https://example.com/a"))
                        writer.finish(summary(raw_url_observations=2))
                self.assertFalse(ledger.has_batch("mismatch"))

    def test_close_leaves_no_wal_or_shared_memory_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.sqlite"
            with SqliteUrlLedger(path) as ledger:
                with ledger.batch(batch_spec()) as writer:
                    writer.add(observation("https://example.com/a"))
                    writer.finish(summary())
            self.assertTrue(path.exists())
            self.assertFalse(Path(f"{path}-wal").exists())
            self.assertFalse(Path(f"{path}-shm").exists())


if __name__ == "__main__":
    unittest.main()
