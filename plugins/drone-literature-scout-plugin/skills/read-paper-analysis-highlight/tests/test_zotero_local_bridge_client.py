import gc
import hashlib
import hmac
import importlib.util
import json
import shutil
import threading
import unittest
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "zotero_local_bridge_client.py"
)
FIXTURE_ROOT = (
    Path(__file__).resolve().parents[4]
    / "运行数据"
    / "read-paper-analysis-highlight-test-fixtures"
)


def load_module():
    spec = importlib.util.spec_from_file_location(
        "zotero_local_bridge_client",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Handler(BaseHTTPRequestHandler):
    requests = []
    responses = []

    def log_message(self, _format, *args):
        return

    def _respond(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        decoded = json.loads(body.decode("utf-8")) if body else None
        self.__class__.requests.append({
            "method": self.command,
            "path": self.path,
            "headers": {key.lower(): value for key, value in self.headers.items()},
            "body": decoded,
            "raw_body": body,
        })
        status, payload = self.__class__.responses.pop(0)
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    do_GET = _respond
    do_POST = _respond


class ZoteroLocalBridgeClientTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.case = FIXTURE_ROOT / self._testMethodName
        self.case.mkdir(parents=True, exist_ok=True)
        self.token = "ab" * 32
        self.token_path = self.case / "auth-token"
        self.token_path.write_text(self.token, encoding="ascii")
        _Handler.requests = []
        _Handler.responses = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = self.module.ZoteroLocalBridgeClient(
            token_path=self.token_path,
            base_url=f"http://127.0.0.1:{self.server.server_port}",
            timeout=1.0,
            now=lambda: 1_000,
        )
        self.request = {
            "schema_version": 1,
            "operation_id": "paper-001-native-v1",
            "library": {"type": "user", "id": 1},
            "attachment": {"key": "ABCD2345", "content_type": "application/pdf"},
            "annotations": [{
                "stable_id": "paper-001-a001",
                "type": "highlight",
                "page_index": 0,
                "position": {"pageIndex": 0, "rects": [[1.0, 2.5, 3.0, 4.5]]},
                "color": "#ffd900",
                "comment": "结论：证据。\n机制：说明。",
                "text": "Evidence",
            }],
            "allowed_native_keys": [],
            "deletions": [],
        }

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        shutil.rmtree(self.case, ignore_errors=True)

    def test_health_preflight_and_apply_use_json_and_short_lived_hmac(self):
        _Handler.responses = [
            (200, {
                "plugin_version": "2.0.0",
                "zotero_version": "9.0.6",
                "schema_version": 1,
                "supported_annotation_types": ["highlight", "image"],
                "initialized": True,
            }),
            (200, {
                "plan_digest": "1" * 64,
                "snapshot_digest": "2" * 64,
                "counts": {"create": 1, "update": 0, "delete": 0, "no_op": 0},
                "conflicts": [],
                "receipt": "signed-receipt",
                "actual": [],
            }),
            (200, {
                "counts": {"create": 1, "update": 0, "delete": 0, "no_op": 0},
                "native_keys": ["ANN00001"],
                "actual": [],
                "snapshot_digest": "3" * 64,
            }),
        ]

        health = self.client.health()
        preflight = self.client.preflight(self.request)
        applied = self.client.apply(self.request, preflight)

        self.assertTrue(health["initialized"])
        self.assertEqual(applied["native_keys"], ["ANN00001"])
        self.assertEqual([item["method"] for item in _Handler.requests], ["GET", "POST", "POST"])
        self.assertEqual(
            [item["path"] for item in _Handler.requests],
            [
                "/zotero-local-bridge/v1/health",
                "/zotero-local-bridge/v1/annotations/preflight",
                "/zotero-local-bridge/v1/annotations/apply",
            ],
        )

        preflight_request = _Handler.requests[1]
        self.assertEqual(preflight_request["headers"]["content-type"], "application/json")
        self.assertNotIn(self.token, preflight_request["raw_body"].decode("utf-8"))
        auth = preflight_request["headers"]["x-zotero-local-bridge-auth"]
        timestamp, signature = auth.split(".")
        canonical = self.module.canonical_json(self.request)
        body_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        message = (
            "POST\n/zotero-local-bridge/v1/annotations/preflight\n"
            f"{timestamp}\n{body_digest}"
        )
        expected = hmac.new(
            self.token.encode("ascii"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(signature, expected)

        apply_body = _Handler.requests[2]["body"]
        self.assertEqual(apply_body["plan_digest"], "1" * 64)
        self.assertEqual(apply_body["snapshot_digest"], "2" * 64)
        self.assertEqual(apply_body["receipt"], "signed-receipt")

    def test_conflict_is_typed_and_never_retried(self):
        _Handler.responses = [(409, {
            "error": {"code": "snapshot_changed", "message": "changed"},
        })]

        with self.assertRaises(self.module.BridgeConflict) as raised:
            self.client.preflight(self.request)

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.code, "snapshot_changed")
        self.assertEqual(len(_Handler.requests), 1)

    def test_http_error_response_is_closed(self):
        _Handler.responses = [(409, {
            "error": {"code": "snapshot_changed", "message": "changed"},
        })]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            try:
                self.client.preflight(self.request)
            except self.module.BridgeConflict:
                pass
            gc.collect()

        resource_warnings = [
            warning for warning in caught
            if issubclass(warning.category, ResourceWarning)
        ]
        self.assertEqual(resource_warnings, [])

    def test_503_retries_once_only_after_fresh_healthy_result(self):
        _Handler.responses = [
            (503, {"error": {"code": "not_initialized", "message": "wait"}}),
            (200, {
                "plugin_version": "2.0.0",
                "zotero_version": "9.0.6",
                "schema_version": 1,
                "supported_annotation_types": ["highlight", "image"],
                "initialized": True,
            }),
            (200, {
                "plan_digest": "1" * 64,
                "snapshot_digest": "2" * 64,
                "counts": {"create": 1, "update": 0, "delete": 0, "no_op": 0},
                "conflicts": [],
                "receipt": "signed-receipt",
                "actual": [],
            }),
        ]

        result = self.client.preflight(self.request)

        self.assertEqual(result["receipt"], "signed-receipt")
        self.assertEqual(
            [item["path"] for item in _Handler.requests],
            [
                "/zotero-local-bridge/v1/annotations/preflight",
                "/zotero-local-bridge/v1/health",
                "/zotero-local-bridge/v1/annotations/preflight",
            ],
        )


if __name__ == "__main__":
    unittest.main()
