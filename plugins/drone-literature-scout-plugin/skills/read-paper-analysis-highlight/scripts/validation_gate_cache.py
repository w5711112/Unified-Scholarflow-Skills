from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def fingerprint_inputs(
    file_hashes: dict[str, str],
    values: dict[str, Any] | None = None,
) -> str:
    payload = {
        "file_hashes": file_hashes,
        "values": values or {},
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def should_run_gate(
    cache: dict[str, Any],
    gate_name: str,
    fingerprint: str,
    *,
    final: bool = False,
    affected: bool = False,
) -> bool:
    if final or affected:
        return True
    gate = cache.get("gates", {}).get(gate_name)
    if not isinstance(gate, dict):
        return True
    if gate.get("fingerprint") != fingerprint:
        return True
    return gate.get("passed") is not True


def record_gate_result(
    cache: dict[str, Any],
    gate_name: str,
    fingerprint: str,
    passed: bool,
    details: str = "",
) -> dict[str, Any]:
    updated = copy.deepcopy(cache)
    updated.setdefault("schema_version", 1)
    gates = updated.setdefault("gates", {})
    gates[gate_name] = {
        "fingerprint": fingerprint,
        "passed": passed is True,
        "details": str(details),
    }
    return updated


def serialize_cache(cache: dict[str, Any]) -> str:
    return _canonical_json(cache) + "\n"
