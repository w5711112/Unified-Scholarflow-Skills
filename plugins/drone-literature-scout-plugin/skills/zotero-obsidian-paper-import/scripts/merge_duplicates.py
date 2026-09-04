from __future__ import annotations

import argparse
import copy
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from paper_import import (
    fetch_json,
    find_existing_parent_keys,
    normalize_doi,
    read_zotero_items,
    save_json,
    zotero_delete_item,
)


PROTECTED_FIELDS = {
    "key",
    "version",
    "dateAdded",
    "dateModified",
    "parentItem",
    "tags",
    "collections",
    "relations",
    "seeAlso",
}


def _union_values(left: list[Any] | None, right: list[Any] | None, key: str | None = None) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in (left or []) + (right or []):
        identity = json.dumps(value, ensure_ascii=False, sort_keys=True) if key is None else str(value.get(key, ""))
        if identity not in seen:
            result.append(copy.deepcopy(value))
            seen.add(identity)
    return result


def merged_parent_data(keep_item: dict[str, Any], source_item: dict[str, Any]) -> dict[str, Any]:
    keep = keep_item.get("data", keep_item)
    source = source_item.get("data", source_item)
    merged = {
        key: copy.deepcopy(value)
        for key, value in keep.items()
        if key not in {"key", "version"}
    }
    for key, value in source.items():
        if key in PROTECTED_FIELDS or value in (None, "", [], {}):
            continue
        merged[key] = copy.deepcopy(value)
    merged["tags"] = _union_values(keep.get("tags"), source.get("tags"), "tag")
    merged["collections"] = _union_values(keep.get("collections"), source.get("collections"))
    return merged


def put_item(item_key: str, data: dict[str, Any], version: int, base_url: str = "http://localhost:23119") -> tuple[int, bytes]:
    request = urllib.request.Request(
        f"{base_url}/api/users/0/items/{item_key}",
        data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
        method="PUT",
        headers={
            "Content-Type": "application/json",
            "If-Unmodified-Since-Version": str(version),
            "User-Agent": "zotero-obsidian-paper-import/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def item_by_key(items: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("key") == key), None)


def all_children(items: list[dict[str, Any]], parent_key: str) -> list[dict[str, Any]]:
    return [item for item in items if item.get("data", {}).get("parentItem") == parent_key]


def merge_one(plan: dict[str, Any], execute: bool, base_url: str = "http://localhost:23119") -> dict[str, Any]:
    result = {
        "doi": plan["doi"],
        "numbers": plan.get("numbers", []),
        "keep_parent_key": plan["keep_parent_key"],
        "metadata_source_key": plan["metadata_source_key"],
        "remove_parent_keys": plan["remove_parent_keys"],
        "status": "dry_run" if not execute else "manual_review",
        "actions": [],
    }
    items = read_zotero_items(base_url)
    keep = item_by_key(items, plan["keep_parent_key"])
    source = item_by_key(items, plan["metadata_source_key"])
    if not keep or not source:
        result["reason"] = "planned parent key is missing"
        return result
    paper = {
        "title": source.get("data", {}).get("title", ""),
        "doi": normalize_doi(plan["doi"]),
    }
    matched = find_existing_parent_keys(items, paper)
    if sorted(matched) != sorted([plan["keep_parent_key"], *plan["remove_parent_keys"]]):
        result["reason"] = f"live duplicate keys differ from plan: {matched}"
        return result
    remove_children = {
        key: [child.get("key") for child in all_children(items, key)]
        for key in plan["remove_parent_keys"]
    }
    if any(remove_children.values()):
        result["reason"] = f"refuse to delete parent with children: {remove_children}"
        return result
    if not execute:
        result["status"] = "ready_to_execute"
        result["remove_children"] = remove_children
        return result

    merged = merged_parent_data(keep, source)
    put_status, put_body = put_item(
        plan["keep_parent_key"],
        merged,
        int(keep.get("version", 0)),
        base_url,
    )
    result["update_status"] = put_status
    result["update_response"] = put_body.decode("utf-8", errors="replace")
    if put_status not in (200, 204):
        result["reason"] = "metadata update failed"
        return result

    for remove_key in plan["remove_parent_keys"]:
        delete_status, delete_body = zotero_delete_item(remove_key, base_url)
        result["actions"].append({
            "remove_parent_key": remove_key,
            "delete_status": delete_status,
            "delete_response": delete_body.decode("utf-8", errors="replace"),
        })
        if delete_status not in (200, 204):
            result["reason"] = "duplicate parent deletion failed"
            return result

    verified = read_zotero_items(base_url)
    final_matches = find_existing_parent_keys(verified, paper)
    result["post_merge_parent_keys"] = final_matches
    remaining_keep = item_by_key(verified, plan["keep_parent_key"])
    original_pdf_keys = [
        key
        for keys in plan.get("pdf_attachment_keys_by_parent", {}).values()
        if keys
        for key in keys
    ]
    final_children = all_children(verified, plan["keep_parent_key"])
    final_pdf_keys = [
        child.get("key")
        for child in final_children
        if child.get("data", {}).get("contentType") == "application/pdf"
    ]
    result["post_merge_pdf_keys"] = final_pdf_keys
    if len(final_matches) == 1 and final_matches[0] == plan["keep_parent_key"] and remaining_keep and set(original_pdf_keys).issubset(final_pdf_keys):
        result["status"] = "merged_verified"
    else:
        result["status"] = "manual_review"
        result["reason"] = "post-merge identity or attachment verification failed"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge verified duplicate Zotero parent items without changing retained attachment keys")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--doi")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    groups = [
        group
        for group in plan.get("groups", [])
        if not args.doi or normalize_doi(group.get("doi")) == normalize_doi(args.doi)
    ]
    if args.limit is not None:
        groups = groups[:args.limit]
    results = [merge_one(group, args.execute) for group in groups]
    save_json(args.output, {
        "plan": str(Path(args.plan).resolve()),
        "execute": args.execute,
        "results": results,
    })
    print(json.dumps({
        "execute": args.execute,
        "groups": len(results),
        "statuses": {status: sum(result["status"] == status for result in results) for status in sorted({result["status"] for result in results})},
    }, ensure_ascii=False))
    return 0 if all(result["status"] in {"ready_to_execute", "merged_verified"} for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())