from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

import scripts.edge_marketplace_query as edge_query
from scripts.domestic_marketplace_query import (
    MarketplaceQueryDimensions,
    SAT_EDGE_PIPE_PATH_ENV,
    edge_task_batch,
)
from scripts.edge_marketplace_query import (
    EdgeWorkerFailure,
    iter_edge_marketplace_events,
    probe_edge_background_bridge,
    run_edge_worker,
)


PAYLOAD = {
    "platform": "jd",
    "query": "手机壳",
    "query_family": "手机壳:default",
    "cursor": {"cursor_id": "jd:abc", "ordinal": 0, "page_number": 1},
    "user_data_dir": "",
    "deadline_seconds": 600.0,
    "max_items": 1000,
    "session_action": "start",
    "pagination_enabled": False,
}

READY_BATCH = {
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
    "cursor": {"cursor_id": "jd:abc", "page_number": 1, "status": "advanced"},
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
            "url": "https://item.jd.com/100123456789.html",
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


class CapturingStdin:
    def __init__(self):
        self.value = ""
        self.closed = False

    def write(self, value: str) -> int:
        self.value += value
        return len(value)

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(
        self,
        output: str,
        *,
        returncode: int = 0,
        times_out: bool = False,
    ):
        self.stdin = CapturingStdin()
        self.stdout = io.StringIO(output)
        self.returncode = returncode
        self.times_out = times_out
        self.terminated = False
        self.killed = False
        self.wait_calls = 0

    def wait(self, timeout=None):
        del timeout
        self.wait_calls += 1
        if self.times_out and not self.terminated and not self.killed:
            raise subprocess.TimeoutExpired("node", 600)
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class EdgeMarketplaceQueryTests(unittest.TestCase):
    def setUp(self):
        # Default-route cases must not inherit another test's profile override.
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop(SAT_EDGE_PIPE_PATH_ENV, None)

    def test_worker_failure_accepts_standard_exception_metadata(self):
        failure = EdgeWorkerFailure("edge_worker_input_invalid", False, "invalid")

        failure.__traceback__ = None

        self.assertIsNone(failure.__traceback__)

    def test_pipe_preflight_uses_the_owned_node_worker_context(self):
        process = FakeProcess('{"ok":true,"pipe":"codex.searching_at_scale.v1"}\n')
        calls = []

        def factory(arguments, **options):
            calls.append((arguments, options))
            return process

        result = probe_edge_background_bridge(
            timeout_seconds=1.25, popen_factory=factory
        )

        self.assertTrue(result["ok"])
        self.assertEqual(calls[0][0][-3:], ["--probe-pipe", "--timeout-ms", "1250"])
        self.assertNotIn("stdin", calls[0][1])

    def test_pipe_preflight_forwards_per_profile_pipe_override(self):
        process = FakeProcess('{"ok":true,"pipe":"codex.searching_at_scale.custom"}\n')
        calls = []

        def factory(arguments, **options):
            calls.append(arguments)
            return process

        saved = os.environ.get(SAT_EDGE_PIPE_PATH_ENV)
        try:
            os.environ[SAT_EDGE_PIPE_PATH_ENV] = r"\\.\pipe\codex.searching_at_scale.custom"
            result = probe_edge_background_bridge(
                timeout_seconds=1.0, popen_factory=factory
            )
        finally:
            if saved is None:
                os.environ.pop(SAT_EDGE_PIPE_PATH_ENV, None)
            else:
                os.environ[SAT_EDGE_PIPE_PATH_ENV] = saved

        self.assertTrue(result["ok"])
        self.assertEqual(
            calls[0][-2:],
            ["--pipe-path", r"\\.\pipe\codex.searching_at_scale.custom"],
        )
        self.assertEqual(calls[0][-3], "1000")

    def test_edge_worker_session_forwards_per_profile_pipe_override(self):
        process = FakeProcess(json.dumps(READY_BATCH, ensure_ascii=False) + "\n")
        calls = []

        def factory(arguments, **options):
            calls.append(arguments)
            return process

        saved = os.environ.get(SAT_EDGE_PIPE_PATH_ENV)
        try:
            os.environ[SAT_EDGE_PIPE_PATH_ENV] = r"\\.\pipe\codex.searching_at_scale.custom"
            with edge_query.EdgeWorkerSession(popen_factory=factory) as session:
                batch = session.run(PAYLOAD)
        finally:
            if saved is None:
                os.environ.pop(SAT_EDGE_PIPE_PATH_ENV, None)
            else:
                os.environ[SAT_EDGE_PIPE_PATH_ENV] = saved

        self.assertEqual(batch["query_family"], READY_BATCH["query_family"])
        self.assertEqual(
            calls[0][-2:],
            ["--pipe-path", r"\\.\pipe\codex.searching_at_scale.custom"],
        )

    def test_pipe_preflight_preserves_unavailable_category(self):
        process = FakeProcess(
            '{"error":{"category":"edge_background_bridge_unavailable","retryable":true}}\n',
            returncode=3,
        )

        with self.assertRaises(EdgeWorkerFailure) as raised:
            probe_edge_background_bridge(
                timeout_seconds=1.0,
                popen_factory=lambda *args, **kwargs: process,
            )

        self.assertEqual(
            raised.exception.category, "edge_background_bridge_unavailable"
        )
        self.assertTrue(raised.exception.retryable)

    def test_session_reuses_one_owned_node_process_for_two_payloads(self):
        second_batch = {
            **READY_BATCH,
            "query_family": "手机壳:second",
            "cursor": {"cursor_id": "jd:def", "page_number": 1, "status": "advanced"},
        }
        process = FakeProcess(
            json.dumps(READY_BATCH, ensure_ascii=False)
            + "\n"
            + json.dumps(second_batch, ensure_ascii=False)
            + "\n"
        )
        calls = []

        def factory(arguments, **options):
            calls.append((arguments, options))
            return process

        second_payload = {
            **PAYLOAD,
            "query": "防摔手机壳",
            "query_family": "手机壳:second",
            "cursor": {"cursor_id": "jd:def", "ordinal": 1, "page_number": 1},
        }
        with edge_query.EdgeWorkerSession(popen_factory=factory) as session:
            first = session.run(PAYLOAD)
            second = session.run(second_payload)
            self.assertFalse(process.stdin.closed)

        self.assertEqual(first, READY_BATCH)
        self.assertEqual(second, second_batch)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0][0][-1],
            str(
                Path(__file__).resolve().parents[1]
                / "scripts"
                / "edge_extension_client.mjs"
            ),
        )
        self.assertNotIn("edge_cdp_client.mjs", repr(calls[0][0]))
        self.assertEqual(
            [json.loads(line) for line in process.stdin.value.splitlines()],
            [PAYLOAD, second_payload],
        )
        self.assertTrue(process.stdin.closed)
        self.assertGreaterEqual(process.wait_calls, 1)

    def test_successful_worker_uses_stdin_and_returns_one_batch(self):
        process = FakeProcess(json.dumps(READY_BATCH, ensure_ascii=False) + "\n")
        calls = []

        def factory(arguments, **options):
            calls.append((arguments, options))
            return process

        batch = run_edge_worker(PAYLOAD, popen_factory=factory)

        self.assertEqual(batch, READY_BATCH)
        self.assertEqual(calls[0][0][-1], str(
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "edge_extension_client.mjs"
        ))
        self.assertNotIn("手机壳", repr(calls[0][0]))
        self.assertEqual(json.loads(process.stdin.value), PAYLOAD)
        self.assertTrue(process.stdin.closed)
        self.assertGreaterEqual(process.wait_calls, 1)

    def test_adapter_reuses_strict_browser_projection_contract(self):
        events = list(
            iter_edge_marketplace_events(
                PAYLOAD,
                worker_runner=lambda payload, **kwargs: READY_BATCH,
            )
        )

        self.assertEqual(events[-1]["type"], "summary")
        self.assertEqual(events[-1]["metric_stage"], "marketplace_candidate")
        self.assertEqual(events[0]["metadata"]["product_id"], "100123456789")
        self.assertNotIn("cookie", repr(events).casefold())

    def test_projection_evidence_sink_receives_detached_safe_recovery_evidence(self):
        original = json.loads(json.dumps(READY_BATCH, ensure_ascii=False))
        received = []

        def sink(evidence):
            received.append(evidence)
            evidence["diagnostics"]["recovery_stage"] = "reload"

        events = list(
            iter_edge_marketplace_events(
                PAYLOAD,
                worker_runner=lambda payload, **kwargs: READY_BATCH,
                projection_evidence_sink=sink,
            )
        )

        self.assertEqual(len(received), 1)
        self.assertEqual(
            set(received[0]),
            {"platform", "requested_page_number", "observed_page_number", "diagnostics"},
        )
        self.assertEqual(set(received[0]["diagnostics"]), set(READY_BATCH["diagnostics"]))
        self.assertEqual(received[0]["requested_page_number"], 1)
        self.assertEqual(received[0]["observed_page_number"], 1)
        self.assertNotIn("source_url", received[0])
        self.assertNotIn("query_family", received[0])
        self.assertEqual(READY_BATCH, original)
        self.assertEqual(events[-1]["type"], "summary")

    def test_projection_evidence_sink_failure_is_fail_closed(self):
        def failing_sink(evidence):
            del evidence
            raise RuntimeError("consumer failed")

        with self.assertRaises(EdgeWorkerFailure) as raised:
            list(
                iter_edge_marketplace_events(
                    PAYLOAD,
                    worker_runner=lambda payload, **kwargs: READY_BATCH,
                    projection_evidence_sink=failing_sink,
                )
            )

        self.assertEqual(raised.exception.category, "projection_evidence_sink_failed")
        self.assertFalse(raised.exception.retryable)

    def test_worker_rejects_invalid_or_oversize_output(self):
        cases = (
            FakeProcess("not-json\n"),
            FakeProcess("x" * (200 * 1024 + 1)),
            FakeProcess(json.dumps(READY_BATCH) + "\n" + json.dumps(READY_BATCH)),
        )
        for process in cases:
            with self.subTest(output_length=len(process.stdout.getvalue())):
                with self.assertRaisesRegex(EdgeWorkerFailure, "edge_worker_output_invalid"):
                    run_edge_worker(PAYLOAD, popen_factory=lambda *a, **k: process)

    def test_worker_maps_compact_error_without_copying_raw_output(self):
        envelope = {
            "error": {
                "category": "edge_remote_debugging_disabled",
                "retryable": False,
            }
        }
        process = FakeProcess(json.dumps(envelope) + "\n", returncode=3)

        with self.assertRaises(EdgeWorkerFailure) as raised:
            run_edge_worker(PAYLOAD, popen_factory=lambda *a, **k: process)

        self.assertEqual(raised.exception.category, "edge_remote_debugging_disabled")
        self.assertFalse(raised.exception.retryable)
        self.assertNotIn("DevToolsActivePort", raised.exception.detail)

    def test_timeout_terminates_only_the_owned_process(self):
        process = FakeProcess("", times_out=True)

        with self.assertRaisesRegex(EdgeWorkerFailure, "edge_worker_timeout"):
            run_edge_worker(PAYLOAD, popen_factory=lambda *a, **k: process)

        self.assertTrue(process.terminated)
        self.assertFalse(process.killed)
        self.assertTrue(process.stdin.closed)

    def test_payload_is_rejected_before_process_creation(self):
        created = False

        def factory(*args, **kwargs):
            nonlocal created
            created = True
            return FakeProcess("")

        invalid = {**PAYLOAD, "cookie": "secret"}
        with self.assertRaisesRegex(EdgeWorkerFailure, "edge_worker_input_invalid"):
            run_edge_worker(invalid, popen_factory=factory)
        self.assertFalse(created)

    def test_worker_rejects_non_exact_or_sensitive_diagnostics(self):
        invalid_diagnostics = (
            {**READY_BATCH["diagnostics"], "html": "<main>secret</main>"},
            {**READY_BATCH["diagnostics"], "cookie": "session=secret"},
            {**READY_BATCH["diagnostics"], "text": "page body"},
            {**READY_BATCH["diagnostics"], "source_path": "/Search?keyword=secret"},
            {**READY_BATCH["diagnostics"], "valid_item_count": -1},
            {**READY_BATCH["diagnostics"], "observed_page_number": 513},
            {**READY_BATCH["diagnostics"], "recovery_stage": "retry"},
            {**READY_BATCH["diagnostics"], "recovery_attempt": 3},
        )
        missing = dict(READY_BATCH["diagnostics"])
        del missing["stable_rounds"]
        for diagnostics in (*invalid_diagnostics, missing):
            value = {**READY_BATCH, "diagnostics": diagnostics}
            process = FakeProcess(json.dumps(value, ensure_ascii=False) + "\n")
            with self.subTest(diagnostics=diagnostics), self.assertRaisesRegex(
                EdgeWorkerFailure, "edge_worker_output_invalid"
            ):
                run_edge_worker(PAYLOAD, popen_factory=lambda *a, **k: process)

    def test_next_page_requires_explicit_pagination_enablement(self):
        invalid = {
            **PAYLOAD,
            "session_action": "next",
            "cursor": {**PAYLOAD["cursor"], "page_number": 2},
        }
        with self.assertRaisesRegex(EdgeWorkerFailure, "edge_worker_input_invalid"):
            run_edge_worker(invalid, popen_factory=lambda *a, **k: FakeProcess(""))

    def test_worker_accepts_bounded_recovery_and_rejects_page_513_or_unknown_action(self):
        generated = edge_task_batch(
            MarketplaceQueryDimensions(topic="手机壳"),
            offset=0,
            limit=1,
            platforms=("jd",),
            page_numbers=(512,),
            pagination_enabled=True,
        )
        self.assertEqual(generated[0]["payload"]["cursor"]["page_number"], 512)
        recover = {
            **PAYLOAD,
            "session_action": "recover",
            "pagination_enabled": True,
            "cursor": {**PAYLOAD["cursor"], "page_number": 512},
        }
        recover_batch = {
            **READY_BATCH,
            "cursor": {**READY_BATCH["cursor"], "page_number": 512},
            "observed_page_number": 512,
            "diagnostics": {
                **READY_BATCH["diagnostics"],
                "observed_page_number": 512,
                "recovery_stage": "reproject",
                "recovery_attempt": 2,
            },
        }
        process = FakeProcess(json.dumps(recover_batch, ensure_ascii=False) + "\n")
        accepted = run_edge_worker(recover, popen_factory=lambda *a, **k: process)
        self.assertEqual(accepted["projection_schema_version"], 4)

        invalid_payloads = (
            {
                **PAYLOAD,
                "session_action": "next",
                "pagination_enabled": True,
                "cursor": {**PAYLOAD["cursor"], "page_number": 513},
            },
            {**PAYLOAD, "session_action": "close", "pagination_enabled": True},
        )
        for invalid in invalid_payloads:
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                EdgeWorkerFailure, "edge_worker_input_invalid"
            ):
                run_edge_worker(invalid, popen_factory=lambda *a, **k: FakeProcess(""))


if __name__ == "__main__":
    unittest.main()
