from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.discover_sitemaps import FetchOutcome
from scripts.market_scheduler import (
    create_run_state,
    ingest_batch_result,
    load_state,
    pure_search_seconds,
    record_discovery_interval,
    resume_state,
    run_builtin_task,
    save_state_atomic,
    select_next_tasks,
)
from scripts.normalize_and_dedupe import (
    BatchSpec,
    SqliteUrlLedger,
    UrlObservation,
)
from test_marketplace_candidates import JD_READY_BATCH


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "market_scheduler.py"


def source_task(
    task_id: str,
    source_class: str,
    adapter: str,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "source_class": source_class,
        "backend": task_id,
        "query_family": f"family:{task_id}",
        "query_dimensions": ["platform"],
        "coverage_targets": [],
        "adapter": adapter,
        "payload": payload or {},
        "status": "pending",
        "score_inputs": {},
        "concurrency": {"tier": 24, "tool_limit": 40, "host_limit": 40},
    }


BASE_CONFIG = {
    "topic": "枕头",
    "scope_fingerprint": "cn-pillow-market-v1",
    "ledger_path": str(
        Path(tempfile.gettempdir()) / "searching-at-scale-cli-test-unused.sqlite"
    ),
    "applicable_sources": ["sitemap", "search_engine"],
    "query_dimensions": ["region", "language", "time", "platform", "brand"],
    "coverage_gaps": ["brand:unseeded"],
    "source_pool": [],
}


CONFIG_WITH_COOP_AND_SEARCH = {
    **BASE_CONFIG,
    "source_pool": [
        source_task(
            "coop-sitemap",
            "sitemap",
            "sitemap",
            {
                "seeds": ["https://coop.example"],
                "explicit_sitemaps": ["https://coop.example/sitemap.xml"],
                "scope_mode": "site",
            },
        ),
        source_task("search-engine", "search_engine", "tool_bridge"),
    ],
}


def fake_fetcher(url, *, timeout_seconds, max_document_bytes):
    del timeout_seconds, max_document_bytes
    if url.endswith("/robots.txt"):
        payload = b"Sitemap: https://coop.example/sitemap.xml\n"
        return FetchOutcome(url, 200, "text/plain", "", payload, 0.20, None)
    if url == "https://coop.example/sitemap.xml":
        payload = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b'<url><loc>https://coop.example/products/pillow-a</loc></url>'
            b"</urlset>"
        )
        return FetchOutcome(
            url, 200, "application/xml", "", payload, 0.30, None
        )
    return FetchOutcome(url, 404, "text/plain", "", b"", 0.10, "not_found")


class MarketSchedulerPersistenceTests(unittest.TestCase):
    def test_load_reconciles_a_committed_batch_missing_from_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            state_path = Path(tmp) / "run.json"
            task = source_task("search", "search_engine", "tool_bridge")
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "ledger_path": str(ledger_path),
                    "source_pool": [task],
                },
                run_id="run-1",
            )
            leased = select_next_tasks(state)[0]
            result = {
                "batch_id": leased["lease_id"],
                "task_id": "search",
                "run_id": "run-1",
                "scope_fingerprint": "cn-pillow-market-v1",
                "metric_stage": "canonical_url",
                "time_session_id": leased["time_session_id"],
                "ledger_committed": True,
                "ledger_counts": {
                    "raw_url_observations": 1,
                    "valid_urls": 1,
                    "unique_additions": 1,
                    "total_unique_urls": 1,
                },
                "active_intervals": [[0.0, 1.0]],
                "verified_objects": [],
                "invalidations": [],
                "new_seeds": [],
                "round": {
                    "query_family": "family:search",
                    "source_class": "search_engine",
                    "new_valid_urls": 1,
                    "new_entities": 0,
                    "new_fields": 0,
                    "mostly_duplicates": False,
                },
                "end_reason": "queue_exhausted",
                "telemetry": {
                    "raw_url_observations": 1,
                    "successful_pages": 0,
                    "structured_records": 0,
                },
            }
            with SqliteUrlLedger(ledger_path) as ledger:
                with ledger.batch(
                    BatchSpec(
                        leased["lease_id"],
                        "run-1",
                        "search",
                        "tool_bridge",
                        "cn-pillow-market-v1",
                    )
                ) as writer:
                    writer.add(
                        UrlObservation(
                            "https://example.com/item/1",
                            "One",
                            "short",
                            ("searxng:bing",),
                            "search_engine",
                            "family:search",
                            "2026-08-03T00:00:00Z",
                            {},
                        )
                    )
                    writer.finish(
                        {
                            "end_reason": "queue_exhausted",
                            "raw_url_observations": 1,
                            "valid_urls": 1,
                            "unique_additions": 1,
                            "scheduler_result": result,
                        }
                    )
            save_state_atomic(state_path, state)

            recovered = load_state(state_path)

            self.assertEqual(recovered["ingested_batch_ids"], [leased["lease_id"]])
            self.assertEqual(recovered["counters"]["unique_urls"], 1)
            self.assertEqual(recovered["source_pool"][0]["status"], "exhausted")

    def test_atomic_round_trip_preserves_time_and_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.json"
            state = create_run_state(BASE_CONFIG, run_id="run-1")
            record_discovery_interval(state, 0.0, 6.74)
            state["ingested_batch_ids"] = ["batch-1"]
            save_state_atomic(path, state)
            resumed = load_state(path)
            self.assertEqual(pure_search_seconds(resumed), 6.74)
            self.assertEqual(resumed["ingested_batch_ids"], ["batch-1"])
            self.assertFalse(any(path.parent.glob(".*.tmp")))

    def test_resume_interrupts_open_leases_and_uses_new_time_session(self):
        state = create_run_state(
            {**BASE_CONFIG, "source_pool": [source_task("search", "search_engine", "tool_bridge")]},
            run_id="run-1",
        )
        select_next_tasks(state)
        old_session = state["current_time_session_id"]
        resume_state(state, session_id="after-reboot")
        self.assertEqual(state["source_pool"][0]["status"], "interrupted")
        self.assertEqual(state["current_time_session_id"], "after-reboot")
        self.assertNotEqual(old_session, state["current_time_session_id"])

    def test_invalid_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.json"
            path.write_text('{"schema_version": 999}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported-state-schema"):
                load_state(path)


class MarketSchedulerBuiltinTests(unittest.TestCase):
    def test_builtin_sitemap_summary_is_batch_not_global_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = create_run_state(
                {
                    **CONFIG_WITH_COOP_AND_SEARCH,
                    "ledger_path": str(Path(tmp) / "run.sqlite"),
                },
                run_id="run-1",
            )
            self.assertEqual(select_next_tasks(state)[0]["task_id"], "coop-sitemap")
            result = run_builtin_task(
                state, "coop-sitemap", sitemap_fetcher=fake_fetcher
            )
            self.assertEqual(result["end_reason"], "queue_exhausted")
            self.assertEqual(result["telemetry"]["raw_url_observations"], 1)
            ingest_batch_result(state, result)
            self.assertEqual(state["status"], "running")
            self.assertEqual(select_next_tasks(state)[0]["task_id"], "search-engine")


class MarketSchedulerCliTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["PYTHONUTF8"] = "1"
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
        )

    def test_next_cli_emits_tool_bridge_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "run.json"
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "source_pool": [
                        source_task("search-engine", "search_engine", "tool_bridge")
                    ],
                },
                run_id="run-1",
            )
            save_state_atomic(state_path, state)
            completed = self._run("next", "--state", str(state_path))
            envelope = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(envelope["tasks"][0]["adapter"], "tool_bridge")
            self.assertEqual(envelope["tasks"][0]["run_id"], "run-1")

    def test_ingest_browser_batch_cli_has_clean_output_and_keeps_caller_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "run.json"
            batch_path = root / "batch.json"
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "run_type": "catalog_enumeration",
                    "ledger_path": str(root / "run.sqlite"),
                },
                run_id="run-1",
            )
            save_state_atomic(state_path, state)
            batch_path.write_text(
                json.dumps(JD_READY_BATCH, ensure_ascii=False), encoding="utf-8"
            )

            completed = self._run(
                "ingest-browser-batch",
                "--state",
                str(state_path),
                "--batch",
                str(batch_path),
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            output = json.loads(completed.stdout)
            self.assertEqual(output["marketplace"]["unique_candidates"], 1)
            self.assertTrue(batch_path.exists())
            persisted = state_path.read_text(encoding="utf-8")
            combined = completed.stdout + completed.stderr + persisted
            for forbidden in (
                "items",
                "100123456789",
                "透明防摔手机壳",
                "https://item.jd.com",
                "https://search.jd.com",
            ):
                self.assertNotIn(forbidden, combined)

    def test_finalize_cli_rejects_incomplete_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "run.json"
            save_state_atomic(
                state_path, create_run_state(BASE_CONFIG, run_id="run-1")
            )
            completed = self._run("finalize", "--state", str(state_path))
            self.assertEqual(completed.returncode, 3)
            self.assertIn("global-stop-not-satisfied", completed.stderr)

    def test_migrate_state_cli_requires_an_explicit_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "legacy.json"
            legacy = create_run_state(BASE_CONFIG, run_id="legacy-1")
            legacy["schema_version"] = 1
            legacy.pop("run_type")
            legacy.pop("search_limit_seconds")
            legacy.pop("scope_completion")
            state_path.write_text(
                json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
            )

            rejected = self._run("status", "--state", str(state_path))
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("unsupported-state-schema", rejected.stderr)

            migrated = self._run("migrate-state", "--state", str(state_path))
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            state = load_state(state_path)
            self.assertEqual(state["schema_version"], 2)
            self.assertEqual(state["run_type"], "open_web_research")
            self.assertEqual(state["search_limit_seconds"], 600.0)

    def test_help_lists_lifecycle_commands(self):
        completed = self._run("--help")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for command in (
            "start",
            "next",
            "ingest",
            "ingest-browser-batch",
            "run-builtins",
            "status",
            "finalize",
            "resume",
            "migrate-state",
        ):
            self.assertIn(command, completed.stdout)


if __name__ == "__main__":
    unittest.main()
