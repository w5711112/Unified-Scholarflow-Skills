from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
CLIENT_SCRIPTS = (
    PLUGIN_ROOT / "skills" / "read-paper-analysis-highlight" / "scripts"
)
sys.path.insert(0, str(CLIENT_SCRIPTS))

from zotero_local_bridge_client import (  # noqa: E402
    BridgeConflict,
    BridgeInternalError,
    ZoteroLocalBridgeClient,
)


FIXTURE_FILE = "zotero-local-bridge-integration-fixture.json"
FAILURE_PATH = "/test/zotero-local-bridge/failure"


def get_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "zotero-local-bridge-test"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any]) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "zotero-local-bridge-test",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def annotation(
    stable_id: str,
    annotation_type: str,
    comment: str,
    sort_index: str,
    rect: list[int],
    *,
    native_key: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "stable_id": stable_id,
        "type": annotation_type,
        "page_index": 0,
        "page_label": "1",
        "sort_index": sort_index,
        "position": {"pageIndex": 0, "rects": [rect]},
        "color": "#ffd400" if annotation_type == "highlight" else "#2ea8e5",
        "comment": comment,
    }
    if annotation_type == "highlight":
        value["text"] = "fixture highlighted text"
    if native_key:
        value["native_key"] = native_key
    return value


def plan(
    operation_id: str,
    library_id: int,
    attachment_key: str,
    annotations: list[dict[str, Any]],
    *,
    allowed_native_keys: list[str] | None = None,
    deletions: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "operation_id": operation_id,
        "library": {"type": "user", "id": library_id},
        "attachment": {
            "key": attachment_key,
            "content_type": "application/pdf",
        },
        "annotations": annotations,
        "allowed_native_keys": allowed_native_keys or [],
        "deletions": deletions or [],
    }


def child_items(base_url: str, library_id: int, attachment_key: str) -> list[dict[str, Any]]:
    value = get_json(f"{base_url}/test/zotero-local-bridge/fixture")
    if not isinstance(value, dict) or value.get("ready") is not True:
        raise AssertionError("integration fixture probe is not ready")
    if int(value.get("library_id", -1)) != library_id:
        raise AssertionError("integration fixture returned the wrong library")
    if value.get("attachment_key") != attachment_key:
        raise AssertionError("integration fixture returned the wrong attachment")
    annotations = value.get("annotations")
    if not isinstance(annotations, list):
        raise AssertionError("integration fixture returned non-list annotations")
    return annotations

def item_by_key(items: list[dict[str, Any]], key: str) -> dict[str, Any]:
    for item in items:
        if item.get("key") == key or item.get("data", {}).get("key") == key:
            return item
    raise AssertionError(f"child item {key} was not found")


def run(profile: Path, base_url: str) -> dict[str, Any]:
    fixture = json.loads((profile / FIXTURE_FILE).read_text(encoding="utf-8"))
    library_id = int(fixture["library_id"])
    attachment_key = str(fixture["attachment_key"])
    manual_key = str(fixture["manual_annotation_key"])
    client = ZoteroLocalBridgeClient(
        token_path=profile / "zotero-local-bridge" / "auth-token",
        base_url=base_url,
    )

    health = client.health()
    if health.get("plugin_version") != "2.0.0" or health.get("initialized") is not True:
        raise AssertionError(f"unexpected health response: {health}")

    before = child_items(base_url, library_id, attachment_key)
    manual_before = item_by_key(before, manual_key)

    create_plan = plan(
        "isolated-create",
        library_id,
        attachment_key,
        [
            annotation(
                "isolated-highlight",
                "highlight",
                "created highlight",
                "00000|000010|00020",
                [10, 20, 30, 40],
            ),
            annotation(
                "isolated-image",
                "image",
                "created image",
                "00000|000020|00050",
                [50, 50, 80, 90],
            ),
        ],
    )
    create_check = client.preflight(create_plan)
    after_preflight = child_items(base_url, library_id, attachment_key)
    if before != after_preflight:
        raise AssertionError("preflight changed Zotero child items")
    if create_check["counts"] != {"create": 2, "update": 0, "delete": 0, "no_op": 0}:
        raise AssertionError(f"unexpected create preflight: {create_check['counts']}")

    unknown_plan = plan(
        "isolated-unknown-delete",
        library_id,
        attachment_key,
        [],
        allowed_native_keys=[manual_key],
        deletions=[
            {"native_key": manual_key, "before_fingerprint": "d" * 64}
        ],
    )
    try:
        client.preflight(unknown_plan)
    except BridgeConflict as error:
        conflicts = error.payload.get("conflicts", []) if isinstance(error.payload, dict) else []
        if not any(value.get("code") == "unknown_annotation" for value in conflicts):
            raise AssertionError(f"wrong unknown-annotation conflict: {error.payload}") from error
    else:
        raise AssertionError("destructive operation accepted an unknown manual annotation")

    created = client.apply(create_plan, create_check)
    if created["counts"]["create"] != 2 or len(created["native_keys"]) != 2:
        raise AssertionError(f"create readback mismatch: {created}")
    created_keys = list(created["native_keys"])

    reconciliation = client.preflight(create_plan)
    if reconciliation["counts"]["no_op"] != 2 or reconciliation["counts"]["create"] != 0:
        raise AssertionError(f"response-loss reconciliation failed: {reconciliation}")

    update_plan = plan(
        "isolated-update",
        library_id,
        attachment_key,
        [
            annotation(
                "isolated-highlight",
                "highlight",
                "updated highlight",
                "00000|000010|00020",
                [10, 20, 30, 40],
                native_key=created_keys[0],
            ),
            annotation(
                "isolated-image",
                "image",
                "updated image",
                "00000|000020|00050",
                [50, 50, 80, 90],
                native_key=created_keys[1],
            ),
        ],
        allowed_native_keys=created_keys,
    )
    updated = client.apply(update_plan, client.preflight(update_plan))
    if updated["counts"]["update"] != 2:
        raise AssertionError(f"update readback mismatch: {updated}")

    rollback_plan = plan(
        "isolated-rollback",
        library_id,
        attachment_key,
        [
            annotation(
                "rollback-one",
                "highlight",
                "rollback one",
                "00000|000030|00100",
                [100, 100, 120, 110],
            ),
            annotation(
                "rollback-two",
                "image",
                "rollback two",
                "00000|000040|00120",
                [120, 120, 150, 150],
            ),
        ],
    )
    rollback_check = client.preflight(rollback_plan)
    armed = post_json(base_url + FAILURE_PATH, {"action": "arm", "fail_on_call": 2})
    if armed != {"armed": True, "fail_on_call": 2}:
        raise AssertionError(f"failure injection did not arm: {armed}")
    try:
        try:
            client.apply(rollback_plan, rollback_check)
        except BridgeInternalError:
            pass
        else:
            raise AssertionError("injected transaction failure was not returned")
    finally:
        post_json(base_url + FAILURE_PATH, {"action": "disarm"})
    rollback_after = client.preflight(rollback_plan)
    if rollback_after["counts"]["create"] != 2 or rollback_after["counts"]["no_op"] != 0:
        raise AssertionError(f"failed transaction left visible residue: {rollback_after}")

    delete_plan = plan(
        "isolated-delete",
        library_id,
        attachment_key,
        [],
        allowed_native_keys=created_keys,
        deletions=[
            {
                "native_key": state["native_key"],
                "before_fingerprint": state["fingerprint"],
            }
            for state in updated["actual"]
        ],
    )
    deleted = client.apply(delete_plan, client.preflight(delete_plan))
    if deleted["counts"]["delete"] != 2:
        raise AssertionError(f"exact delete failed: {deleted}")

    final_children = child_items(base_url, library_id, attachment_key)
    manual_after = item_by_key(final_children, manual_key)
    if manual_before != manual_after:
        raise AssertionError("manual annotation changed during controlled operations")
    remaining_keys = {
        item.get("key") or item.get("data", {}).get("key")
        for item in final_children
    }
    if any(key in remaining_keys for key in created_keys):
        raise AssertionError("controlled annotations remained after delete")

    return {
        "health": health,
        "preflight_no_write": True,
        "created": 2,
        "updated": 2,
        "deleted": 2,
        "duplicate_additions": 0,
        "failed_batch_residue": 0,
        "unknown_user_changes": 0,
        "manual_annotation_key": manual_key,
        "controlled_native_keys": created_keys,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:23120")
    args = parser.parse_args()
    print(json.dumps(run(args.profile.resolve(), args.base_url), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
