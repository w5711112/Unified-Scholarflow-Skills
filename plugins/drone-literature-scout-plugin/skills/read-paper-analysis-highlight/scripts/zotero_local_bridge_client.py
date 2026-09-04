from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


HEALTH_PATH = "/zotero-local-bridge/v1/health"
PREFLIGHT_PATH = "/zotero-local-bridge/v1/annotations/preflight"
APPLY_PATH = "/zotero-local-bridge/v1/annotations/apply"
TOKEN_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class BridgeError(RuntimeError):
    def __init__(self, status: int | None, code: str, message: str, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.payload = payload


class BridgeBadRequest(BridgeError):
    pass


class BridgeAuthenticationError(BridgeError):
    pass


class BridgeNotFound(BridgeError):
    pass


class BridgeConflict(BridgeError):
    pass


class BridgeValidationError(BridgeError):
    pass


class BridgeInternalError(BridgeError):
    pass


class BridgeUnavailable(BridgeError):
    pass


STATUS_ERRORS = {
    400: BridgeBadRequest,
    401: BridgeAuthenticationError,
    403: BridgeAuthenticationError,
    404: BridgeNotFound,
    409: BridgeConflict,
    422: BridgeValidationError,
    500: BridgeInternalError,
    503: BridgeUnavailable,
}


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite JSON numbers are not allowed")
        if value.is_integer():
            return int(value)
        if 0 < abs(value) < 1e-6 or abs(value) >= 1e21:
            raise ValueError("JSON numbers outside the bridge canonical range are not allowed")
        return value
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    raise ValueError(f"unsupported JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _error_payload(raw: bytes) -> tuple[Any, str, str]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "invalid_response", "bridge returned a non-JSON error"
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    code = error.get("code", "bridge_error") if isinstance(error, dict) else "bridge_error"
    message = (
        error.get("message", "bridge request failed")
        if isinstance(error, dict)
        else "bridge request failed"
    )
    return payload, str(code), str(message)


class ZoteroLocalBridgeClient:
    def __init__(
        self,
        *,
        token_path: str | Path,
        base_url: str = "http://127.0.0.1:23119",
        timeout: float = 5.0,
        now: Callable[[], int | float] = time.time,
    ):
        parsed = urllib.parse.urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("base_url must be an HTTP 127.0.0.1 origin")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.token_path = Path(token_path)
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.now = now

    def _token(self) -> str:
        try:
            token = self.token_path.read_text(encoding="ascii").strip()
        except (OSError, UnicodeError) as error:
            raise BridgeAuthenticationError(
                None,
                "token_unavailable",
                "Zotero Local Bridge authentication token is unavailable",
            ) from error
        if not TOKEN_PATTERN.fullmatch(token):
            raise BridgeAuthenticationError(
                None,
                "invalid_token",
                "Zotero Local Bridge authentication token is invalid",
            )
        return token

    def _authentication(self, path: str, body: Any) -> str:
        timestamp = int(self.now())
        digest = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
        message = f"POST\n{path}\n{timestamp}\n{digest}"
        signature = hmac.new(
            self._token().encode("ascii"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{timestamp}.{signature}"

    def _send(self, method: str, path: str, body: Any = None) -> dict[str, Any]:
        data = None if body is None else canonical_json(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["X-Zotero-Local-Bridge-Auth"] = self._authentication(path, body)
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            try:
                raw = error.read()
            finally:
                error.close()
            payload, code, message = _error_payload(raw)
            exception = STATUS_ERRORS.get(error.code, BridgeError)
            raise exception(error.code, code, message, payload) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise BridgeUnavailable(
                None,
                "connection_failed",
                "Zotero Local Bridge is unavailable",
            ) from error
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BridgeError(
                None,
                "invalid_response",
                "Zotero Local Bridge returned invalid JSON",
            ) from error
        if not isinstance(payload, dict):
            raise BridgeError(
                None,
                "invalid_response",
                "Zotero Local Bridge returned a non-object response",
                payload,
            )
        return payload

    def health(self) -> dict[str, Any]:
        return self._send("GET", HEALTH_PATH)

    def _post_with_condition_retry(
        self,
        path: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return self._send("POST", path, body)
        except BridgeUnavailable:
            health = self.health()
            if health.get("initialized") is not True:
                raise
            return self._send("POST", path, body)

    def preflight(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._post_with_condition_retry(PREFLIGHT_PATH, request)

    def apply(
        self,
        request: dict[str, Any],
        preflight_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(preflight_receipt, dict):
            raise ValueError("preflight receipt must be an object")
        try:
            body = {
                **request,
                "plan_digest": preflight_receipt["plan_digest"],
                "snapshot_digest": preflight_receipt["snapshot_digest"],
                "receipt": preflight_receipt["receipt"],
            }
        except KeyError as error:
            raise ValueError(f"preflight receipt is missing {error.args[0]}") from error
        return self._post_with_condition_retry(APPLY_PATH, body)
