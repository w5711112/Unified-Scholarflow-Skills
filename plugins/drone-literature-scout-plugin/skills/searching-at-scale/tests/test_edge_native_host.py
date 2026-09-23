from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import subprocess
import queue
import threading
import time
import unittest
import uuid


SKILL_ROOT = Path(__file__).resolve().parents[1]
HOST_EXE = SKILL_ROOT / "native-host" / "SearchingAtScaleNativeHost.v2.exe"
HOST_SOURCE = SKILL_ROOT / "native-host" / "SearchingAtScaleNativeHost.cs"
TASK_ID = "0123456789abcdef0123456789abcdef"


def frame(payload: object) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return struct.pack("<I", len(encoded)) + encoded


def read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise AssertionError("broker stream ended before one complete frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream) -> dict[str, object]:
    size = struct.unpack("<I", read_exact(stream, 4))[0]
    if size <= 0 or size > 256 * 1024:
        raise AssertionError("broker frame size is invalid")
    value = json.loads(read_exact(stream, size))
    if not isinstance(value, dict):
        raise AssertionError("broker frame must contain an object")
    return value


def read_frame_with_timeout(stream, timeout: float = 1.0) -> dict[str, object]:
    outcomes: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def read_one() -> None:
        try:
            outcomes.put((True, read_frame(stream)))
        except BaseException as error:  # pragma: no cover - forwarded below
            outcomes.put((False, error))

    threading.Thread(target=read_one, daemon=True).start()
    try:
        succeeded, value = outcomes.get(timeout=timeout)
    except queue.Empty as error:
        raise AssertionError("broker did not emit one frame before timeout") from error
    if not succeeded:
        raise value  # type: ignore[misc]
    assert isinstance(value, dict)
    return value


def task(task_id: str = TASK_ID) -> dict[str, object]:
    return {
        "type": "task",
        "protocol_version": 3,
        "operation": "search",
        "task_id": task_id,
        "platform": "jd",
        "query": "小米15",
        "query_family": "小米15:default",
        "cursor": {"cursor_id": "jd:xiaomi15", "ordinal": 0, "page_number": 1},
        "deadline_seconds": 30,
        "max_items": 100,
        "session_action": "start",
        "pagination_enabled": False,
        "pagination_route": None,
    }


def result(
    task_id: str = TASK_ID,
    page_number: int = 1,
) -> dict[str, object]:
    return {
        "type": "result",
        "protocol_version": 3,
        "task_id": task_id,
        "payload": {
            "projection_schema_version": 4,
            "capabilities": [
                "stable_card_fields_v2",
                "verified_pagination_v1",
                "resilient_pagination_v1",
            ],
            "platform": "jd",
            "page_state": "ready",
            "source_url": "https://search.jd.com/Search",
            "query_family": "小米15:default",
            "cursor": {
                "cursor_id": "jd:xiaomi15",
                "page_number": page_number,
                "status": "advanced",
            },
            "observed_page_number": page_number,
            "pagination_state": "pagination_unverified",
            "has_next_page": False,
            "sku_digest": "100123",
            "diagnostics": {
                "document_ready_state": "complete",
                "data_sku_node_count": 1,
                "candidate_anchor_count": 1,
                "valid_item_count": 1,
                "collection_elapsed_ms": 1000,
                "stable_rounds": 2,
                "observed_page_number": page_number,
                "recovery_stage": "initial",
                "recovery_attempt": 0,
                "source_path": "/Search",
            },
            "items": [{
                "product_id": "100123",
                "title": "小米15 手机",
                "url": "https://item.jd.com/100123.html",
                "price": "3999.00",
                "shop": None,
                "commit": None,
                "good_rate": None,
                "promo": None,
                "stock": None,
                "image": None,
            }],
        },
    }


class HostProcess:
    def __init__(self) -> None:
        self.pipe_name = f"codex.searching_at_scale.test.{uuid.uuid4().hex}"
        environment = dict(os.environ)
        environment["SEARCHING_AT_SCALE_PIPE_NAME"] = self.pipe_name
        self.process = subprocess.Popen(
            [str(HOST_EXE)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )

    def connect(self):
        path = rf"\\.\pipe\{self.pipe_name}"
        deadline = time.monotonic() + 5
        while True:
            try:
                return open(path, "r+b", buffering=0)
            except FileNotFoundError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)

    def close(self) -> None:
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()
        self.process.wait(timeout=5)
        assert self.process.stderr is not None
        stderr = self.process.stderr.read()
        self.process.stderr.close()
        if self.process.stdout is not None:
            self.process.stdout.close()
        if stderr:
            raise AssertionError(f"native host wrote stderr: {stderr!r}")


class EdgeNativeHostTests(unittest.TestCase):
    def assert_invalid_extension_result(
        self,
        invalid_result: dict[str, object],
        request: dict[str, object] | None = None,
    ) -> None:
        broker_task = task() if request is None else request
        host = HostProcess()
        try:
            with host.connect() as client:
                client.write(frame(broker_task))
                assert host.process.stdout is not None
                self.assertEqual(
                    read_frame_with_timeout(host.process.stdout), broker_task
                )
                assert host.process.stdin is not None
                host.process.stdin.write(frame(invalid_result))
                host.process.stdin.flush()
                self.assertEqual(read_frame(client), {
                    "type": "error",
                    "protocol_version": 3,
                    "task_id": TASK_ID,
                    "category": "edge_native_message_invalid",
                    "retryable": False,
                })
        finally:
            host.close()

    def test_task_and_matching_extension_result_are_forwarded_bidirectionally(self):
        host = HostProcess()
        try:
            with host.connect() as client:
                client.write(frame(task()))
                assert host.process.stdout is not None
                self.assertEqual(read_frame_with_timeout(host.process.stdout), task())
                assert host.process.stdin is not None
                host.process.stdin.write(frame(result()))
                host.process.stdin.flush()
                self.assertEqual(read_frame(client), result())
        finally:
            host.close()

    def test_second_task_is_rejected_as_busy_while_first_is_in_flight(self):
        host = HostProcess()
        other_id = "fedcba9876543210fedcba9876543210"
        try:
            with host.connect() as first:
                first.write(frame(task()))
                assert host.process.stdout is not None
                self.assertEqual(read_frame_with_timeout(host.process.stdout), task())
                with host.connect() as second:
                    second.write(frame(task(other_id)))
                    self.assertEqual(read_frame(second), {
                        "type": "error",
                        "protocol_version": 3,
                        "task_id": other_id,
                        "category": "edge_background_bridge_busy",
                        "retryable": True,
                    })
                assert host.process.stdin is not None
                host.process.stdin.write(frame(result()))
                host.process.stdin.flush()
                self.assertEqual(read_frame(first), result())
        finally:
            host.close()

    def test_unsupported_operation_is_rejected_without_forwarding(self):
        host = HostProcess()
        try:
            with host.connect() as client:
                client.write(frame({**task(), "operation": "detail"}))
                self.assertEqual(read_frame(client), {
                    "type": "error",
                    "protocol_version": 3,
                    "task_id": TASK_ID,
                    "category": "edge_operation_unsupported",
                    "retryable": False,
                })
        finally:
            host.close()

    def test_next_page_without_explicit_enablement_is_rejected(self):
        host = HostProcess()
        try:
            with host.connect() as client:
                unsafe = task()
                unsafe["session_action"] = "next"
                unsafe["cursor"] = {
                    "cursor_id": "jd:xiaomi15", "ordinal": 0, "page_number": 2
                }
                client.write(frame(unsafe))
                self.assertEqual(
                    read_frame(client)["category"], "edge_native_message_invalid"
                )
        finally:
            host.close()

    def test_protocol_three_is_exact_for_tasks_and_results(self):
        for invalid_version in (2, 4):
            invalid = {**task(), "protocol_version": invalid_version}
            host = HostProcess()
            try:
                with self.subTest(task_protocol=invalid_version), host.connect() as client:
                    client.write(frame(invalid))
                    response = read_frame(client)
                    self.assertEqual(response["protocol_version"], 3)
                    self.assertEqual(response["category"], "edge_native_message_invalid")
            finally:
                host.close()

        for invalid_version in (2, 4):
            host = HostProcess()
            try:
                with self.subTest(result_protocol=invalid_version), host.connect() as client:
                    client.write(frame(task()))
                    assert host.process.stdout is not None
                    self.assertEqual(read_frame_with_timeout(host.process.stdout), task())
                    invalid = {**result(), "protocol_version": invalid_version}
                    assert host.process.stdin is not None
                    host.process.stdin.write(frame(invalid))
                    host.process.stdin.flush()
                    response = read_frame(client)
                    self.assertEqual(response["protocol_version"], 3)
                    self.assertEqual(response["category"], "edge_native_message_invalid")
            finally:
                host.close()

    def test_start_next_and_recover_actions_use_the_production_request_shape(self):
        cases = (
            ("start", 1, False),
            ("next", 2, True),
            ("recover", 2, True),
        )
        for action, page_number, pagination_enabled in cases:
            request = task()
            request["session_action"] = action
            request["pagination_enabled"] = pagination_enabled
            request["cursor"] = {
                "cursor_id": "jd:xiaomi15",
                "ordinal": 0,
                "page_number": page_number,
            }
            host = HostProcess()
            try:
                with self.subTest(action=action), host.connect() as client:
                    client.write(frame(request))
                    assert host.process.stdout is not None
                    self.assertEqual(read_frame_with_timeout(host.process.stdout), request)
                    assert host.process.stdin is not None
                    valid_result = result(page_number=page_number)
                    host.process.stdin.write(frame(valid_result))
                    host.process.stdin.flush()
                    self.assertEqual(read_frame(client), valid_result)
            finally:
                host.close()

    def test_pagination_route_is_forwarded_verbatim_to_the_extension(self):
        request = task()
        request["session_action"] = "start"
        request["pagination_enabled"] = True
        request["pagination_route"] = "experimental_url"
        host = HostProcess()
        try:
            with host.connect() as client:
                client.write(frame(request))
                assert host.process.stdout is not None
                self.assertEqual(read_frame_with_timeout(host.process.stdout), request)
                assert host.process.stdin is not None
                host.process.stdin.write(frame(result()))
                host.process.stdin.flush()
                self.assertEqual(read_frame(client), result())
        finally:
            host.close()

    def test_page_512_is_accepted_while_0_and_513_fail_closed(self):
        boundary = task()
        boundary["session_action"] = "next"
        boundary["pagination_enabled"] = True
        boundary["cursor"] = {
            "cursor_id": "jd:xiaomi15", "ordinal": 0, "page_number": 512
        }
        host = HostProcess()
        try:
            with host.connect() as client:
                client.write(frame(boundary))
                assert host.process.stdout is not None
                self.assertEqual(read_frame_with_timeout(host.process.stdout), boundary)
                assert host.process.stdin is not None
                boundary_result = result(page_number=512)
                host.process.stdin.write(frame(boundary_result))
                host.process.stdin.flush()
                self.assertEqual(read_frame(client), boundary_result)
        finally:
            host.close()

        for invalid_page in (0, 513):
            invalid = task()
            invalid["session_action"] = "next"
            invalid["pagination_enabled"] = True
            invalid["cursor"] = {
                "cursor_id": "jd:xiaomi15",
                "ordinal": 0,
                "page_number": invalid_page,
            }
            host = HostProcess()
            try:
                with self.subTest(page_number=invalid_page), host.connect() as client:
                    client.write(frame(invalid))
                    response = read_frame(client)
                    self.assertEqual(response["protocol_version"], 3)
                    self.assertEqual(response["category"], "edge_native_message_invalid")
            finally:
                host.close()

    def test_unknown_action_and_sensitive_extra_fields_fail_closed(self):
        invalid_tasks = []
        close = task()
        close["session_action"] = "close"
        close["pagination_enabled"] = True
        invalid_tasks.append(close)
        for key in ("html", "cookie", "query_string", "raw_text"):
            invalid_tasks.append({**task(), key: "sensitive"})

        for invalid in invalid_tasks:
            host = HostProcess()
            try:
                with self.subTest(keys=tuple(invalid)), host.connect() as client:
                    client.write(frame(invalid))
                    response = read_frame(client)
                    self.assertEqual(response["protocol_version"], 3)
                    self.assertEqual(response["category"], "edge_native_message_invalid")
            finally:
                host.close()

    def test_result_requires_schema_four_exact_capabilities_and_diagnostics(self):
        invalid_results: list[tuple[str, dict[str, object]]] = []

        extra_diagnostic = result()
        extra_diagnostic["payload"]["diagnostics"]["html"] = "<body>secret</body>"
        invalid_results.append(("diagnostics extra html", extra_diagnostic))

        missing_diagnostics = result()
        del missing_diagnostics["payload"]["diagnostics"]
        invalid_results.append(("missing diagnostics", missing_diagnostics))

        stale_schema = result()
        stale_schema["payload"]["projection_schema_version"] = 3
        invalid_results.append(("schema 3", stale_schema))

        missing_capability = result()
        missing_capability["payload"]["capabilities"] = [
            "stable_card_fields_v2",
            "verified_pagination_v1",
        ]
        invalid_results.append(("missing capability", missing_capability))

        reordered_capabilities = result()
        reordered_capabilities["payload"]["capabilities"] = [
            "verified_pagination_v1",
            "stable_card_fields_v2",
            "resilient_pagination_v1",
        ]
        invalid_results.append(("reordered capabilities", reordered_capabilities))

        extra_capability = result()
        extra_capability["payload"]["capabilities"] = [
            "stable_card_fields_v2",
            "verified_pagination_v1",
            "resilient_pagination_v1",
            "raw_dom_v1",
        ]
        invalid_results.append(("extra capability", extra_capability))

        for name, invalid in invalid_results:
            with self.subTest(name=name):
                self.assert_invalid_extension_result(invalid)

    def test_result_rejects_unsafe_source_and_invalid_diagnostic_values(self):
        invalid_results: list[tuple[str, dict[str, object]]] = []

        for name, source_url in (
            ("query", "https://search.jd.com/Search?keyword=x"),
            ("userinfo", "https://user@search.jd.com/Search"),
            ("fragment", "https://search.jd.com/Search#items"),
            ("wrong path", "https://search.jd.com/search"),
        ):
            invalid = result()
            invalid["payload"]["source_url"] = source_url
            invalid_results.append((f"source_url {name}", invalid))

        diagnostic_mutations = (
            ("source_path query", "source_path", "/Search?keyword=x"),
            ("source_path wrong path", "source_path", "/search"),
            ("negative node count", "data_sku_node_count", -1),
            ("boolean node count", "data_sku_node_count", True),
            ("wrong observed page", "observed_page_number", 2),
            ("unknown recovery stage", "recovery_stage", "third"),
            ("recovery attempt above two", "recovery_attempt", 3),
        )
        for name, key, value in diagnostic_mutations:
            invalid = result()
            invalid["payload"]["diagnostics"][key] = value
            invalid_results.append((name, invalid))

        missing_diagnostic = result()
        del missing_diagnostic["payload"]["diagnostics"]["stable_rounds"]
        invalid_results.append(("missing diagnostic key", missing_diagnostic))

        for name, invalid in invalid_results:
            with self.subTest(name=name):
                self.assert_invalid_extension_result(invalid)

    def test_result_items_are_exact_typed_and_privacy_safe(self):
        invalid_results: list[tuple[str, dict[str, object]]] = []

        extra_item_key = result()
        extra_item_key["payload"]["items"][0]["html"] = "<div>secret</div>"
        invalid_results.append(("extra html", extra_item_key))

        missing_item_key = result()
        del missing_item_key["payload"]["items"][0]["image"]
        invalid_results.append(("missing image", missing_item_key))

        invalid_title = result()
        invalid_title["payload"]["items"][0]["title"] = {"raw_text": "secret"}
        invalid_results.append(("title object", invalid_title))

        invalid_card_field = result()
        invalid_card_field["payload"]["items"][0]["price"] = ["3999.00"]
        invalid_results.append(("card field list", invalid_card_field))

        item_query = result()
        item_query["payload"]["items"][0]["url"] = (
            "https://item.jd.com/100123.html?tracking=secret"
        )
        invalid_results.append(("JD item query", item_query))

        item_userinfo = result()
        item_userinfo["payload"]["items"][0]["url"] = (
            "https://user@item.jd.com/100123.html"
        )
        invalid_results.append(("JD item userinfo", item_userinfo))

        non_numeric_product = result()
        non_numeric_product["payload"]["items"][0]["product_id"] = "sku-100123"
        invalid_results.append(("non-numeric product id", non_numeric_product))

        non_array_items = result()
        non_array_items["payload"]["items"] = {"raw_text": "secret"}
        invalid_results.append(("items object", non_array_items))

        for name, invalid in invalid_results:
            with self.subTest(name=name):
                self.assert_invalid_extension_result(invalid)

        for key in ("html", "cookie", "query_string", "raw_text"):
            host = HostProcess()
            try:
                with self.subTest(result_payload_key=key), host.connect() as client:
                    client.write(frame(task()))
                    assert host.process.stdout is not None
                    self.assertEqual(read_frame_with_timeout(host.process.stdout), task())
                    invalid_result = result()
                    invalid_result["payload"][key] = "sensitive"
                    assert host.process.stdin is not None
                    host.process.stdin.write(frame(invalid_result))
                    host.process.stdin.flush()
                    response = read_frame(client)
                    self.assertEqual(response["protocol_version"], 3)
                    self.assertEqual(response["category"], "edge_native_message_invalid")
            finally:
                host.close()

    def test_native_stdin_eof_disconnects_pending_client_and_exits(self):
        host = HostProcess()
        with host.connect() as client:
            client.write(frame(task()))
            assert host.process.stdout is not None
            self.assertEqual(read_frame_with_timeout(host.process.stdout), task())
            assert host.process.stdin is not None
            host.process.stdin.close()
            self.assertEqual(read_frame(client)["category"], "edge_background_bridge_disconnected")
        host.process.wait(timeout=5)
        self.assertEqual(host.process.returncode, 0)
        assert host.process.stderr is not None
        self.assertEqual(host.process.stderr.read(), b"")
        host.process.stderr.close()
        assert host.process.stdout is not None
        host.process.stdout.close()

    def test_source_builds_a_current_sid_only_pipe_acl_and_no_tcp_listener(self):
        source = HOST_SOURCE.read_text(encoding="utf-8")

        self.assertIn("WindowsIdentity.GetCurrent().User", source)
        self.assertIn("SetAccessRuleProtection(true, false)", source)
        self.assertIn("NamedPipeServerStream", source)
        self.assertNotIn("TcpClient", source)
        self.assertNotIn("TcpListener", source)


if __name__ == "__main__":
    unittest.main()
