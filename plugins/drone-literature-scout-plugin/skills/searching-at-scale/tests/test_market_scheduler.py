from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.market_scheduler import (
    apply_channel_signal,
    _bounded_edge_payload,
    cumulative_verified_count,
    create_run_state,
    _record_edge_backend_failure,
    _ensure_marketplace_query_tasks,
    _set_platform_cooling,
    enqueue_feedback_tasks,
    ensure_query_tasks,
    evaluate_global_status,
    expand_query_tasks,
    finalize_run,
    ingest_browser_batch,
    ingest_batch_result,
    pure_search_seconds,
    rank_source_tasks,
    record_task_failure,
    record_discovery_interval,
    run_backend_tasks,
    select_next_tasks,
)
from scripts.backend_runner import AdapterFailure
import scripts.backend_runner as backend_runner
from scripts.domestic_marketplace_query import EDGE_PAYLOAD_KEYS
from scripts.jd_continuation import new_continuation, page_verified
from scripts.marketplace_candidates import iter_browser_batch_events
from scripts.edge_marketplace_query import iter_edge_marketplace_events
from test_marketplace_candidates import JD_READY_BATCH
from scripts.normalize_and_dedupe import (
    BatchSpec,
    SqliteUrlLedger,
    UrlObservation,
)


BASE_CONFIG = {
    "topic": "枕头",
    "scope_fingerprint": "cn-pillow-market-v1",
    "ledger_path": str(
        Path(tempfile.gettempdir()) / "searching-at-scale-test-unused.sqlite"
    ),
    "applicable_sources": ["sitemap", "search_engine"],
    "query_dimensions": ["region", "language", "time", "platform", "brand"],
    "coverage_gaps": ["brand:unseeded"],
    "source_pool": [],
}


_LEDGER_TEMP_DIRS: list[tempfile.TemporaryDirectory[str]] = []


def temporary_ledger_path() -> str:
    directory = tempfile.TemporaryDirectory()
    _LEDGER_TEMP_DIRS.append(directory)
    return str(Path(directory.name) / "run.sqlite")


def edge_projection_events(
    payload: dict[str, object], *, cursor_status: str = "advanced", has_next: bool = False
):
    request = {
        "platform": payload["platform"],
        "query": payload.get("query", payload["query_family"]),
        "query_family": payload["query_family"],
        "cursor": payload["cursor"],
        "user_data_dir": payload.get("user_data_dir", ""),
        "deadline_seconds": payload.get("deadline_seconds", 600.0),
        "max_items": payload.get("max_items", 1000),
        "session_action": payload.get("session_action", "start"),
        "pagination_enabled": payload.get("pagination_enabled", False),
    }
    batch = deepcopy(JD_READY_BATCH)
    page_number = request["cursor"]["page_number"]
    batch["platform"] = request["platform"]
    batch["query_family"] = request["query_family"]
    batch["cursor"] = {
        **batch["cursor"],
        "cursor_id": request["cursor"]["cursor_id"],
        "page_number": page_number,
        "status": cursor_status,
    }
    batch["observed_page_number"] = page_number
    batch["diagnostics"]["observed_page_number"] = page_number
    batch["has_next_page"] = has_next
    yield from iter_edge_marketplace_events(
        request, worker_runner=lambda normalized, **kwargs: batch
    )


def tearDownModule() -> None:
    for directory in _LEDGER_TEMP_DIRS:
        directory.cleanup()
    _LEDGER_TEMP_DIRS.clear()


def pending_search_task() -> dict[str, object]:
    return {
        "task_id": "search-engine",
        "source_class": "search_engine",
        "backend": "public-search",
        "query_family": "brand-model-search",
        "query_dimensions": ["platform", "brand"],
        "coverage_targets": ["brand:unseeded"],
        "adapter": "tool_bridge",
        "payload": {"query": "枕头 品牌 型号"},
        "status": "pending",
        "score_inputs": {},
        "concurrency": {"tier": 24, "tool_limit": 40, "host_limit": 40},
    }


def source_task(
    task_id: str,
    source_class: str,
    adapter: str,
    *,
    score_inputs: dict[str, float] | None = None,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "source_class": source_class,
        "backend": task_id,
        "query_family": f"family:{task_id}",
        "query_dimensions": ["platform"],
        "coverage_targets": [f"platform:{source_class}"],
        "adapter": adapter,
        "payload": {},
        "status": "pending",
        "score_inputs": score_inputs or {},
        "concurrency": {"tier": 24, "tool_limit": 40, "host_limit": 40},
    }


class MarketSchedulerStateTests(unittest.TestCase):
    def resilient_jd_state(
        self,
        *,
        wall_deadline: float | None = None,
        jd_debug_page_limit: int | None = None,
        topics: tuple[str, ...] | None = None,
    ) -> dict[str, object]:
        topics = topics or ("机械键盘",)
        config = {
            **BASE_CONFIG,
            "run_type": "catalog_enumeration",
            "ledger_path": temporary_ledger_path(),
            "applicable_sources": ["marketplace_list"],
            "marketplace_plan": {
                "topic_dimensions": [{"topic": topic} for topic in topics],
                "platforms": ["jd"],
                "batch_size": 8,
                "jd_slow_lane": True,
            },
            "jd_continuation": new_continuation(topics),
            "jd_full_window": True,
            "source_pool": [],
        }
        if wall_deadline is not None:
            config["wall_deadline"] = wall_deadline
        if jd_debug_page_limit is not None:
            config["jd_debug_page_limit"] = jd_debug_page_limit
        return create_run_state(config, run_id=f"jd-resilient-{len(_LEDGER_TEMP_DIRS)}")

    def fail_current_jd_task(
        self, state: dict[str, object], category: str
    ) -> None:
        selected = select_next_tasks(state, max_tasks=1)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["adapter"], "edge_marketplace")
        _record_edge_backend_failure(
            state,
            selected[0],
            AdapterFailure(category, retryable=True),
        )

    def test_jd_continuation_materializes_only_current_page(self):
        """An eager scheduler would queue future JD pages or generic searches."""
        state = self.resilient_jd_state()

        self.assertEqual(len(state["source_pool"]), 1)
        task = state["source_pool"][0]
        self.assertEqual(task["adapter"], "edge_marketplace")
        self.assertEqual(task["payload"]["query"], "机械键盘")
        self.assertEqual(task["payload"]["cursor"]["page_number"], 1)
        self.assertEqual(state["jd_continuation"]["page_number"], 1)

    def test_transient_empty_reprojects_then_reloads_same_page(self):
        """Soft recovery must never skip the failed page or rotate prematurely."""
        state = self.resilient_jd_state()

        self.fail_current_jd_task(state, "pagination_page_transient_empty")
        first_recovery = select_next_tasks(state, max_tasks=1)[0]
        self.assertEqual(first_recovery["payload"]["session_action"], "recover")
        self.assertEqual(first_recovery["payload"]["cursor"]["page_number"], 1)
        self.assertEqual(state["jd_continuation"]["recovery_stage"], "reproject")
        _record_edge_backend_failure(
            state,
            first_recovery,
            AdapterFailure("pagination_page_transient_empty", retryable=True),
        )
        second_recovery = select_next_tasks(state, max_tasks=1)[0]
        self.assertEqual(second_recovery["payload"]["session_action"], "recover")
        self.assertEqual(second_recovery["payload"]["cursor"]["page_number"], 1)
        self.assertEqual(state["jd_continuation"]["recovery_stage"], "reload")

        with SqliteUrlLedger(state["ledger_path"]) as ledger:
            self.assertEqual(
                [
                    (row["recovery_stage"], row["attempt"], row["disposition"])
                    for row in ledger.recovery_events()
                ],
                [
                    ("initial", 0, "retry_same_page"),
                    ("reproject", 1, "retry_same_page"),
                ],
            )
            self.assertEqual(ledger.marketplace_candidate_count(), 0)

    def test_soft_page_failure_reaches_reproject_adapter_without_platform_probe(self):
        """Marking a soft continuation source blocked would deadlock the next round."""
        calls: list[tuple[int, str]] = []

        @contextmanager
        def session_adapter():
            def adapter(payload):
                page_number = payload["cursor"]["page_number"]
                session_action = payload["session_action"]
                calls.append((page_number, session_action))
                if (page_number, session_action) == (2, "next"):
                    raise AdapterFailure(
                        "pagination_page_transient_empty", retryable=True
                    )
                yield from edge_projection_events(
                    payload,
                    has_next=(page_number == 1),
                )

            yield adapter

        state = self.resilient_jd_state()
        with tempfile.TemporaryDirectory() as tmp, patch(
            "scripts.market_scheduler.edge_marketplace_session_adapter",
            session_adapter,
        ):
            spool = Path(tmp) / "spool"
            run_backend_tasks(state, max_tasks=1, spool_dir=spool)
            run_backend_tasks(state, max_tasks=1, spool_dir=spool)

            self.assertEqual(
                state["marketplace_plan"]["platform_recovery_probe"]["jd"],
                False,
            )
            run_backend_tasks(state, max_tasks=1, spool_dir=spool)

        self.assertEqual(calls, [(1, "start"), (2, "next"), (2, "recover")])
        self.assertEqual(state["jd_continuation"]["page_number"], 3)

    @unittest.skipUnless(os.name == "nt", "Windows path-length regression")
    def test_owned_spool_path_is_bounded_for_long_ledger_parent(self):
        """The live run's 274-character NDJSON path must remain below MAX_PATH."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            component_length = max(16, 145 - len(str(root)) - 1)
            self.assertLess(component_length, 240)
            ledger_parent = root / ("x" * component_length)
            ledger_parent.mkdir()
            ledger_path = ledger_parent / "run.sqlite"
            state = self.resilient_jd_state()
            state["ledger_path"] = str(ledger_path)
            state["run_id"] = "jd-route1-222-20260809T225800-a47c"
            legacy_spool = ledger_parent / (
                f"searching-at-scale-{state['run_id']}-abcdefgh"
            )
            legacy_file = legacy_spool / (("f" * 64) + ".ndjson")
            self.assertGreaterEqual(len(str(legacy_file)), 260)

            created_spools: list[Path] = []
            real_mkdtemp = tempfile.mkdtemp

            def observed_mkdtemp(*args, **kwargs):
                created = Path(real_mkdtemp(*args, **kwargs))
                created_spools.append(created)
                return str(created)

            with patch(
                "scripts.market_scheduler.tempfile.mkdtemp",
                side_effect=observed_mkdtemp,
            ):
                results = run_backend_tasks(
                    state,
                    max_tasks=1,
                    edge_session_adapter=lambda payload: edge_projection_events(
                        payload
                    ),
                )

            self.assertEqual(len(results), 1)
            self.assertEqual(len(created_spools), 1)
            self.assertEqual(created_spools[0].parent, ledger_parent)
            spool_file_bound = created_spools[0] / (("f" * 64) + ".ndjson")
            self.assertLess(len(str(spool_file_bound)), 260)
            self.assertFalse(created_spools[0].exists())
            self.assertTrue(ledger_path.exists())

    def test_unexpected_backend_exception_interrupts_owned_lease(self):
        state = self.resilient_jd_state()
        with tempfile.TemporaryDirectory() as tmp, patch(
            "scripts.market_scheduler.run_adapter_group",
            side_effect=FileNotFoundError("owned spool missing"),
        ), self.assertRaisesRegex(FileNotFoundError, "owned spool missing"):
            try:
                run_backend_tasks(
                    state,
                    max_tasks=1,
                    spool_dir=Path(tmp) / "spool",
                    edge_session_adapter=lambda payload: iter(()),
                )
            finally:
                task = state["source_pool"][0]
                self.assertEqual(task["status"], "interrupted")
                self.assertEqual(
                    task["interrupted_lease_id"], task["lease_id"]
                )

    def test_family_failures_rotate_without_blocking_jd(self):
        """Structure/session failures abandon only the current query family."""
        for category in (
            "browser_page_structure_changed",
            "pagination_session_missing",
        ):
            with self.subTest(category=category):
                state = self.resilient_jd_state()
                self.fail_current_jd_task(state, category)

                self.assertEqual(
                    state["marketplace_plan"]["platform_health"]["jd"],
                    "healthy",
                )
                next_task = select_next_tasks(state, max_tasks=1)[0]
                self.assertEqual(next_task["payload"]["query"], "机械键盘 自营")
                self.assertEqual(next_task["payload"]["cursor"]["page_number"], 1)

    def test_hard_jd_failures_block_platform_without_recovery(self):
        """Risk or login failures must close the JD lane immediately."""
        for category in (
            "browser_captcha_required",
            "browser_rate_limited",
            "browser_authentication_required",
            "authentication_required",
        ):
            with self.subTest(category=category):
                state = self.resilient_jd_state()
                self.assertIn("jd_continuation", state)
                before = deepcopy(state["jd_continuation"])
                self.fail_current_jd_task(state, category)

                self.assertEqual(
                    state["marketplace_plan"]["platform_health"]["jd"],
                    "blocked",
                )
                self.assertEqual(state["jd_continuation"], before)
                self.assertEqual(select_next_tasks(state, max_tasks=1), ())
                with SqliteUrlLedger(state["ledger_path"]) as ledger:
                    event = ledger.recovery_events()[0]
                    self.assertEqual(event["disposition"], "hard_block")

    def test_hard_block_survives_explicit_recovery_ledger_failure(self):
        state = self.resilient_jd_state()
        task = select_next_tasks(state, max_tasks=1)[0]
        with patch.object(
            SqliteUrlLedger,
            "record_marketplace_recovery",
            side_effect=OSError("disk full"),
        ), self.assertRaisesRegex(RuntimeError, "recovery-ledger-write-failed"):
            _record_edge_backend_failure(
                state,
                task,
                AdapterFailure("browser_captcha_required", retryable=False),
            )
        self.assertEqual(
            state["marketplace_plan"]["platform_health"]["jd"], "blocked"
        )

    def test_same_failure_callback_is_claimed_once_per_task_lease(self):
        cases = (
            (
                "pagination_page_transient_empty",
                "retry_same_page",
                lambda plan: (plan["recovery_stage"], plan["recovery_attempt"]),
                ("reproject", 1),
            ),
            (
                "browser_page_structure_changed",
                "rotate_family",
                lambda plan: (plan["family_index"], tuple(plan["abandoned_families"])),
                (1, ("机械键盘",)),
            ),
            (
                "browser_captcha_required",
                "hard_block",
                lambda plan: (plan["recovery_stage"], plan["recovery_attempt"]),
                ("initial", 0),
            ),
        )
        for category, disposition, continuation_view, expected in cases:
            with self.subTest(category=category):
                state = self.resilient_jd_state()
                task = select_next_tasks(state, max_tasks=1)[0]
                failure = AdapterFailure(category, retryable=True)

                _record_edge_backend_failure(state, task, failure)
                first_view = continuation_view(state["jd_continuation"])
                _record_edge_backend_failure(state, task, failure)

                self.assertEqual(first_view, expected)
                self.assertEqual(continuation_view(state["jd_continuation"]), expected)
                current = next(
                    item
                    for item in state["source_pool"]
                    if item["task_id"] == task["task_id"]
                )
                self.assertNotIn(current["status"], {"leased", "interrupted"})
                with SqliteUrlLedger(state["ledger_path"]) as ledger:
                    events = ledger.recovery_events(run_id=str(state["run_id"]))
                    self.assertEqual(len(events), 1)
                    self.assertEqual(events[0]["disposition"], disposition)
                    summary = ledger.marketplace_recovery_summary(
                        run_id=str(state["run_id"])
                    )
                total = sum(summary["recoveries"].values())
                total += sum(
                    sum(categories.values())
                    for categories in summary["abandoned_families"].values()
                )
                total += sum(
                    sum(categories.values())
                    for categories in summary["hard_blocks"].values()
                )
                self.assertEqual(total, 1)

    def test_finalize_query_family_counts_are_scoped_to_current_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "shared.sqlite"
            sku = "100123456789"
            with SqliteUrlLedger(ledger_path) as ledger:
                def commit_cursor(
                    *, run_id: str, batch_id: str, cursor_id: str
                ) -> None:
                    spec = BatchSpec(
                        batch_id=batch_id,
                        run_id=run_id,
                        task_id=f"task:{batch_id}",
                        adapter="edge_marketplace",
                        scope_fingerprint="cn-pillow-market-v1",
                    )
                    with ledger.batch(spec) as writer:
                        outcome = writer.add(
                            UrlObservation(
                                url=f"https://item.jd.com/{sku}.html",
                                title="机械键盘",
                                snippet="",
                                channels=("edge:jd",),
                                source_class="marketplace_list",
                                query_family="机械键盘",
                                observed_at="2026-08-09T00:00:00Z",
                                metadata={"platform": "jd", "product_id": sku},
                            )
                        )
                        writer.finish(
                            {
                                "end_reason": "partial",
                                "raw_url_observations": 1,
                                "valid_urls": 1,
                                "unique_additions": int(not outcome.duplicate),
                                "unique_candidate_additions": int(
                                    outcome.candidate_added
                                ),
                            }
                        )
                    ledger.record_marketplace_cursor(
                        cursor_id=cursor_id,
                        source="edge:jd",
                        query_family="机械键盘",
                        status="advanced",
                        last_batch_id=batch_id,
                        unique_candidate_additions=int(outcome.candidate_added),
                    )

                commit_cursor(
                    run_id="run-old",
                    batch_id="old-shared",
                    cursor_id="jd:shared",
                )
                commit_cursor(
                    run_id="run-old",
                    batch_id="old-only",
                    cursor_id="jd:old-only",
                )
                commit_cursor(
                    run_id="run-new",
                    batch_id="new-shared",
                    cursor_id="jd:shared",
                )

            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "run_type": "catalog_enumeration",
                    "ledger_path": str(ledger_path),
                    "applicable_sources": ["marketplace_list"],
                },
                run_id="run-new",
            )
            record_discovery_interval(state, 0.0, 600.0, session_id="final-window")

            final = finalize_run(state)

            self.assertEqual(
                final["query_family_counts"],
                {"机械键盘": {"successful_pages": 1, "new_skus": 0}},
            )

    def test_finalize_returns_fixed_recovery_summary_and_closes_leases(self):
        state = self.resilient_jd_state()
        ledger_path = Path(state["ledger_path"])
        sku = "100123456789"
        with SqliteUrlLedger(ledger_path) as ledger:
            for index in range(2):
                spec = BatchSpec(
                    batch_id=f"family-batch-{index}",
                    run_id=str(state["run_id"]),
                    task_id=f"family-task-{index}",
                    adapter="edge_marketplace",
                    scope_fingerprint=str(state["scope_fingerprint"]),
                )
                with ledger.batch(spec) as writer:
                    outcome = writer.add(
                        UrlObservation(
                            url=f"https://item.jd.com/{sku}.html",
                            title="机械键盘",
                            snippet="",
                            channels=("edge:jd",),
                            source_class="marketplace_list",
                            query_family="机械键盘",
                            observed_at="2026-08-09T00:00:00Z",
                            metadata={"platform": "jd", "product_id": sku},
                        )
                    )
                    writer.finish(
                        {
                            "end_reason": "partial",
                            "raw_url_observations": 1,
                            "valid_urls": 1,
                            "unique_additions": int(not outcome.duplicate),
                            "unique_candidate_additions": int(outcome.candidate_added),
                        }
                    )
                ledger.record_marketplace_cursor(
                    cursor_id=f"jd:family-{index}",
                    source="edge:jd",
                    query_family="机械键盘",
                    status="advanced",
                    last_batch_id=spec.batch_id,
                    unique_candidate_additions=int(outcome.candidate_added),
                )
            for category, disposition in (
                ("pagination_page_transient_empty", "retry_same_page"),
                ("browser_page_structure_changed", "rotate_family"),
                ("browser_captcha_required", "hard_block"),
            ):
                ledger.record_marketplace_recovery(
                    run_id=str(state["run_id"]),
                    platform="jd",
                    query_family="机械键盘",
                    page_number=1,
                    recovery_stage="initial",
                    attempt=0,
                    category=category,
                    disposition=disposition,
                )

        state["source_pool"][0]["status"] = "leased"
        state["source_pool"].append(
            {**pending_search_task(), "task_id": "interrupted-task", "status": "interrupted"}
        )
        record_discovery_interval(state, 0.0, 600.0, session_id="final-window")
        final = finalize_run(state)

        self.assertEqual(
            final["query_family_counts"],
            {"机械键盘": {"successful_pages": 2, "new_skus": 1}},
        )
        self.assertEqual(final["recoveries"], {"机械键盘": 1})
        self.assertEqual(
            final["abandoned_families"],
            {"机械键盘": {"browser_page_structure_changed": 1}},
        )
        self.assertEqual(
            final["hard_blocks"],
            {"机械键盘": {"browser_captcha_required": 1}},
        )
        self.assertFalse(
            any(
                task["status"] in {"leased", "interrupted"}
                for task in final["source_pool"]
            )
        )
        serialized = json.dumps(
            {
                key: final[key]
                for key in (
                    "query_family_counts",
                    "recoveries",
                    "abandoned_families",
                    "hard_blocks",
                )
            },
            ensure_ascii=False,
        ).casefold()
        for forbidden in ("html", "cookie", "https://", "items"):
            self.assertNotIn(forbidden, serialized)

    def test_wall_budget_guard_refuses_new_jd_task(self):
        """A request that cannot fit pacing, deadline, and cleanup stays unleased."""
        with patch("scripts.market_scheduler.time.perf_counter", return_value=100.0):
            state = self.resilient_jd_state(wall_deadline=191.9)

        self.assertEqual(state["source_pool"], [])
        self.assertTrue(state["wall_budget_exhausted"])

    def test_debug_page_limit_is_applied_outside_continuation(self):
        """The outer debug cap prevents page two without mutating Task 1 schema."""
        state = self.resilient_jd_state(jd_debug_page_limit=1)
        self.assertIn("jd_continuation", state)
        state["source_pool"][0]["status"] = "exhausted"
        page_verified(state["jd_continuation"])

        self.assertEqual(ensure_query_tasks(state), 0)
        self.assertEqual(len(state["source_pool"]), 1)
        self.assertNotIn("debug_page_limit", state["jd_continuation"])

    def test_debug_page_limit_rotates_to_next_topic(self):
        """Reaching the per-topic page cap advances to the next topic, not a dead-end."""
        def advanced_adapter(payload):
            yield from edge_projection_events(payload, has_next=True)

        state = self.resilient_jd_state(
            jd_debug_page_limit=1,
            topics=("机械键盘", "青轴"),
        )
        run_backend_tasks(
            state,
            adapters={"edge_marketplace": advanced_adapter},
            max_tasks=1,
        )

        next_task = select_next_tasks(state, max_tasks=1)[0]
        self.assertEqual(next_task["payload"]["query"], "青轴")
        self.assertEqual(next_task["payload"]["cursor"]["page_number"], 1)
        self.assertEqual(next_task["payload"]["session_action"], "start")
        self.assertTrue(state["jd_debug_page_limit_reached"])
        self.assertEqual(state["jd_continuation"]["topic_index"], 1)

    def test_advanced_jd_page_moves_continuation_to_next_page(self):
        """A verified result must advance before another task is materialized."""
        def advanced_adapter(payload):
            yield from edge_projection_events(payload, has_next=True)

        state = self.resilient_jd_state()
        run_backend_tasks(
            state,
            adapters={"edge_marketplace": advanced_adapter},
            max_tasks=1,
        )

        self.assertEqual(state["jd_continuation"]["page_number"], 2)
        next_task = select_next_tasks(state, max_tasks=1)[0]
        self.assertEqual(next_task["payload"]["cursor"]["page_number"], 2)
        self.assertEqual(next_task["payload"]["session_action"], "next")

    def test_natural_jd_end_rotates_to_next_query_family(self):
        """A natural last page abandons the family without blocking the platform."""
        def exhausted_adapter(payload):
            yield from edge_projection_events(payload, cursor_status="exhausted")

        state = self.resilient_jd_state()
        run_backend_tasks(
            state,
            adapters={"edge_marketplace": exhausted_adapter},
            max_tasks=1,
        )

        self.assertEqual(
            state["marketplace_plan"]["platform_health"]["jd"], "healthy"
        )
        next_task = select_next_tasks(state, max_tasks=1)[0]
        self.assertEqual(next_task["payload"]["query"], "机械键盘 自营")
        self.assertEqual(next_task["payload"]["cursor"]["page_number"], 1)

    def test_edge_pages_rank_in_numeric_order(self):
        tasks = []
        for page_number in (1, 10, 2):
            task = source_task(
                f"edge-marketplace:jd:pillow:page-{page_number}",
                "marketplace_list",
                "edge_marketplace",
            )
            task["backend"] = "edge:jd"
            task["payload"] = {
                "platform": "jd",
                "query": "枕头",
                "query_family": "枕头:default",
                "cursor": {
                    "cursor_id": "jd:pillow",
                    "ordinal": 0,
                    "page_number": page_number,
                },
                "user_data_dir": "",
                "deadline_seconds": 45.0,
                "max_items": 100,
                "session_action": "start",
                "pagination_enabled": False,
            }
            tasks.append(task)
        state = create_run_state(
            {
                **BASE_CONFIG,
                "run_type": "catalog_enumeration",
                "applicable_sources": ["marketplace_list"],
                "source_pool": tasks,
            },
            run_id="numeric-page-order-run",
        )

        ranked = rank_source_tasks(state)

        self.assertEqual(
            [task["payload"]["cursor"]["page_number"] for task in ranked],
            [1, 2, 10],
        )

    def test_edge_payload_deadline_is_capped_to_remaining_search_budget(self):
        payload = {
            "platform": "jd",
            "query": "枕头",
            "query_family": "枕头:default",
            "cursor": {"cursor_id": "jd:pillow", "ordinal": 0, "page_number": 3},
            "user_data_dir": "",
            "deadline_seconds": 600.0,
            "max_items": 1000,
            "session_action": "start",
            "pagination_enabled": False,
        }

        bounded = _bounded_edge_payload(payload, remaining_seconds=7.5)

        self.assertEqual(bounded["deadline_seconds"], 7.5)
        self.assertEqual(payload["deadline_seconds"], 600.0)

    def test_equal_score_leases_cover_distinct_adapters_before_filling(self):
        tasks = [
            source_task("a-edge-1", "marketplace_list", "edge_marketplace"),
            source_task("a-edge-2", "marketplace_list", "edge_marketplace"),
            source_task("b-search", "search_engine", "searxng"),
            source_task("c-history", "open_index", "common_crawl"),
        ]
        state = create_run_state(
            {
                **BASE_CONFIG,
                "ledger_path": temporary_ledger_path(),
                "source_pool": tasks,
            },
            run_id="source-fair-run",
        )

        selected = select_next_tasks(state, max_tasks=3)

        self.assertEqual(
            {task["adapter"] for task in selected},
            {"edge_marketplace", "searxng", "common_crawl"},
        )

    def test_distinct_backend_groups_overlap_network_and_commit_to_one_ledger(self):
        rendezvous = threading.Barrier(2, timeout=2.0)

        def adapter_for(url):
            def adapter(payload):
                rendezvous.wait()
                yield {
                    "type": "url",
                    "url": url,
                    "title": "candidate",
                    "snippet": "",
                    "channels": [payload["source_class"]],
                    "source_class": payload["source_class"],
                    "query_family": payload["query_family"],
                    "observed_at": "2026-08-05T00:00:00Z",
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

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = [
                source_task("alpha", "search_engine", "adapter_alpha"),
                source_task("beta", "open_index", "adapter_beta"),
            ]
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "ledger_path": str(root / "run.sqlite"),
                    "source_pool": tasks,
                },
                run_id="parallel-groups-run",
            )

            results = run_backend_tasks(
                state,
                max_tasks=2,
                adapters={
                    "adapter_alpha": adapter_for("https://alpha.example/item"),
                    "adapter_beta": adapter_for("https://beta.example/item"),
                },
                spool_dir=root / "spool",
            )

            self.assertEqual(len(results), 2)
            self.assertEqual(state["counters"]["unique_urls"], 2)
            self.assertEqual(state["backend_runtime"]["peak_inflight"], 2)
            self.assertEqual(
                {task["status"] for task in state["source_pool"]},
                {"exhausted"},
            )
            self.assertEqual(list((root / "spool").glob("*.ndjson")), [])

    def test_common_crawl_uses_its_two_worker_tier(self):
        rendezvous = threading.Barrier(2, timeout=2.0)

        def common_crawl_fixture(payload):
            rendezvous.wait()
            yield {
                "type": "summary",
                "end_reason": "queue_exhausted",
                "metric_stage": "canonical_url",
                "telemetry": {
                    "raw_url_observations": 0,
                    "successful_pages": 0,
                    "structured_records": 0,
                },
                "new_seeds": [],
                "round": {
                    "query_family": payload["query_family"],
                    "source_class": payload["source_class"],
                    "new_valid_urls": 0,
                    "new_entities": 0,
                    "new_fields": 0,
                    "mostly_duplicates": False,
                },
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = [
                source_task("cc-1", "open_index", "common_crawl"),
                source_task("cc-2", "open_index", "common_crawl"),
            ]
            for task in tasks:
                task["concurrency"] = {
                    "tier": 2,
                    "tool_limit": 2,
                    "host_limit": 2,
                }
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "ledger_path": str(root / "run.sqlite"),
                    "source_pool": tasks,
                },
                run_id="common-crawl-two-worker-run",
            )

            results = run_backend_tasks(
                state,
                max_tasks=2,
                adapters={"common_crawl": common_crawl_fixture},
                spool_dir=root / "spool",
            )

            self.assertEqual(len(results), 2)
            self.assertEqual(
                state["backend_runtime"]["groups"]["common_crawl"][
                    "peak_inflight"
                ],
                2,
            )

    def test_default_edge_group_uses_one_session_adapter(self):
        entries = []
        payload_keys = []

        @contextmanager
        def fake_session_adapter():
            entries.append("enter")

            def adapter(payload):
                payload_keys.append(set(payload))
                yield from edge_projection_events(payload)

            try:
                yield adapter
            finally:
                entries.append("exit")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = []
            for ordinal in range(2):
                task = source_task(
                    f"edge-marketplace:jd:{ordinal}",
                    "marketplace_list",
                    "edge_marketplace",
                )
                task["backend"] = "edge:jd"
                task["payload"] = {
                    "platform": "jd",
                    "query": f"手机壳 {ordinal}",
                    "query_family": f"手机壳:{ordinal}",
                    "cursor": {
                        "cursor_id": f"jd:phone-case:{ordinal}",
                        "ordinal": ordinal,
                        "page_number": 1,
                    },
                    "user_data_dir": str(root / "edge-profile"),
                    "deadline_seconds": 600.0,
                    "max_items": 1000,
                    "session_action": "start",
                    "pagination_enabled": False,
                }
                tasks.append(task)
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "run_type": "catalog_enumeration",
                    "ledger_path": str(root / "run.sqlite"),
                    "applicable_sources": ["marketplace_list"],
                    "source_pool": tasks,
                },
                run_id="edge-session-run",
            )

            with patch(
                "scripts.market_scheduler.edge_marketplace_session_adapter",
                fake_session_adapter,
            ):
                results = run_backend_tasks(
                    state,
                    max_tasks=2,
                    spool_dir=root / "spool",
                )

        self.assertEqual(entries, ["enter", "exit"])
        self.assertEqual(len(results), 2)
        self.assertEqual(payload_keys, [set(EDGE_PAYLOAD_KEYS)] * 2)

    def test_shared_edge_session_retains_healthy_pace_across_scheduler_rounds(self):
        """Reopening the Edge context would incorrectly slow-start at 45 s twice."""
        delays: list[float] = []
        entries: list[str] = []
        now = [0.0]

        class Pace:
            class Params:
                slow_page_threshold_seconds = 15.0

            params = Params()

            def __init__(self):
                self.interval = 45.0

            def next_delay(self):
                delays.append(self.interval)
                return self.interval

            def on_healthy(self):
                self.interval = max(20.0, self.interval * 0.75)

            def on_empty(self):
                pass

            def on_warning(self, *args, **kwargs):
                del args, kwargs

        class Session:
            def __enter__(self):
                entries.append("enter")
                return self

            def __exit__(self, *args):
                del args
                entries.append("exit")
                return False

            def run(self, payload):
                batch = deepcopy(JD_READY_BATCH)
                page_number = payload["cursor"]["page_number"]
                batch["platform"] = "jd"
                batch["query_family"] = payload["query_family"]
                batch["cursor"] = {
                    **batch["cursor"],
                    "cursor_id": payload["cursor"]["cursor_id"],
                    "page_number": page_number,
                    "status": "advanced",
                }
                batch["observed_page_number"] = page_number
                batch["diagnostics"]["observed_page_number"] = page_number
                batch["has_next_page"] = page_number == 1
                return batch

        state = self.resilient_jd_state()
        with tempfile.TemporaryDirectory() as tmp, backend_runner.edge_marketplace_session_adapter(
            session_factory=Session,
            pace_factory=Pace,
            monotonic=lambda: now[0],
            sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds),
        ) as shared_adapter:
            spool = Path(tmp) / "spool"
            run_backend_tasks(
                state,
                max_tasks=1,
                spool_dir=spool,
                edge_session_adapter=shared_adapter,
            )
            run_backend_tasks(
                state,
                max_tasks=1,
                spool_dir=spool,
                edge_session_adapter=shared_adapter,
            )

        self.assertEqual(entries, ["enter", "exit"])
        self.assertEqual(delays, [45.0, 33.75])

    def test_edge_group_stops_at_budget_and_restores_unsubmitted_lease(self):
        calls = []

        @contextmanager
        def fake_session_adapter():
            def adapter(payload):
                calls.append(payload["query"])
                time.sleep(0.03)
                yield from edge_projection_events(payload)

            yield adapter

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = []
            for ordinal in range(2):
                task = source_task(
                    f"edge-marketplace:jd:{ordinal}",
                    "marketplace_list",
                    "edge_marketplace",
                )
                task["backend"] = "edge:jd"
                task["payload"] = {
                    "platform": "jd",
                    "query": f"手机壳 {ordinal}",
                    "query_family": f"手机壳:{ordinal}",
                    "cursor": {
                        "cursor_id": f"jd:budget:{ordinal}",
                        "ordinal": ordinal,
                        "page_number": 1,
                    },
                    "user_data_dir": "",
                    "deadline_seconds": 45.0,
                    "max_items": 100,
                    "session_action": "start",
                    "pagination_enabled": False,
                }
                tasks.append(task)
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "run_type": "catalog_enumeration",
                    "ledger_path": str(root / "run.sqlite"),
                    "applicable_sources": ["marketplace_list"],
                    "source_pool": tasks,
                },
                run_id="edge-budget-run",
            )
            record_discovery_interval(
                state, 0.0, 599.99, session_id="prior-budget-session"
            )

            with patch(
                "scripts.market_scheduler.edge_marketplace_session_adapter",
                fake_session_adapter,
            ):
                results = run_backend_tasks(
                    state,
                    max_tasks=2,
                    spool_dir=root / "spool",
                )

        statuses = {task["task_id"]: task["status"] for task in state["source_pool"]}
        self.assertEqual(len(results), 1)
        self.assertEqual(calls, ["手机壳 0"])
        self.assertGreaterEqual(pure_search_seconds(state), 600.0)
        self.assertEqual(statuses["edge-marketplace:jd:0"], "exhausted")
        self.assertEqual(statuses["edge-marketplace:jd:1"], "pending")
        self.assertEqual(
            state["backend_runtime"]["groups"]["edge_marketplace"][
                "submitted_tasks"
            ],
            1,
        )

    def test_failed_edge_attempt_also_consumes_budget_before_next_cursor(self):
        calls = []

        @contextmanager
        def failing_session_adapter():
            def adapter(payload):
                calls.append(payload["query"])
                time.sleep(0.03)
                raise AdapterFailure("edge_worker_input_invalid", retryable=False)
                yield

            yield adapter

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = []
            for ordinal in range(2):
                task = source_task(
                    f"edge-marketplace:jd:{ordinal}",
                    "marketplace_list",
                    "edge_marketplace",
                )
                task["backend"] = "edge:jd"
                task["payload"] = {
                    "platform": "jd",
                    "query": f"手机壳 {ordinal}",
                    "query_family": f"手机壳:{ordinal}",
                    "cursor": {
                        "cursor_id": f"jd:failure-budget:{ordinal}",
                        "ordinal": ordinal,
                        "page_number": 1,
                    },
                    "user_data_dir": "",
                    "deadline_seconds": 45.0,
                    "max_items": 100,
                    "session_action": "start",
                    "pagination_enabled": False,
                }
                tasks.append(task)
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "run_type": "catalog_enumeration",
                    "ledger_path": str(root / "run.sqlite"),
                    "applicable_sources": ["marketplace_list"],
                    "source_pool": tasks,
                },
                run_id="edge-failure-budget-run",
            )
            record_discovery_interval(
                state, 0.0, 599.99, session_id="prior-budget-session"
            )

            with patch(
                "scripts.market_scheduler.edge_marketplace_session_adapter",
                failing_session_adapter,
            ):
                results = run_backend_tasks(
                    state,
                    max_tasks=2,
                    spool_dir=root / "spool",
                )

        statuses = {task["task_id"]: task["status"] for task in state["source_pool"]}
        self.assertEqual(results, ())
        self.assertEqual(calls, ["手机壳 0"])
        self.assertGreaterEqual(pure_search_seconds(state), 600.0)
        self.assertEqual(statuses["edge-marketplace:jd:0"], "failed")
        self.assertEqual(statuses["edge-marketplace:jd:1"], "pending")

    def test_rate_limited_edge_cursor_blocks_jd_source_for_remainder_of_run(self):
        calls = []

        @contextmanager
        def rate_limited_session_adapter():
            def adapter(payload):
                calls.append(payload["query"])
                raise AdapterFailure("browser_rate_limited", retryable=True)
                yield

            yield adapter

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = []
            for ordinal in range(2):
                task = source_task(
                    f"edge-marketplace:jd:{ordinal}",
                    "marketplace_list",
                    "edge_marketplace",
                )
                task["backend"] = "edge:jd"
                task["payload"] = {
                    "platform": "jd",
                    "query": f"手机壳 {ordinal}",
                    "query_family": f"手机壳:{ordinal}",
                    "cursor": {
                        "cursor_id": f"jd:cooldown:{ordinal}",
                        "ordinal": ordinal,
                        "page_number": 1,
                    },
                    "user_data_dir": "",
                    "deadline_seconds": 45.0,
                    "max_items": 100,
                    "session_action": "start",
                    "pagination_enabled": False,
                }
                tasks.append(task)
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "run_type": "catalog_enumeration",
                    "ledger_path": str(root / "run.sqlite"),
                    "applicable_sources": ["marketplace_list"],
                    "marketplace_plan": {
                        "dimensions": {"topic": "手机壳"},
                        "platforms": ["jd"],
                        "batch_size": 8,
                        "jd_slow_lane": True,
                    },
                    "source_pool": tasks,
                },
                run_id="edge-cooldown-run",
            )

            with patch(
                "scripts.market_scheduler.edge_marketplace_session_adapter",
                rate_limited_session_adapter,
            ):
                results = run_backend_tasks(
                    state,
                    max_tasks=2,
                    spool_dir=root / "spool",
                )

        statuses = {task["task_id"]: task["status"] for task in state["source_pool"]}
        self.assertEqual(results, ())
        self.assertEqual(calls, ["手机壳 0"])
        self.assertEqual(statuses["edge-marketplace:jd:0"], "blocked")
        self.assertEqual(statuses["edge-marketplace:jd:1"], "pending")
        self.assertEqual(
            state["marketplace_plan"]["platform_health"]["jd"],
            "blocked",
        )
        self.assertEqual(select_next_tasks(state, max_tasks=1), ())

    def test_local_edge_worker_timeout_cools_without_marking_jd_rate_limited(self):
        @contextmanager
        def timeout_session_adapter():
            def adapter(payload):
                raise AdapterFailure("edge_worker_timeout", retryable=True)
                yield

            yield adapter

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = source_task(
                "edge-marketplace:jd:timeout",
                "marketplace_list",
                "edge_marketplace",
            )
            task["backend"] = "edge:jd"
            task["payload"] = {
                "platform": "jd",
                "query": "手机壳",
                "query_family": "手机壳:default",
                "cursor": {
                    "cursor_id": "jd:timeout",
                    "ordinal": 0,
                    "page_number": 1,
                },
                "user_data_dir": "",
                "deadline_seconds": 45.0,
                "max_items": 100,
                "session_action": "start",
                "pagination_enabled": False,
            }
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "run_type": "catalog_enumeration",
                    "ledger_path": str(root / "run.sqlite"),
                    "applicable_sources": ["marketplace_list"],
                    "marketplace_plan": {
                        "dimensions": {"topic": "手机壳"},
                        "platforms": ["jd"],
                        "batch_size": 8,
                        "jd_slow_lane": True,
                    },
                    "source_pool": [task],
                },
                run_id="edge-local-timeout-run",
            )
            with patch(
                "scripts.market_scheduler.edge_marketplace_session_adapter",
                timeout_session_adapter,
            ):
                results = run_backend_tasks(
                    state,
                    max_tasks=1,
                    spool_dir=root / "spool",
                )

        self.assertEqual(results, ())
        self.assertEqual(state["source_pool"][0]["status"], "cooling")
        self.assertEqual(state["marketplace_plan"]["platform_health"]["jd"], "cooling")
        self.assertEqual(
            state["failures"][-1]["error_category"],
            "edge_worker_timeout",
        )

    def test_jd_slow_lane_accepts_when_wall_window_is_consumed(self):
        """慢速车道按墙钟窗口验收：候选先到、长冷却占满窗口仍判达标。

        京东慢速车道的 pacing（180s→90s）让纯请求时间远小于 search_limit，
        验收必须看墙钟已消耗窗口（driver 记录 wall_started_at）。本用例模拟
        候选在窗口早期到达、随后平台进入长冷却的场景：此时 pure_search 仍小，
        但墙钟窗口已跑满，evaluate_global_status 必须返回 ten_minute_limit 且
        acceptance_passed=True。
        """
        state = create_run_state(
            {
                **BASE_CONFIG,
                "run_type": "catalog_enumeration",
                "ledger_path": temporary_ledger_path(),
                "applicable_sources": ["marketplace_list"],
                "marketplace_plan": {
                    "dimensions": {"topic": "手机壳"},
                    "platforms": ["jd"],
                    "batch_size": 8,
                    "jd_slow_lane": True,
                },
                "source_pool": [],
            },
            run_id="slow-lane-wall-window",
        )
        # driver 记录单调起点：模拟已消耗 700s 墙钟（> 600s search_limit）。
        state["wall_started_at"] = time.perf_counter() - 700.0
        discovery = state["marketplace_discovery"]
        discovery["total_unique_candidates"] = 340
        discovery["recent_activity"] = [
            {"search_second": 50.0, "count": 340, "source": "marketplace_list"}
        ]
        discovery["max_zero_gap_seconds"] = 5.0
        discovery["sources"] = {
            "marketplace_list": {
                "state": "available",
                "batches": 2,
                "raw_observations": 400,
                "candidate_additions": 340,
            }
        }
        state["counters"]["raw_url_observations"] = 400

        status = evaluate_global_status(state)

        self.assertEqual(status, "ten_minute_limit")
        decision = discovery["decision"]
        self.assertTrue(decision["acceptance_passed"])
        self.assertEqual(decision["state"], "ten_minute_limit")
        # 纯请求时间仍很小，确认达标靠的是墙钟窗口而非纯搜索秒。
        self.assertLess(pure_search_seconds(state), 600.0)

    def test_jd_slow_lane_without_wall_start_stays_conservative(self):
        """未记录墙钟起点时回退到纯搜索秒，避免误判达标。"""
        state = create_run_state(
            {
                **BASE_CONFIG,
                "run_type": "catalog_enumeration",
                "ledger_path": temporary_ledger_path(),
                "applicable_sources": ["marketplace_list"],
                "marketplace_plan": {
                    "dimensions": {"topic": "手机壳"},
                    "platforms": ["jd"],
                    "batch_size": 8,
                    "jd_slow_lane": True,
                },
                "source_pool": [],
            },
            run_id="slow-lane-no-wall-start",
        )
        discovery = state["marketplace_discovery"]
        discovery["total_unique_candidates"] = 340
        discovery["recent_activity"] = [
            {"search_second": 50.0, "count": 340, "source": "marketplace_list"}
        ]
        discovery["max_zero_gap_seconds"] = 5.0
        discovery["sources"] = {
            "marketplace_list": {
                "state": "available",
                "batches": 2,
                "raw_observations": 400,
                "candidate_additions": 340,
            }
        }
        state["counters"]["raw_url_observations"] = 400

        status = evaluate_global_status(state)

        # 无 wall_started_at -> 回退纯搜索秒（0s），未到 600s，保持 running。
        self.assertEqual(status, "running")
        self.assertFalse(discovery["decision"]["acceptance_passed"])

    def test_edge_rate_limit_cools_platform_then_resumes_after_cooldown(self):
        """Rate limit pauses the JD platform lane and reopens it after cooldown."""
        plan_config = {
            "dimensions": {"topic": "手机壳"},
            "platforms": ["jd"],
            "batch_size": 8,
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = source_task(
                "edge-marketplace:jd:0",
                "marketplace_list",
                "edge_marketplace",
            )
            task["backend"] = "edge:jd"
            task["payload"] = {
                "platform": "jd",
                "query": "手机壳 0",
                "query_family": "手机壳:0",
                "cursor": {
                    "cursor_id": "jd:resume:0",
                    "ordinal": 0,
                    "page_number": 1,
                },
                "user_data_dir": "",
                "deadline_seconds": 45.0,
                "max_items": 100,
                "session_action": "start",
                "pagination_enabled": False,
            }
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "run_type": "catalog_enumeration",
                    "ledger_path": str(root / "run.sqlite"),
                    "applicable_sources": ["marketplace_list"],
                    "marketplace_plan": plan_config,
                    "source_pool": [task],
                },
                run_id="edge-cooldown-resume-run",
            )
            plan = state["marketplace_plan"]
            self.assertEqual(plan["platform_health"]["jd"], "healthy")

            # A rate-limited failure must flip the platform lane to cooling.
            _set_platform_cooling(state, task)
            self.assertEqual(plan["platform_health"]["jd"], "cooling")
            self.assertGreater(plan["platform_cool_until"]["jd"], 0.0)
            self.assertEqual(
                [
                    item
                    for item in rank_source_tasks(state)
                    if item.get("adapter") == "edge_marketplace"
                ],
                [],
            )

            # Once the cooldown elapses the lane reopens: health returns and the
            # pre-seeded edge task becomes selectable again.
            plan["platform_cool_until"]["jd"] = time.perf_counter() - 1.0
            added = _ensure_marketplace_query_tasks(state, plan)
            self.assertEqual(plan["platform_health"]["jd"], "healthy")
            pending = [
                item
                for item in rank_source_tasks(state)
                if item.get("adapter") == "edge_marketplace"
            ]
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["payload"]["platform"], "jd")
            self.assertEqual(added, 0)  # plan already exhausted, no new tasks

    def test_edge_backend_commits_candidate_but_keeps_state_compact(self):
        def fake_edge_adapter(payload):
            yield from edge_projection_events(payload)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = source_task(
                "edge-marketplace:jd:1", "marketplace_list", "edge_marketplace"
            )
            task["backend"] = "edge:jd"
            task["payload"] = {
                "platform": "jd",
                "query": "透明防摔手机壳",
                "cursor": {
                    "cursor_id": "jd:phone-case:page-1",
                    "ordinal": 0,
                    "page_number": 1,
                },
            }
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "run_type": "catalog_enumeration",
                    "ledger_path": str(root / "run.sqlite"),
                    "applicable_sources": ["marketplace_list"],
                    "source_pool": [task],
                },
                run_id="edge-run",
            )

            results = run_backend_tasks(
                state,
                adapters={"edge_marketplace": fake_edge_adapter},
                max_tasks=1,
                spool_dir=root / "spool",
            )

            self.assertEqual(results[0]["metric_stage"], "marketplace_candidate")
            self.assertEqual(
                state["marketplace_discovery"]["total_unique_candidates"], 1
            )
            serialized = json.dumps(state, ensure_ascii=False)
            for forbidden in (
                "透明防摔手机壳",
                "100123456789",
                "https://item.jd.com",
                "https://search.jd.com",
            ):
                self.assertNotIn(forbidden, serialized)
            self.assertEqual(
                state["backend_runtime"]["groups"]["edge_marketplace"][
                    "max_workers"
                ],
                1,
            )
            self.assertEqual(list((root / "spool").glob("*.ndjson")), [])
            with SqliteUrlLedger(root / "run.sqlite") as ledger:
                self.assertEqual(ledger.marketplace_candidate_count(), 1)

    def test_edge_backend_preserves_stable_failure_category_and_cursor_digest(self):
        def disabled_edge(payload):
            del payload
            raise AdapterFailure(
                "edge_remote_debugging_disabled",
                retryable=False,
                detail="must not enter scheduler state",
            )
            yield

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = source_task(
                "edge-marketplace:jd:2", "marketplace_list", "edge_marketplace"
            )
            task["backend"] = "edge:jd"
            task["payload"] = {
                "platform": "jd",
                "cursor": {
                    "cursor_id": "jd:private-query-shape",
                    "ordinal": 0,
                    "page_number": 1,
                },
            }
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "run_type": "catalog_enumeration",
                    "ledger_path": str(root / "run.sqlite"),
                    "applicable_sources": ["marketplace_list"],
                    "source_pool": [task],
                },
                run_id="edge-run",
            )

            results = run_backend_tasks(
                state,
                adapters={"edge_marketplace": disabled_edge},
                max_tasks=1,
                spool_dir=root / "spool",
            )

            self.assertEqual(results, ())
            self.assertEqual(state["source_pool"][0]["status"], "unavailable")
            failure = state["failures"][0]
            self.assertEqual(
                set(failure),
                {"task_id", "error_category", "retryable", "cursor_digest"},
            )
            self.assertEqual(
                failure["error_category"], "edge_remote_debugging_disabled"
            )
            self.assertFalse(failure["retryable"])
            self.assertEqual(len(failure["cursor_digest"]), 24)
            serialized = json.dumps(state, ensure_ascii=False)
            self.assertNotIn("must not enter scheduler state", serialized)
            self.assertNotIn("jd:private-query-shape", serialized)

    def test_transient_browser_ingest_is_compact_idempotent_and_failure_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            other_tasks = [
                source_task("domestic-search", "search_engine", "searxng"),
                source_task("history", "open_index", "common_crawl"),
            ]
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "run_type": "catalog_enumeration",
                    "ledger_path": str(ledger_path),
                    "source_pool": other_tasks,
                },
                run_id="run-1",
            )

            ingest_browser_batch(state, deepcopy(JD_READY_BATCH))
            first = json.dumps(state, ensure_ascii=False, sort_keys=True)
            ingest_browser_batch(state, deepcopy(JD_READY_BATCH))

            browser_tasks = [
                task
                for task in state["source_pool"]
                if task["adapter"] == "browser_batch_ingest"
            ]
            self.assertEqual(len(browser_tasks), 1)
            self.assertEqual(browser_tasks[0]["status"], "exhausted")
            self.assertIn("cursor_digest", browser_tasks[0]["payload"])
            self.assertEqual(state["marketplace_discovery"]["total_unique_candidates"], 1)
            self.assertEqual(first, json.dumps(state, ensure_ascii=False, sort_keys=True))
            for forbidden in (
                "items",
                "100123456789",
                "透明防摔手机壳",
                "https://item.jd.com",
                "https://search.jd.com",
            ):
                self.assertNotIn(forbidden, first)

            blocked = deepcopy(JD_READY_BATCH)
            blocked["cursor"]["cursor_id"] = "jd:手机壳:default:page-2"
            blocked["cursor"]["page_number"] = 2
            blocked["observed_page_number"] = 2
            blocked["diagnostics"]["observed_page_number"] = 2
            blocked["diagnostics"]["valid_item_count"] = 0
            blocked["diagnostics"]["candidate_anchor_count"] = 0
            blocked["page_state"] = "authentication_required"
            blocked["items"] = []
            ingest_browser_batch(state, blocked)
            statuses = {
                task["task_id"]: task["status"] for task in state["source_pool"]
            }
            self.assertEqual(statuses["domestic-search"], "pending")
            self.assertEqual(statuses["history"], "pending")
            self.assertIn("blocked", statuses.values())
            self.assertEqual(
                state["failures"][-1]["error_category"],
                "browser_authentication_required",
            )

    def test_catalog_ingest_keeps_only_compact_candidate_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            task = source_task(
                "browser-jd", "marketplace_list", "browser_batch_ingest"
            )
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "run_type": "catalog_enumeration",
                    "ledger_path": str(ledger_path),
                    "source_pool": [task],
                },
                run_id="run-1",
            )
            select_next_tasks(state)
            leased = next(
                item for item in state["source_pool"] if item["status"] == "leased"
            )
            spec = BatchSpec(
                "candidate-batch",
                "run-1",
                str(leased["task_id"]),
                str(leased["adapter"]),
                "cn-pillow-market-v1",
            )
            with SqliteUrlLedger(ledger_path) as ledger:
                with ledger.batch(spec) as writer:
                    writer.add(
                        UrlObservation(
                            url="https://item.jd.com/100123456789.html",
                            title="透明防摔手机壳",
                            snippet="",
                            channels=("edge:jd",),
                            source_class="marketplace_list",
                            query_family="手机壳:default",
                            observed_at="2026-08-04T08:00:00Z",
                            metadata={
                                "platform": "jd",
                                "product_id": "100123456789",
                            },
                        )
                    )
                    writer.finish(
                        {
                            "end_reason": "queue_exhausted",
                            "raw_url_observations": 1,
                            "valid_urls": 1,
                            "unique_additions": 1,
                            "unique_candidate_additions": 1,
                        }
                    )
            result = {
                "batch_id": "candidate-batch",
                "task_id": leased["task_id"],
                "run_id": "run-1",
                "scope_fingerprint": "cn-pillow-market-v1",
                "metric_stage": "marketplace_candidate",
                "time_session_id": "boot-1",
                "ledger_committed": True,
                "ledger_counts": {
                    "raw_url_observations": 1,
                    "valid_urls": 1,
                    "unique_additions": 1,
                    "total_unique_urls": 1,
                    "unique_candidate_additions": 1,
                    "total_unique_candidates": 1,
                },
                "active_intervals": [[0.0, 35.0]],
                "verified_objects": [],
                "invalidations": [],
                "new_seeds": [],
                "round": {
                    "query_family": "手机壳:default",
                    "source_class": "marketplace_list",
                    "new_valid_urls": 1,
                    "new_entities": 1,
                    "new_fields": 0,
                    "mostly_duplicates": False,
                },
                "end_reason": "queue_exhausted",
                "telemetry": {
                    "raw_url_observations": 1,
                    "successful_pages": 1,
                    "structured_records": 1,
                },
            }

            ingest_batch_result(state, result)

            discovery = state["marketplace_discovery"]
            self.assertEqual(discovery["total_unique_candidates"], 1)
            self.assertEqual(
                discovery["recent_activity"],
                [{"search_second": 35.0, "count": 1, "source": "marketplace_list"}],
            )
            self.assertGreaterEqual(discovery["max_zero_gap_seconds"], 35.0)
            self.assertEqual(discovery["decision"]["state"], "zero_window")
            serialized = json.dumps(state, ensure_ascii=False)
            for forbidden in (
                "100123456789",
                "透明防摔手机壳",
                "https://item.jd.com",
            ):
                self.assertNotIn(forbidden, serialized)

    def test_state_uses_a_sqlite_ledger_path_not_a_url_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            state = create_run_state(
                {**BASE_CONFIG, "ledger_path": str(ledger_path)},
                run_id="run-1",
            )
            self.assertEqual(state["ledger_path"], str(ledger_path.resolve()))
            self.assertNotIn("canonical_urls", state)

    def test_ingest_accepts_only_a_matching_committed_ledger_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            task = source_task("search", "search_engine", "tool_bridge")
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "ledger_path": str(ledger_path),
                    "source_pool": [task],
                },
                run_id="run-1",
            )
            select_next_tasks(state)
            spec = BatchSpec(
                "batch-1",
                "run-1",
                "search",
                "tool_bridge",
                "cn-pillow-market-v1",
            )
            with SqliteUrlLedger(ledger_path) as ledger:
                with ledger.batch(spec) as writer:
                    writer.add(
                        UrlObservation(
                            url="https://example.com/item/1?utm_source=a",
                            title="One",
                            snippet="short",
                            channels=("searxng:bing",),
                            source_class="search_engine",
                            query_family="family:search",
                            observed_at="2026-08-03T00:00:00Z",
                            metadata={},
                        )
                    )
                    writer.finish(
                        {
                            "end_reason": "queue_exhausted",
                            "raw_url_observations": 1,
                            "valid_urls": 1,
                            "unique_additions": 1,
                        }
                    )
            result = {
                "batch_id": "batch-1",
                "task_id": "search",
                "run_id": "run-1",
                "scope_fingerprint": "cn-pillow-market-v1",
                "metric_stage": "product_candidate",
                "time_session_id": "boot-1",
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

            ingest_batch_result(state, result)

            serialized = json.dumps(state, ensure_ascii=False)
            self.assertNotIn("https://example.com/item/1", serialized)
            self.assertEqual(state["counters"]["unique_urls"], 1)

    def test_ingest_rejects_an_uncommitted_ledger_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            task = source_task("search", "search_engine", "tool_bridge")
            state = create_run_state(
                {
                    **BASE_CONFIG,
                    "ledger_path": str(ledger_path),
                    "source_pool": [task],
                },
                run_id="run-1",
            )
            select_next_tasks(state)
            result = {
                "batch_id": "missing",
                "task_id": "search",
                "run_id": "run-1",
                "scope_fingerprint": "cn-pillow-market-v1",
                "metric_stage": "canonical_url",
                "ledger_committed": True,
                "ledger_counts": {
                    "raw_url_observations": 0,
                    "valid_urls": 0,
                    "unique_additions": 0,
                    "total_unique_urls": 0,
                },
            }
            with self.assertRaisesRegex(ValueError, "ledger-batch-not-committed"):
                ingest_batch_result(state, result)

    def test_all_discovery_run_types_share_the_ten_minute_limit(self):
        for run_type in (
            "quick_direct",
            "open_web_research",
            "catalog_enumeration",
            "bounded_dataset_extract",
        ):
            with self.subTest(run_type=run_type):
                state = create_run_state(
                    {
                        **BASE_CONFIG,
                        "run_type": run_type,
                        "source_pool": [pending_search_task()],
                    },
                    run_id=f"{run_type}-1",
                )
                self.assertEqual(state["run_type"], run_type)
                self.assertEqual(state["search_limit_seconds"], 600.0)
                record_discovery_interval(state, 0.0, 600.0)
                self.assertEqual(
                    evaluate_global_status(state),
                    "ten_minute_limit",
                )

    def test_search_limit_seconds_is_configurable_within_bounds(self):
        state = create_run_state(
            {**BASE_CONFIG, "search_limit_seconds": 300.0},
            run_id="custom-limit",
        )
        self.assertEqual(state["search_limit_seconds"], 300.0)
        record_discovery_interval(state, 0.0, 300.0)
        self.assertEqual(evaluate_global_status(state), "ten_minute_limit")

    def test_search_limit_seconds_rejects_out_of_bounds_values(self):
        for invalid in (0, -5, 4000, True):
            with self.subTest(value=invalid), self.assertRaisesRegex(
                ValueError, "search_limit_seconds"
            ):
                create_run_state(
                    {**BASE_CONFIG, "search_limit_seconds": invalid},
                    run_id="invalid-limit",
                )

    def test_bounded_dataset_can_finish_by_verified_scope(self):
        state = create_run_state(
            {
                **BASE_CONFIG,
                "run_type": "bounded_dataset_extract",
                "source_pool": [],
                "scope_completion": {
                    "boundary": "2025-01-01/2025-12-31",
                    "expected_pages": 12,
                    "completed_pages": 12,
                    "failed_pages": 0,
                },
            },
            run_id="bounded-1",
        )
        self.assertEqual(
            evaluate_global_status(state),
            "deterministic_scope_complete",
        )

    def test_schema_one_migration_is_explicit_and_pure(self):
        from scripts import market_scheduler as module

        legacy = create_run_state(BASE_CONFIG, run_id="legacy-1")
        legacy["schema_version"] = 1
        legacy.pop("run_type", None)
        legacy.pop("search_limit_seconds", None)
        original = dict(legacy)

        migrated = module.migrate_state_v1_to_v2(legacy)

        self.assertEqual(legacy, original)
        self.assertEqual(migrated["schema_version"], 2)
        self.assertEqual(migrated["run_type"], "open_web_research")
        self.assertEqual(migrated["search_limit_seconds"], 600.0)

    def test_overlapping_discovery_intervals_count_once(self):
        state = create_run_state(BASE_CONFIG, run_id="run-1")
        record_discovery_interval(state, 0.0, 4.0, session_id="boot-1")
        record_discovery_interval(state, 2.0, 7.0, session_id="boot-1")
        self.assertEqual(pure_search_seconds(state), 7.0)

    def test_reboot_time_sessions_sum_without_cross_epoch_overlap(self):
        state = create_run_state(BASE_CONFIG, run_id="run-1")
        record_discovery_interval(state, 100.0, 106.0, session_id="boot-1")
        record_discovery_interval(state, 1.0, 5.0, session_id="boot-2")
        self.assertEqual(pure_search_seconds(state), 10.0)

    def test_six_second_backend_probe_cannot_finalize_market_run(self):
        config = {**BASE_CONFIG, "source_pool": [pending_search_task()]}
        state = create_run_state(config, run_id="run-1")
        record_discovery_interval(state, 0.0, 6.74)
        state["attempted_sources"] = ["sitemap"]
        self.assertEqual(evaluate_global_status(state), "running")
        with self.assertRaisesRegex(ValueError, "global-stop-not-satisfied"):
            finalize_run(state)

    def test_six_hundred_seconds_can_finalize(self):
        state = create_run_state(BASE_CONFIG, run_id="run-1")
        record_discovery_interval(state, 0.0, 600.0)
        finalized = finalize_run(state)
        self.assertEqual(finalized["status"], "ten_minute_limit")
        self.assertEqual(
            finalized["stop_evidence"]["reason"], "ten-minute-search-limit"
        )

    def test_backend_batch_never_finalizes_as_market_discovery(self):
        state = create_run_state(
            {**BASE_CONFIG, "run_kind": "backend_batch"}, run_id="batch-1"
        )
        record_discovery_interval(state, 0.0, 600.0)
        with self.assertRaisesRegex(
            ValueError, "only-market-discovery-can-finalize"
        ):
            finalize_run(state)

    def test_no_route_before_global_stop_is_incomplete_not_success(self):
        state = create_run_state(BASE_CONFIG, run_id="run-1")
        record_discovery_interval(state, 0.0, 6.74)
        self.assertEqual(evaluate_global_status(state), "incomplete_blocked")
        with self.assertRaisesRegex(ValueError, "global-stop-not-satisfied"):
            finalize_run(state)

    def test_invalid_or_reversed_time_intervals_are_rejected(self):
        state = create_run_state(BASE_CONFIG, run_id="run-1")
        for start, end in ((2.0, 1.0), (-1.0, 1.0), (True, 1.0)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValueError):
                    record_discovery_interval(state, start, end)


class MarketSchedulerRoutingTests(unittest.TestCase):
    def test_catalog_plan_is_lazy_small_and_keeps_platform_offsets_separate(self):
        config = {
            **BASE_CONFIG,
            "run_type": "catalog_enumeration",
            "source_pool": [],
            "marketplace_plan": {
                "dimensions": {
                    "topic": "手机壳",
                    "brands": [f"品牌-{index}" for index in range(100)],
                    "specifications": [f"规格-{index}" for index in range(100)],
                    "categories": [f"分类-{index}" for index in range(10)],
                    "price_bands": [f"价格-{index}" for index in range(10)],
                },
                "platforms": ["jd", "taobao"],
                "batch_size": 16,
            },
        }

        state = create_run_state(config, run_id="catalog-1")

        plan = state["marketplace_plan"]
        self.assertLessEqual(len(state["source_pool"]), 16)
        self.assertEqual(plan["batch_size"], 16)
        self.assertFalse(plan["exhausted"])
        self.assertNotIn("queries", plan)
        self.assertNotIn("items", json.dumps(state, ensure_ascii=False).casefold())
        self.assertLessEqual(len(json.dumps(state, ensure_ascii=False)), 32768)
        self.assertTrue(
            all(task["adapter"] == "searxng" for task in state["source_pool"])
        )
        self.assertTrue(
            all("items" not in task["payload"] for task in state["source_pool"])
        )

        for task in state["source_pool"]:
            task["status"] = "exhausted"
        jd_before = plan["platform_offsets"]["jd"]
        taobao_before = plan["platform_offsets"]["taobao"]
        plan["platform_health"]["jd"] = "blocked"
        added = ensure_query_tasks(state)

        self.assertGreater(added, 0)
        self.assertEqual(plan["platform_offsets"]["jd"], jd_before)
        self.assertGreater(plan["platform_offsets"]["taobao"], taobao_before)
        self.assertFalse(plan["exhausted"])
        new_tasks = [
            task
            for task in state["source_pool"]
            if task.get("status") == "pending"
        ]
        self.assertTrue(new_tasks)
        self.assertTrue(
            all(
                task["marketplace_cursor"]["platform"] == "taobao"
                for task in new_tasks
            )
        )

    def test_catalog_plan_round_robins_all_topic_dimensions(self):
        state = create_run_state(
            {
                **BASE_CONFIG,
                "run_type": "catalog_enumeration",
                "ledger_path": temporary_ledger_path(),
                "applicable_sources": ["search_engine"],
                "marketplace_plan": {
                    "topic_dimensions": [
                        {"topic": "枕头"},
                        {"topic": "枕芯"},
                    ],
                    "platforms": ["jd"],
                    "batch_size": 8,
                },
                "source_pool": [],
            },
            run_id="multi-topic-marketplace-plan",
        )

        plan = state["marketplace_plan"]
        added = _ensure_marketplace_query_tasks(state, plan)
        queries = {
            task["payload"]["query"]
            for task in state["source_pool"]
            if task.get("adapter") == "searxng"
        }

        self.assertEqual(added, 0)
        self.assertTrue(any("枕头" in query for query in queries))
        self.assertTrue(any("枕芯" in query for query in queries))
        self.assertEqual(
            [item["topic"] for item in plan["topic_dimensions"]],
            ["枕头", "枕芯"],
        )

    def test_legacy_single_marketplace_dimensions_is_normalized(self):
        state = create_run_state(
            {
                **BASE_CONFIG,
                "run_type": "catalog_enumeration",
                "ledger_path": temporary_ledger_path(),
                "marketplace_plan": {
                    "dimensions": {"topic": "手机壳"},
                    "platforms": ["jd"],
                    "batch_size": 8,
                },
                "source_pool": [],
            },
            run_id="legacy-marketplace-plan",
        )
        self.assertEqual(
            state["marketplace_plan"]["topic_dimensions"],
            [state["marketplace_plan"]["dimensions"]],
        )

    def test_million_query_matrix_is_materialized_only_in_small_batches(self):
        config = {
            **BASE_CONFIG,
            "query_matrix": {
                "topics": [f"topic-{index}" for index in range(100)],
                "locations": [f"location-{index}" for index in range(100)],
                "times": [f"time-{index}" for index in range(100)],
            },
            "source_templates": [
                {
                    "source_class": "search_engine",
                    "backend": "searxng",
                    "adapter": "tool_bridge",
                    "query_family": "broad",
                    "payload_template": {"query": "{query}"},
                    "query_dimensions": ["time", "platform"],
                    "concurrency": {
                        "tier": 2,
                        "tiers": [2, 4],
                        "tool_limit": 4,
                        "host_limit": 4,
                    },
                }
            ],
        }

        state = create_run_state(config, run_id="large-1")

        self.assertLessEqual(len(state["source_pool"]), 8)
        self.assertEqual(state["query_generation"]["offset"], 8)
        self.assertFalse(state["query_generation"]["exhausted"])
        self.assertNotIn("queries", state["query_generation"])
        self.assertLess(len(json.dumps(state)), 25_000)

        for task in state["source_pool"]:
            task["status"] = "exhausted"
        state["query_generation"]["last_canonical_yield"] = 0.30
        next_tasks = select_next_tasks(state, max_tasks=1)
        self.assertEqual(len(next_tasks), 1)
        self.assertEqual(state["query_generation"]["batch_size"], 16)
        self.assertEqual(state["query_generation"]["offset"], 24)

        for task in state["source_pool"]:
            task["status"] = "exhausted"
        state["query_generation"]["last_canonical_yield"] = 0.80
        state["query_generation"]["last_batch_failed"] = True
        select_next_tasks(state, max_tasks=1)
        self.assertEqual(state["query_generation"]["batch_size"], 16)
        self.assertEqual(state["query_generation"]["offset"], 40)

    def test_coop_queue_exhaustion_selects_another_source(self):
        config = {
            **BASE_CONFIG,
            "source_pool": [
                source_task("coop-sitemap", "sitemap", "sitemap"),
                source_task("open-index", "open_index", "tool_bridge"),
            ],
        }
        state = create_run_state(config, run_id="run-1")
        first = select_next_tasks(state)[0]
        self.assertEqual(first["task_id"], "coop-sitemap")
        first["status"] = "exhausted"
        second = select_next_tasks(state)[0]
        self.assertEqual(second["task_id"], "open-index")
        self.assertEqual(evaluate_global_status(state), "running")

    def test_object_yield_outranks_raw_url_noise(self):
        state = create_run_state(
            {
                **BASE_CONFIG,
                "source_pool": [
                    source_task(
                        "huge-noisy-map",
                        "sitemap",
                        "sitemap",
                        score_inputs={
                            "raw_rate": 500,
                            "canonical_yield": 0.01,
                            "object_yield": 0.0,
                            "duplicate_rate": 0.99,
                        },
                    ),
                    source_task(
                        "brand-catalog",
                        "official_site",
                        "tool_bridge",
                        score_inputs={
                            "raw_rate": 20,
                            "canonical_yield": 0.8,
                            "object_yield": 0.6,
                            "duplicate_rate": 0.1,
                        },
                    ),
                ],
            },
            run_id="run-1",
        )
        self.assertEqual(rank_source_tasks(state)[0]["task_id"], "brand-catalog")

    def test_query_matrix_and_feedback_seeds_expand_new_tasks_once(self):
        config = {
            **BASE_CONFIG,
            "query_matrix": {
                "topics": ["枕头"],
                "aliases": ["pillow"],
                "source_facets": ["官网", "型号"],
                "languages": ["中文"],
            },
            "source_templates": [
                {
                    "source_class": "search_engine",
                    "backend": "public-search",
                    "adapter": "tool_bridge",
                    "query_family": "topic-facet",
                    "payload_template": {"query": "{query}"},
                    "query_dimensions": ["language", "platform", "brand"],
                    "concurrency": {
                        "tier": 24,
                        "tool_limit": 40,
                        "host_limit": 40,
                    },
                }
            ],
        }
        self.assertEqual(len(expand_query_tasks(config)), 4)
        state = create_run_state(config, run_id="run-1")
        initial_ids = {task["task_id"] for task in state["source_pool"]}
        self.assertEqual(len(initial_ids), 4)
        added = enqueue_feedback_tasks(
            state,
            [{"topic": "乳胶枕", "query_family": "discovered-material"}],
        )
        repeated = enqueue_feedback_tasks(
            state,
            [{"topic": "乳胶枕", "query_family": "discovered-material"}],
        )
        self.assertGreater(added, 0)
        self.assertEqual(repeated, 0)

    def test_page_pressure_reduces_only_the_page_channel(self):
        state = create_run_state(
            {
                **BASE_CONFIG,
                "source_pool": [
                    source_task("pages", "official_site", "page"),
                    source_task("maps", "sitemap", "sitemap"),
                ],
            },
            run_id="run-1",
        )
        apply_channel_signal(
            state,
            "pages",
            {
                "rate_limited": True,
                "rate_limit_streak": 2,
                "error_rate": 0.2,
                "latency_ratio": 1.7,
                "captcha_rate": 0.1,
                "empty_body_rate": 0.2,
            },
        )
        tiers = {
            task["task_id"]: task["concurrency"]["tier"]
            for task in state["source_pool"]
        }
        self.assertLess(tiers["pages"], 24)
        self.assertEqual(tiers["maps"], 24)

    def test_channel_signal_uses_the_tasks_configured_concurrency_tiers(self):
        task = source_task("searxng", "search_engine", "tool_bridge")
        task["concurrency"] = {
            "tier": 2,
            "tiers": [2, 4],
            "tool_limit": 8,
            "host_limit": 8,
        }
        state = create_run_state(
            {**BASE_CONFIG, "source_pool": [task]}, run_id="run-1"
        )

        apply_channel_signal(
            state,
            "searxng",
            {"error_rate": 0.0, "latency_ratio": 1.0},
        )

        concurrency = state["source_pool"][0]["concurrency"]
        self.assertEqual(concurrency["tier"], 4)
        self.assertEqual(concurrency["tiers"], [2, 4])

    def test_failed_route_switches_source_and_cannot_repeat_unchanged(self):
        state = create_run_state(
            {
                **BASE_CONFIG,
                "source_pool": [
                    source_task(
                        "blocked-pages",
                        "official_site",
                        "page",
                        score_inputs={"object_yield": 1.0},
                    ),
                    source_task("open-index", "open_index", "tool_bridge"),
                ],
            },
            run_id="run-1",
        )
        self.assertEqual(select_next_tasks(state)[0]["task_id"], "blocked-pages")
        record_task_failure(
            state,
            "blocked-pages",
            error_category="captcha",
            next_route={
                "backend": "open-index",
                "query_family": "historical-index",
            },
        )
        self.assertEqual(select_next_tasks(state)[0]["task_id"], "open-index")
        with self.assertRaisesRegex(ValueError, "unchanged-failed-route"):
            record_task_failure(
                state,
                "blocked-pages",
                error_category="captcha",
                next_route={
                    "backend": "blocked-pages",
                    "query_family": "family:blocked-pages",
                },
            )


def batch_result(
    state: dict[str, object],
    *,
    batch_id: str = "batch-1",
    task_id: str = "coop-sitemap",
    objects: tuple[dict[str, object], ...] = (),
    invalidations: tuple[dict[str, object], ...] = (),
    interval: tuple[float, float] = (0.0, 6.74),
    raw_urls: int = 557,
    query_family: str = "site-catalog",
    source_class: str = "sitemap",
    new_valid_urls: int = 1,
    mostly_duplicates: bool = False,
) -> dict[str, object]:
    if new_valid_urls > raw_urls:
        raise ValueError("new_valid_urls cannot exceed raw_urls")
    task = next(
        task
        for task in state["source_pool"]
        if task["task_id"] == task_id
    )
    raw_observations = [
        f"https://example.com/products/pillow-{index}"
        for index in range(new_valid_urls)
    ]
    if raw_urls > len(raw_observations):
        duplicate_url = (
            raw_observations[0]
            if raw_observations
            else "https://example.com/products/duplicate"
        )
        raw_observations.extend(
            duplicate_url for _ in range(raw_urls - len(raw_observations))
        )
    spec = BatchSpec(
        batch_id=batch_id,
        run_id=str(state["run_id"]),
        task_id=task_id,
        adapter=str(task["adapter"]),
        scope_fingerprint=str(state["scope_fingerprint"]),
    )
    with SqliteUrlLedger(str(state["ledger_path"])) as ledger:
        with ledger.batch(spec) as writer:
            unique_additions = 0
            for raw_url in raw_observations:
                outcome = writer.add(
                    UrlObservation(
                        url=raw_url,
                        title="fixture",
                        snippet="fixture",
                        channels=(str(task["backend"]),),
                        source_class=source_class,
                        query_family=query_family,
                        observed_at="2026-08-03T00:00:00Z",
                        metadata={},
                    )
                )
                unique_additions += int(not outcome.duplicate)
            writer.finish(
                {
                    "end_reason": "queue_exhausted",
                    "raw_url_observations": raw_urls,
                    "valid_urls": raw_urls,
                    "unique_additions": unique_additions,
                }
            )
        total_unique_urls = ledger.stats().unique_urls
    return {
        "batch_id": batch_id,
        "task_id": task_id,
        "run_id": "run-1",
        "scope_fingerprint": "cn-pillow-market-v1",
        "metric_stage": "verified_model",
        "time_session_id": "boot-1",
        "ledger_committed": True,
        "ledger_counts": {
            "raw_url_observations": raw_urls,
            "valid_urls": raw_urls,
            "unique_additions": unique_additions,
            "total_unique_urls": total_unique_urls,
        },
        "active_intervals": [list(interval)],
        "verified_objects": list(objects),
        "invalidations": list(invalidations),
        "new_seeds": [],
        "round": {
            "query_family": query_family,
            "source_class": source_class,
            "new_valid_urls": new_valid_urls,
            "new_entities": len(objects),
            "new_fields": 0,
            "mostly_duplicates": mostly_duplicates,
        },
        "end_reason": "queue_exhausted",
        "telemetry": {
            "raw_url_observations": raw_urls,
            "successful_pages": 0,
            "structured_records": len(objects),
        },
    }


def state_with_coop(
    *, parent: dict[str, object] | None = None
) -> dict[str, object]:
    state = create_run_state(
        {
            **BASE_CONFIG,
            "ledger_path": temporary_ledger_path(),
            "source_pool": [source_task("coop-sitemap", "sitemap", "sitemap")],
        },
        run_id="run-1",
        parent=parent,
    )
    select_next_tasks(state)
    return state


class MarketSchedulerLineageTests(unittest.TestCase):
    def test_ingest_is_idempotent(self):
        state = state_with_coop()
        result = batch_result(
            state,
            objects=(
                {
                    "object_id": "brand:model-a",
                    "evidence": ["https://example.com/products/pillow-a"],
                },
            )
        )
        ingest_batch_result(state, result)
        ingest_batch_result(state, result)
        self.assertEqual(state["counters"]["raw_url_observations"], 557)
        self.assertEqual(cumulative_verified_count(state), 1)

    def test_parent_union_cannot_shrink_without_invalidation(self):
        parent = {
            "run_id": "old",
            "scope_fingerprint": "cn-pillow-market-v1",
            "verified_objects": {
                "a": {"evidence": ["https://a.example/p"]},
                "b": {"evidence": ["https://b.example/p"]},
            },
        }
        state = state_with_coop(parent=parent)
        ingest_batch_result(
            state,
            batch_result(
                state,
                objects=(
                    {"object_id": "b", "evidence": ["https://b.example/p"]},
                    {"object_id": "c", "evidence": ["https://c.example/p"]},
                )
            ),
        )
        self.assertEqual(set(state["verified_objects"]), {"a", "b", "c"})
        self.assertEqual(state["counters"]["previous_verified_objects"], 2)
        self.assertEqual(state["counters"]["new_verified_objects"], 1)
        self.assertEqual(state["counters"]["overlap_verified_objects"], 1)

    def test_invalidation_requires_new_evidence_and_reason(self):
        parent = {
            "run_id": "old",
            "scope_fingerprint": "cn-pillow-market-v1",
            "verified_objects": {
                "a": {"evidence": ["https://a.example/p"]}
            },
        }
        state = state_with_coop(parent=parent)
        before = cumulative_verified_count(state)
        bad = batch_result(
            state, invalidations=({"object_id": "a", "reason": ""},)
        )
        with self.assertRaisesRegex(ValueError, "invalidation-evidence-required"):
            ingest_batch_result(state, bad)
        self.assertEqual(cumulative_verified_count(state), before)
        self.assertEqual(state["ingested_batch_ids"], [])


class MarketSchedulerHistoricalAcceptanceTests(unittest.TestCase):
    def test_pillow_run_keeps_switching_after_the_six_second_coop_batch(self):
        """The 557/78 historical probe is one batch, never the whole market."""
        tasks = [
            source_task(
                "coop-sitemap",
                "sitemap",
                "sitemap",
                score_inputs={"object_yield": 1.0},
            ),
            source_task("open-index", "open_index", "tool_bridge"),
            source_task("official-sites", "official_site", "tool_bridge"),
            source_task("search-engine", "search_engine", "tool_bridge"),
        ]
        state = create_run_state(
            {
                **BASE_CONFIG,
                "applicable_sources": [
                    "sitemap",
                    "open_index",
                    "official_site",
                    "search_engine",
                ],
                "ledger_path": temporary_ledger_path(),
                "source_pool": tasks,
            },
            run_id="run-1",
        )

        self.assertEqual(select_next_tasks(state)[0]["task_id"], "coop-sitemap")
        objects = tuple(
            {
                "object_id": f"pillow:model-{index}",
                "evidence": [f"https://example.com/products/pillow-{index}"],
            }
            for index in range(78)
        )
        ingest_batch_result(
            state,
            batch_result(
                state,
                objects=objects,
                raw_urls=557,
                new_valid_urls=78,
                interval=(0.0, 6.74),
            ),
        )
        self.assertEqual(evaluate_global_status(state), "running")
        self.assertEqual(cumulative_verified_count(state), 78)

        switched_tasks = set()
        for index in range(1, 4):
            task = select_next_tasks(state)[0]
            switched_tasks.add(str(task["task_id"]))
            result = batch_result(
                state,
                batch_id=f"zero-{index}",
                task_id=str(task["task_id"]),
                raw_urls=0,
                new_valid_urls=0,
                interval=(5.74 + index, 6.74 + index),
                query_family=str(task["query_family"]),
                source_class=str(task["source_class"]),
                mostly_duplicates=True,
            )
            ingest_batch_result(state, result)

        self.assertEqual(
            switched_tasks, {"open-index", "official-sites", "search-engine"}
        )

        self.assertEqual(evaluate_global_status(state), "incomplete_blocked")
        state["coverage_gaps"] = []
        state["query_dimensions"]["attempted"] = list(
            state["query_dimensions"]["applicable"]
        )
        state["continued_discovery_unlikely_to_change"] = True
        self.assertEqual(evaluate_global_status(state), "search_saturated")
        self.assertEqual(finalize_run(state)["status"], "search_saturated")

    def test_sibling_run_reaches_the_permanent_ten_minute_limit(self):
        state = create_run_state(
            {**BASE_CONFIG, "source_pool": [pending_search_task()]},
            run_id="run-1",
        )
        record_discovery_interval(state, 0.0, 600.0, session_id="boot-1")
        self.assertEqual(evaluate_global_status(state), "ten_minute_limit")
        self.assertEqual(finalize_run(state)["status"], "ten_minute_limit")

    def test_evidenced_invalidation_can_reduce_union_and_is_audited(self):
        parent = {
            "run_id": "old",
            "scope_fingerprint": "cn-pillow-market-v1",
            "verified_objects": {
                "a": {"evidence": ["https://a.example/p"]},
                "b": {"evidence": ["https://b.example/p"]},
            },
        }
        state = state_with_coop(parent=parent)
        ingest_batch_result(
            state,
            batch_result(
                state,
                invalidations=(
                    {
                        "object_id": "a",
                        "reason": "official replacement confirmed",
                        "new_evidence": ["https://a.example/replacement"],
                    },
                )
            ),
        )
        self.assertEqual(set(state["verified_objects"]), {"b"})
        self.assertEqual(state["counters"]["invalidated_objects"], 1)
        self.assertEqual(state["invalidations"][0]["object_id"], "a")

    def test_mismatched_scope_is_rejected_before_mutation(self):
        state = state_with_coop()
        result = batch_result(state)
        result["scope_fingerprint"] = "another-market"
        with self.assertRaisesRegex(ValueError, "batch-scope-mismatch"):
            ingest_batch_result(state, result)
        self.assertEqual(state["ingested_batch_ids"], [])


if __name__ == "__main__":
    unittest.main()
