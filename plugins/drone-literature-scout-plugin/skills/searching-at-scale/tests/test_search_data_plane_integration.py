from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.market_scheduler import (
    create_run_state,
    evaluate_global_status,
    ingest_browser_batch,
    run_backend_tasks,
)
from scripts.normalize_and_dedupe import SqliteUrlLedger
from test_marketplace_candidates import JD_READY_BATCH


def source_task(
    task_id: str,
    adapter: str,
    source_class: str,
    *,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "source_class": source_class,
        "backend": adapter,
        "query_family": f"family:{adapter}",
        "query_dimensions": ["platform"],
        "coverage_targets": [],
        "adapter": adapter,
        "payload": payload or {},
        "status": "pending",
        "score_inputs": {},
    }


def config(
    ledger_path: Path,
    tasks: list[dict[str, object]],
    *,
    run_type: str = "open_web_research",
) -> dict[str, object]:
    return {
        "topic": "universal research",
        "scope_fingerprint": "integration-scope-v1",
        "ledger_path": str(ledger_path),
        "run_type": run_type,
        "applicable_sources": sorted(
            {str(task["source_class"]) for task in tasks}
        ),
        "query_dimensions": ["platform"],
        "coverage_gaps": [],
        "source_pool": tasks,
    }


def adapter_for(channel: str, url: str = "https://example.com/item/1"):
    def adapter(payload):
        yield {
            "type": "url",
            "url": url,
            "title": "One",
            "snippet": "compact",
            "channels": [channel],
            "source_class": payload["source_class"],
            "query_family": payload["query_family"],
            "observed_at": "2026-08-03T00:00:00Z",
            "metadata": {},
        }
        yield {
            "type": "summary",
            "end_reason": "queue_exhausted",
            "metric_stage": "canonical_url",
            "telemetry": {
                "raw_url_observations": 1,
                "successful_pages": 0,
                "structured_records": 0,
            },
            "new_seeds": [],
            "round": {
                "query_family": payload["query_family"],
                "source_class": payload["source_class"],
                "new_valid_urls": 1,
                "new_entities": 0,
                "new_fields": 0,
                "mostly_duplicates": False,
            },
        }

    return adapter


class SearchDataPlaneIntegrationTests(unittest.TestCase):
    def test_edge_batch_uses_sqlite_without_spool_or_candidate_pool_in_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = create_run_state(
                config(root / "run.sqlite", [], run_type="catalog_enumeration"),
                run_id="run-1",
            )
            ingest_browser_batch(state, JD_READY_BATCH)
            self.assertFalse((root / "spool").exists())
            with SqliteUrlLedger(root / "run.sqlite") as ledger:
                self.assertEqual(ledger.marketplace_candidate_count(), 1)
            serialized = json.dumps(state, ensure_ascii=False)
            self.assertNotIn("100123456789", serialized)
            self.assertNotIn("https://item.jd.com", serialized)

    def test_same_adapter_group_ingests_intermediate_total_snapshots(self):
        def unique_adapter(payload):
            yield from adapter_for(
                "engine:fixture",
                url=f"https://example.com/{payload['item']}",
            )(payload)

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            tasks = [
                source_task(
                    "search-a",
                    "searxng",
                    "search_engine",
                    payload={
                        "base_url": "http://127.0.0.1:1",
                        "item": "a",
                    },
                ),
                source_task(
                    "search-b",
                    "searxng",
                    "search_engine",
                    payload={
                        "base_url": "http://127.0.0.1:1",
                        "item": "b",
                    },
                ),
            ]
            state = create_run_state(config(ledger_path, tasks), run_id="run-1")

            results = run_backend_tasks(
                state,
                max_tasks=2,
                adapters={"searxng": unique_adapter},
                spool_dir=Path(tmp) / "spool",
            )

            self.assertEqual(len(results), 2)
            self.assertEqual(state["counters"]["unique_urls"], 2)
            self.assertEqual(state["failures"], [])
            self.assertEqual(
                {task["status"] for task in state["source_pool"]},
                {"exhausted"},
            )

    def test_three_backends_merge_provenance_without_urls_in_json_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            tasks = [
                source_task("a", "adapter_a", "search_engine"),
                source_task("b", "adapter_b", "open_index"),
                source_task("c", "adapter_c", "sitemap"),
            ]
            state = create_run_state(config(ledger_path, tasks), run_id="run-1")
            results = run_backend_tasks(
                state,
                max_tasks=3,
                adapters={
                    "adapter_a": adapter_for("engine:a"),
                    "adapter_b": adapter_for("index:b"),
                    "adapter_c": adapter_for("map:c"),
                },
                spool_dir=Path(tmp) / "spool",
            )
            self.assertEqual(len(results), 3)
            with SqliteUrlLedger(ledger_path) as ledger:
                self.assertEqual(ledger.stats().unique_urls, 1)
                provenance = ledger.provenance_for("https://example.com/item/1")
                self.assertIsNotNone(provenance)
                self.assertEqual(
                    provenance.discovery_channels,
                    ("engine:a", "index:b", "map:c"),
                )
            serialized = json.dumps(state, ensure_ascii=False).casefold()
            for forbidden in ("https://example.com/item/1", "title", "snippet", "html", "secret"):
                self.assertNotIn(forbidden, serialized)

    def test_searxng_unavailable_does_not_stop_other_backend(self):
        class UnavailableRuntime:
            @contextmanager
            def searxng(self):
                yield SimpleNamespace(
                    available=False,
                    reason="docker_unavailable",
                    base_url=None,
                )

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            tasks = [
                source_task("search", "searxng", "search_engine"),
                source_task("map", "sitemap", "sitemap"),
            ]
            state = create_run_state(config(ledger_path, tasks), run_id="run-1")
            results = run_backend_tasks(
                state,
                max_tasks=2,
                adapters={"sitemap": adapter_for("map")},
                runtime_manager_factory=lambda **kwargs: UnavailableRuntime(),
                spool_dir=Path(tmp) / "spool",
            )
            statuses = {task["task_id"]: task["status"] for task in state["source_pool"]}
            self.assertEqual(len(results), 1)
            self.assertEqual(statuses, {"map": "exhausted", "search": "unavailable"})
            self.assertEqual(state["failures"][0]["error_category"], "docker_unavailable")

    def test_keyboard_interrupt_marks_the_lease_interrupted(self):
        def interrupted(payload):
            del payload
            raise KeyboardInterrupt
            yield

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            tasks = [source_task("stop", "interrupting", "search_engine")]
            state = create_run_state(config(ledger_path, tasks), run_id="run-1")
            with self.assertRaises(KeyboardInterrupt):
                run_backend_tasks(
                    state,
                    adapters={"interrupting": interrupted},
                    spool_dir=Path(tmp) / "spool",
                )
            self.assertEqual(state["source_pool"][0]["status"], "interrupted")

    def test_bounded_scope_evidence_completes_the_run(self):
        def bounded(payload):
            del payload
            summary = next(adapter_for("dataset")({
                "source_class": "dataset",
                "query_family": "family:dataset",
            }))
            del summary
            yield {
                "type": "summary",
                "end_reason": "queue_exhausted",
                "metric_stage": "canonical_url",
                "telemetry": {
                    "raw_url_observations": 0,
                    "successful_pages": 1,
                    "structured_records": 1,
                },
                "new_seeds": [],
                "round": {
                    "query_family": "family:dataset",
                    "source_class": "dataset",
                    "new_valid_urls": 0,
                    "new_entities": 0,
                    "new_fields": 0,
                    "mostly_duplicates": False,
                },
                "scope_completion": {
                    "boundary": "pages:0..0",
                    "expected_pages": 1,
                    "completed_pages": 1,
                    "failed_pages": 0,
                },
                "deterministic_scope_complete": True,
            }

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            tasks = [source_task("dataset", "dataset", "dataset")]
            state = create_run_state(
                config(ledger_path, tasks, run_type="bounded_dataset_extract"),
                run_id="run-1",
            )
            run_backend_tasks(
                state,
                adapters={"dataset": bounded},
                spool_dir=Path(tmp) / "spool",
            )
            self.assertEqual(evaluate_global_status(state), "deterministic_scope_complete")
            self.assertEqual(state["scope_completion"]["completed_pages"], 1)

    def test_query_templates_get_adapter_specific_default_concurrency(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = create_run_state(
                {
                    **config(Path(tmp) / "run.sqlite", []),
                    "query_matrix": {"topics": ["pillow"]},
                    "source_templates": [
                        {
                            "backend": "searxng",
                            "source_class": "search_engine",
                            "query_family": "broad",
                            "query_dimensions": ["platform"],
                            "coverage_targets": [],
                            "adapter": "searxng",
                            "payload_template": {"query": "{query}"},
                        }
                    ],
                },
                run_id="run-1",
            )
            concurrency = state["source_pool"][0]["concurrency"]
            self.assertEqual(concurrency["tier"], 2)
            self.assertEqual(concurrency["tiers"], [2, 4])


if __name__ == "__main__":
    unittest.main()
