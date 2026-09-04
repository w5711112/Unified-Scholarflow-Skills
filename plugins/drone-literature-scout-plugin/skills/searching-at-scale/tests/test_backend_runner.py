from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

import scripts.backend_runner as backend_runner
from scripts.backend_runner import (
    ADAPTER_REGISTRY,
    AdapterFailure,
    edge_marketplace_adapter,
    run_adapter,
    run_adapter_group,
)
from scripts.normalize_and_dedupe import SqliteUrlLedger
from test_marketplace_candidates import JD_READY_BATCH


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backend_runner.py"


def projection_for_payload(payload: dict[str, object]) -> dict[str, object]:
    value = json.loads(json.dumps(JD_READY_BATCH, ensure_ascii=False))
    cursor = payload["cursor"]
    value["platform"] = payload["platform"]
    value["query_family"] = payload["query_family"]
    value["cursor"] = {
        **value["cursor"],
        "cursor_id": cursor["cursor_id"],
        "page_number": cursor["page_number"],
    }
    value["observed_page_number"] = cursor["page_number"]
    value["diagnostics"]["observed_page_number"] = cursor["page_number"]
    return value


def safe_projection_evidence() -> dict[str, object]:
    return {
        "platform": "jd",
        "requested_page_number": 1,
        "observed_page_number": 1,
        "diagnostics": json.loads(
            json.dumps(JD_READY_BATCH["diagnostics"], ensure_ascii=False)
        ),
    }


def envelope(lease_id: str = "run-1:task-1:1") -> dict[str, object]:
    return {
        "type": "task-envelope",
        "run_id": "run-1",
        "scope_fingerprint": "scope-1",
        "task_id": "task-1",
        "lease_id": lease_id,
        "time_session_id": "session-1",
        "adapter": "fixture",
        "payload": {"query_family": "broad"},
    }


def browser_envelope(lease_id: str = "browser-lease-1") -> dict[str, object]:
    value = envelope(lease_id)
    value["adapter"] = "browser_batch_ingest"
    value["payload"] = json.loads(json.dumps(JD_READY_BATCH, ensure_ascii=False))
    return value


def url_event(url: str = "https://example.com/a") -> dict[str, object]:
    return {
        "type": "url",
        "url": url,
        "title": "A",
        "snippet": "",
        "channels": ["fixture"],
        "source_class": "search",
        "query_family": "broad",
        "observed_at": "2026-08-03T00:00:00Z",
        "metadata": {},
    }


def terminal_summary(raw: int = 1) -> dict[str, object]:
    return {
        "type": "summary",
        "end_reason": "queue_exhausted",
        "metric_stage": "canonical_url",
        "telemetry": {
            "raw_url_observations": raw,
            "successful_pages": 0,
            "structured_records": 0,
        },
        "new_seeds": [],
        "round": {
            "query_family": "broad",
            "source_class": "search",
            "new_valid_urls": raw,
            "new_entities": 0,
            "new_fields": 0,
            "mostly_duplicates": False,
        },
    }


def complete_adapter(payload):
    self_query_family = payload["query_family"]
    event = url_event()
    event["query_family"] = self_query_family
    yield event
    summary = terminal_summary()
    summary["round"]["query_family"] = self_query_family
    yield summary


def missing_summary_adapter(payload):
    del payload
    yield url_event()


def failing_adapter(payload):
    del payload
    raise AdapterFailure("fixture_failure", retryable=False, detail="safe detail")
    yield


class BackendRunnerTests(unittest.TestCase):
    def test_adapter_failure_projection_evidence_is_exact_and_deep_detached(self):
        original = safe_projection_evidence()
        failure = AdapterFailure(
            "browser_page_structure_changed",
            retryable=False,
            projection_evidence=original,
        )
        self.assertEqual(failure.projection_evidence, original)
        failure.projection_evidence["diagnostics"]["recovery_stage"] = "reload"
        self.assertEqual(original["diagnostics"]["recovery_stage"], "initial")

    def test_adapter_failure_requires_platform_specific_source_path(self):
        for platform, source_path in (("jd", "/Search"), ("taobao", "/search")):
            with self.subTest(platform=platform, source_path=source_path):
                original = safe_projection_evidence()
                original["platform"] = platform
                original["diagnostics"]["source_path"] = source_path
                failure = AdapterFailure(
                    "browser_page_structure_changed",
                    retryable=False,
                    projection_evidence=original,
                )
                self.assertEqual(failure.projection_evidence, original)
                failure.projection_evidence["diagnostics"]["stable_rounds"] = 99
                self.assertNotEqual(original["diagnostics"]["stable_rounds"], 99)

        for platform, source_path in (("jd", "/search"), ("taobao", "/Search")):
            with self.subTest(platform=platform, rejected_source_path=source_path):
                evidence = safe_projection_evidence()
                evidence["platform"] = platform
                evidence["diagnostics"]["source_path"] = source_path
                with self.assertRaises(ValueError):
                    AdapterFailure(
                        "browser_page_structure_changed",
                        retryable=False,
                        projection_evidence=evidence,
                    )

    def test_adapter_failure_rejects_noncanonical_projection_evidence(self):
        invalid = []
        for key in (
            "platform",
            "requested_page_number",
            "observed_page_number",
            "diagnostics",
        ):
            value = safe_projection_evidence()
            value.pop(key)
            invalid.append(value)
        for key in ("html", "text", "cookie", "query", "free"):
            value = safe_projection_evidence()
            value[key] = "forbidden"
            invalid.append(value)
        for key in ("html", "text", "cookie", "query"):
            value = safe_projection_evidence()
            value["diagnostics"][key] = "forbidden"
            invalid.append(value)
        for changes in (
            {"platform": "amazon"},
            {"requested_page_number": 0},
            {"requested_page_number": 513},
            {"requested_page_number": True},
            {"observed_page_number": 2},
        ):
            invalid.append({**safe_projection_evidence(), **changes})
        for changes in (
            {"document_ready_state": "unknown"},
            {"valid_item_count": -1},
            {"stable_rounds": True},
            {"observed_page_number": 2},
            {"recovery_stage": "retry"},
            {"recovery_stage": "initial", "recovery_attempt": 1},
            {"source_path": "/item"},
        ):
            value = safe_projection_evidence()
            value["diagnostics"].update(changes)
            invalid.append(value)

        for evidence in invalid:
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                AdapterFailure(
                    "browser_page_structure_changed",
                    retryable=False,
                    projection_evidence=evidence,
                )

    def test_adapter_group_stops_before_submitting_more_after_result_callback(self):
        first = envelope("lease-1")
        first["task_id"] = "task-1"
        second = envelope("lease-2")
        second["task_id"] = "task-2"
        keep_running = True
        observed = []
        telemetry: dict[str, object] = {}

        def on_result(result):
            nonlocal keep_running
            observed.append(result["task_id"])
            keep_running = False

        with tempfile.TemporaryDirectory() as tmp:
            results = run_adapter_group(
                [first, second],
                ledger_path=Path(tmp) / "run.sqlite",
                adapter=complete_adapter,
                max_workers=1,
                spool_dir=Path(tmp) / "spool",
                telemetry=telemetry,
                result_callback=on_result,
                should_continue=lambda: keep_running,
            )

        self.assertEqual([result["task_id"] for result in results], ["task-1"])
        self.assertEqual(observed, ["task-1"])
        self.assertEqual(telemetry["submitted_tasks"], 1)

    def test_edge_group_adapter_reuses_one_worker_session(self):
        class ZeroPace:
            class Params:
                slow_page_threshold_seconds = 999.0

            params = Params()

            def next_delay(self):
                return 0.0

            def on_healthy(self):
                pass

            def on_empty(self):
                pass

            def on_warning(self, *args, **kwargs):
                del args, kwargs

        class FakeSession:
            def __init__(self):
                self.enter_count = 0
                self.exit_count = 0
                self.payloads = []

            def __enter__(self):
                self.enter_count += 1
                return self

            def __exit__(self, exc_type, exc, traceback):
                del exc_type, exc, traceback
                self.exit_count += 1
                return False

            def run(self, payload):
                self.payloads.append(payload)
                return projection_for_payload(payload)

        session = FakeSession()
        payload = {
            "platform": "jd",
            "query": "手机壳",
            "query_family": "手机壳:default",
            "cursor": {"cursor_id": "jd:abc", "ordinal": 0, "page_number": 1},
            "user_data_dir": "C:\\runtime\\edge-profile",
            "deadline_seconds": 600.0,
            "max_items": 1000,
            "session_action": "start",
            "pagination_enabled": False,
        }

        with backend_runner.edge_marketplace_session_adapter(
            session_factory=lambda: session,
            pace_factory=ZeroPace,
        ) as adapter:
            first = list(adapter(payload))
            second = list(adapter({
                **payload,
                "query": "防摔手机壳",
                "cursor": {"cursor_id": "jd:def", "ordinal": 1, "page_number": 1},
            }))

        self.assertEqual(session.enter_count, 1)
        self.assertEqual(session.exit_count, 1)
        self.assertEqual(len(session.payloads), 2)
        self.assertEqual(first[-1]["type"], "summary")
        self.assertEqual(second[-1]["type"], "summary")

    def test_edge_session_active_interval_excludes_pacing_delay(self):
        class FakeClock:
            def __init__(self):
                self.now = 0.0

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.now += seconds

        class FakePace:
            class Params:
                slow_page_threshold_seconds = 999.0

            params = Params()

            def next_delay(self):
                return 30.0

            def on_healthy(self):
                pass

            def on_empty(self):
                pass

            def on_warning(self, *args, **kwargs):
                del args, kwargs

        clock = FakeClock()
        payload = {
            "platform": "jd",
            "query": "手机壳",
            "query_family": "手机壳:default",
            "cursor": {"cursor_id": "jd:abc", "ordinal": 0, "page_number": 1},
            "user_data_dir": "C:\\runtime\\edge-profile",
            "deadline_seconds": 600.0,
            "max_items": 1000,
            "session_action": "start",
            "pagination_enabled": False,
        }

        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                del args
                return False

            def run(self, payload):
                clock.now += 2.0
                page_number = payload["cursor"]["page_number"]
                value = projection_for_payload(payload)
                value["pagination_state"] = (
                    "pagination_unverified" if page_number == 1 else "page_verified"
                )
                return value

        with backend_runner.edge_marketplace_session_adapter(
            session_factory=FakeSession,
            pace_factory=FakePace,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        ) as adapter:
            list(adapter(payload))
            list(adapter({
                **payload,
                "cursor": {"cursor_id": "jd:abc", "ordinal": 0, "page_number": 2},
                "session_action": "next",
                "pagination_enabled": True,
            }))
            interval = adapter.consume_active_interval()

        self.assertEqual(clock.now, 64.0)
        self.assertEqual(interval, (62.0, 64.0))

    def test_edge_session_does_not_start_when_pacing_exceeds_wall_budget(self):
        now = [100.0]
        calls = []

        class Pace:
            def next_delay(self):
                return 30.0

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                del args
                return False

            def run(self, payload):
                calls.append(payload)
                return JD_READY_BATCH

        with backend_runner.edge_marketplace_session_adapter(
            session_factory=Session,
            pace_factory=Pace,
            monotonic=lambda: now[0],
            sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds),
            wall_deadline=120.0,
        ) as adapter:
            with self.assertRaises(AdapterFailure) as raised:
                list(adapter({
                    "platform": "jd",
                    "query": "枕头",
                    "query_family": "枕头:default",
                    "cursor": {"cursor_id": "jd:pillow", "ordinal": 0, "page_number": 1},
                    "user_data_dir": "",
                    "deadline_seconds": 60.0,
                    "max_items": 100,
                    "session_action": "start",
                    "pagination_enabled": False,
                }))

        self.assertEqual(raised.exception.category, "wall_budget_exhausted")
        self.assertEqual(now[0], 100.0)
        self.assertEqual(calls, [])

    def test_edge_marketplace_adapter_is_in_the_fixed_registry(self):
        self.assertIs(
            ADAPTER_REGISTRY["edge_marketplace"], edge_marketplace_adapter
        )

    def test_adapter_group_reports_only_compact_failure_telemetry(self):
        value = envelope("failed-lease")
        value["task_id"] = "edge-task-1"
        telemetry: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as tmp:
            spool_dir = Path(tmp) / "spool"
            results = run_adapter_group(
                [value],
                ledger_path=Path(tmp) / "run.sqlite",
                adapter=lambda payload: failing_adapter(payload),
                max_workers=1,
                spool_dir=spool_dir,
                telemetry=telemetry,
            )

            self.assertEqual(results, ())
            self.assertEqual(
                telemetry["failures"],
                [
                    {
                        "task_id": "edge-task-1",
                        "category": "fixture_failure",
                        "retryable": False,
                    }
                ],
            )
            self.assertNotIn("safe detail", json.dumps(telemetry))
            self.assertEqual(list(spool_dir.glob("*.ndjson")), [])

    def test_engine_health_is_forwarded_as_compact_whitelisted_telemetry(self):
        def partial_engine_adapter(payload):
            del payload
            yield url_event()
            summary = terminal_summary()
            summary["telemetry"]["unresponsive_engines"] = [
                ["sogou", "timeout"],
                ["quark", "HTTP 429"],
            ]
            summary["telemetry"]["engine_health"] = {
                "baidu": "available",
                "quark": "rate_limited",
                "sogou": "unresponsive",
            }
            summary["telemetry"]["cooldown_engines"] = ["quark", "sogou"]
            yield summary

        with tempfile.TemporaryDirectory() as tmp:
            result = run_adapter(
                envelope(),
                ledger_path=Path(tmp) / "run.sqlite",
                adapter=partial_engine_adapter,
            )
            self.assertEqual(
                result["telemetry"]["engine_health"],
                {
                    "baidu": "available",
                    "quark": "rate_limited",
                    "sogou": "unresponsive",
                },
            )
            self.assertEqual(
                result["telemetry"]["cooldown_engines"],
                ["quark", "sogou"],
            )

    def test_browser_batch_commits_one_candidate_and_replays_idempotently(self):
        self.assertIn("browser_batch_ingest", ADAPTER_REGISTRY)
        self.assertNotIn("jd_union_api", ADAPTER_REGISTRY)
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            value = browser_envelope()
            first = run_adapter(
                value,
                ledger_path=ledger_path,
                adapter=ADAPTER_REGISTRY["browser_batch_ingest"],
            )
            replay = run_adapter(
                value,
                ledger_path=ledger_path,
                adapter=ADAPTER_REGISTRY["browser_batch_ingest"],
            )
            self.assertEqual(first, replay)
            self.assertEqual(first["ledger_counts"]["unique_candidate_additions"], 1)
            self.assertEqual(first["ledger_counts"]["total_unique_candidates"], 1)
            self.assertEqual(first["round"]["new_entities"], 1)
            self.assertEqual(first["cursor_evidence"]["page_number"], 1)
            serialized = json.dumps(first, ensure_ascii=False).casefold()
            for forbidden in (
                "items",
                "透明防摔手机壳".casefold(),
                "cookie",
                "local_storage",
                "dom",
            ):
                self.assertNotIn(forbidden, serialized)
            with SqliteUrlLedger(ledger_path) as ledger:
                self.assertEqual(ledger.marketplace_candidate_count(), 1)

    def test_browser_block_states_are_stable_failures_and_commit_nothing(self):
        states = {
            "authentication_required": "browser_authentication_required",
            "captcha_required": "browser_captcha_required",
            "page_structure_changed": "browser_page_structure_changed",
        }
        for state, category in states.items():
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                value = browser_envelope(state)
                value["payload"]["page_state"] = state
                value["payload"]["items"] = []
                value["payload"]["diagnostics"]["valid_item_count"] = 0
                value["payload"]["diagnostics"]["candidate_anchor_count"] = 0
                ledger_path = Path(tmp) / "run.sqlite"
                with self.assertRaisesRegex(AdapterFailure, category):
                    run_adapter(
                        value,
                        ledger_path=ledger_path,
                        adapter=ADAPTER_REGISTRY["browser_batch_ingest"],
                    )
                with SqliteUrlLedger(ledger_path) as ledger:
                    self.assertEqual(ledger.stats().unique_urls, 0)
                    self.assertEqual(ledger.marketplace_candidate_count(), 0)

    def test_strict_projection_failure_carries_detached_safe_evidence(self):
        value = browser_envelope()
        value["payload"]["page_state"] = "page_structure_changed"
        value["payload"]["items"] = []
        value["payload"]["diagnostics"]["valid_item_count"] = 0
        value["payload"]["diagnostics"]["candidate_anchor_count"] = 0
        original = json.loads(json.dumps(value["payload"], ensure_ascii=False))
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(
            AdapterFailure
        ) as raised:
            run_adapter(
                value,
                ledger_path=Path(tmp) / "run.sqlite",
                adapter=ADAPTER_REGISTRY["browser_batch_ingest"],
            )

        evidence = raised.exception.projection_evidence
        self.assertEqual(
            set(evidence),
            {"platform", "requested_page_number", "observed_page_number", "diagnostics"},
        )
        self.assertEqual(set(evidence["diagnostics"]), set(original["diagnostics"]))
        evidence["diagnostics"]["recovery_stage"] = "reload"
        self.assertEqual(value["payload"], original)
        for forbidden in ("source_url", "query_family", "items", "cookie"):
            self.assertNotIn(forbidden, evidence)

    def test_browser_batch_rejects_sensitive_fields_and_rolls_back(self):
        for key in ("cookie", "password", "local_storage", "profile"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                value = browser_envelope(key)
                value["payload"][key] = "must-not-enter-ledger"
                ledger_path = Path(tmp) / "run.sqlite"
                with self.assertRaisesRegex(
                    AdapterFailure, "adapter_sensitive_field_rejected"
                ):
                    run_adapter(
                        value,
                        ledger_path=ledger_path,
                        adapter=ADAPTER_REGISTRY["browser_batch_ingest"],
                    )
                with SqliteUrlLedger(ledger_path) as ledger:
                    self.assertEqual(ledger.stats().unique_urls, 0)

    def test_all_public_url_events_can_promote_verified_marketplace_identity(self):
        def search_adapter(payload):
            del payload
            yield {
                "type": "url",
                "url": "https://item.jd.com/100123456789.html?utm_source=search",
                "title": "透明防摔手机壳",
                "snippet": "public search result",
                "channels": ["searxng:baidu"],
                "source_class": "search",
                "query_family": "手机壳:baidu",
                "observed_at": "2026-08-04T08:00:00Z",
                "metadata": {},
            }
            yield terminal_summary()

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            result = run_adapter(
                envelope(), ledger_path=ledger_path, adapter=search_adapter
            )
            self.assertEqual(result["ledger_counts"]["unique_candidate_additions"], 1)
            with SqliteUrlLedger(ledger_path) as ledger:
                self.assertEqual(ledger.marketplace_candidate_count(), 1)

    def test_adapter_declared_marketplace_identity_must_match_url(self):
        def mismatched(payload):
            del payload
            event = url_event("https://item.jd.com/100123456789.html")
            event["title"] = "透明防摔手机壳"
            event["metadata"] = {
                "platform": "jd",
                "product_id": "999999999999",
            }
            yield event
            yield terminal_summary()

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            with self.assertRaisesRegex(
                AdapterFailure, "adapter_marketplace_identity_mismatch"
            ):
                run_adapter(
                    envelope(), ledger_path=ledger_path, adapter=mismatched
                )
            with SqliteUrlLedger(ledger_path) as ledger:
                self.assertEqual(ledger.stats().unique_urls, 0)
                self.assertEqual(ledger.marketplace_candidate_count(), 0)

    def test_adapter_group_bounds_inflight_work_and_removes_spools(self):
        active = 0
        peak = 0
        lock = threading.Lock()

        def adapter(payload):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            event = url_event(f"https://example.com/{payload['index']}")
            yield event
            yield terminal_summary()
            with lock:
                active -= 1

        envelopes = []
        for index in range(4):
            value = envelope(f"lease-{index}")
            value["task_id"] = f"task-{index}"
            value["payload"] = {"query_family": "broad", "index": index}
            envelopes.append(value)
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            spool_dir = Path(tmp) / "spool"
            results = run_adapter_group(
                envelopes,
                ledger_path=ledger_path,
                adapter=adapter,
                max_workers=2,
                spool_dir=spool_dir,
            )
            self.assertEqual(len(results), 4)
            self.assertEqual(peak, 2)
            self.assertEqual(list(spool_dir.glob("*.ndjson")), [])
            with SqliteUrlLedger(ledger_path) as ledger:
                self.assertEqual(ledger.stats().unique_urls, 4)

    def test_complete_adapter_commits_only_a_small_terminal_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            result = run_adapter(
                envelope(), ledger_path=ledger_path, adapter=complete_adapter
            )
            serialized = json.dumps(result, ensure_ascii=False).casefold()
            self.assertTrue(result["ledger_committed"])
            self.assertNotIn("urls", result)
            self.assertNotIn("body", serialized)
            self.assertNotIn("secret", serialized)
            self.assertEqual(result["ledger_counts"]["unique_additions"], 1)
            self.assertEqual(result["round"]["new_valid_urls"], 1)
            with SqliteUrlLedger(ledger_path) as ledger:
                self.assertTrue(ledger.has_batch("run-1:task-1:1"))
                self.assertEqual(ledger.stats().unique_urls, 1)

    def test_missing_terminal_summary_rolls_back_the_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            with self.assertRaisesRegex(AdapterFailure, "adapter_summary_required"):
                run_adapter(
                    envelope(),
                    ledger_path=ledger_path,
                    adapter=missing_summary_adapter,
                )
            with SqliteUrlLedger(ledger_path) as ledger:
                self.assertFalse(ledger.has_batch("run-1:task-1:1"))
                self.assertEqual(ledger.stats().unique_urls, 0)

    def test_summary_must_be_unique_and_last(self):
        def two_summaries(payload):
            del payload
            yield terminal_summary(raw=0)
            yield terminal_summary(raw=0)

        def url_after_summary(payload):
            del payload
            yield terminal_summary(raw=0)
            yield url_event()

        for name, adapter in (
            ("two", two_summaries),
            ("after", url_after_summary),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(AdapterFailure, "adapter_summary_not_terminal"):
                    run_adapter(
                        envelope(),
                        ledger_path=Path(tmp) / "run.sqlite",
                        adapter=adapter,
                    )

    def test_adapter_failure_is_isolated_and_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            run_adapter(
                envelope("good"), ledger_path=ledger_path, adapter=complete_adapter
            )
            with self.assertRaisesRegex(AdapterFailure, "fixture_failure"):
                run_adapter(
                    envelope("bad"), ledger_path=ledger_path, adapter=failing_adapter
                )
            with SqliteUrlLedger(ledger_path) as ledger:
                self.assertTrue(ledger.has_batch("good"))
                self.assertFalse(ledger.has_batch("bad"))
                self.assertIn("fixture_failure", ledger.failure_categories())

    def test_keyboard_interrupt_propagates_after_transaction_rollback(self):
        def interrupted(payload):
            del payload
            yield url_event()
            raise KeyboardInterrupt

        with tempfile.TemporaryDirectory() as tmp:
            ledger_path = Path(tmp) / "run.sqlite"
            with self.assertRaises(KeyboardInterrupt):
                run_adapter(
                    envelope(), ledger_path=ledger_path, adapter=interrupted
                )
            with SqliteUrlLedger(ledger_path) as ledger:
                self.assertEqual(ledger.stats().unique_urls, 0)

    def test_cli_stdout_contains_one_terminal_json_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            envelope_path = Path(tmp) / "task.json"
            ledger_path = Path(tmp) / "run.sqlite"
            value = envelope()
            value["adapter"] = "diagnostic_empty"
            envelope_path.write_text(
                json.dumps(value, ensure_ascii=False), encoding="utf-8"
            )
            environment = dict(os.environ)
            environment["PYTHONUTF8"] = "1"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(SCRIPT),
                    "--envelope",
                    str(envelope_path),
                    "--ledger",
                    str(ledger_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            lines = completed.stdout.splitlines()
            self.assertEqual(len(lines), 1)
            self.assertTrue(json.loads(lines[0])["ledger_committed"])


if __name__ == "__main__":
    unittest.main()
