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
    del data, version, base_url
    return 501, f'Local API update unsupported for {item_key}; supported native merge bridge required'.encode('utf-8')


def item_by_key(items: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get("key") == key), None)


def all_children(items: list[dict[str, Any]], parent_key: str) -> list[dict[str, Any]]:
    return [item for item in items if item.get("data", {}).get("parentItem") == parent_key]


def merge_one(plan: dict[str, Any], execute: bool, base_url: str = "http://127.0.0.1:23119",
              *, client=None, journal_path: Path | None = None) -> dict[str, Any]:
    import hashlib
    result = {"doi": plan.get("doi", ""), "keep_parent_key": plan["keep_parent_key"],
              "remove_parent_keys": plan["remove_parent_keys"], "status": "manual_review"}
    try:
        evidence_path = Path(plan.get("identity_evidence_file", ""))
        if not evidence_path.is_file():
            raise ValueError("identity evidence file required")
        raw = evidence_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != plan.get("identity_evidence_sha256"):
            raise ValueError("identity evidence hash changed")
        evidence = json.loads(raw)
        expected = [plan["keep_parent_key"], *plan["remove_parent_keys"]]
        if evidence.get("decision") != "same_publication" or sorted(evidence.get("parent_keys", [])) != sorted(expected):
            raise ValueError("identity evidence does not authorize these keys")
        if not evidence.get("title") or not evidence.get("source_url"):
            raise ValueError("identity source evidence missing")
        if plan.get("metadata_source_key", plan["keep_parent_key"]) != plan["keep_parent_key"]:
            raise ValueError("retain the verified metadata parent; metadata overwrite is not supported")

        items = read_zotero_items(base_url)
        keep = item_by_key(items, plan["keep_parent_key"])
        if not keep:
            raise ValueError("retained parent missing")
        paper = {"title": evidence["title"], "doi": normalize_doi(plan.get("doi"))}
        if sorted(find_existing_parent_keys(items, paper)) != sorted(expected):
            raise ValueError("live duplicate keys differ from reviewed identity evidence")
        request = {"schema_version": 1, "operation_id": plan.get("operation_id", "merge-" + "-".join(expected)),
                   "library_id": plan["library_id"], "master_key": plan["keep_parent_key"],
                   "other_keys": plan["remove_parent_keys"], "identity_evidence_sha256": plan["identity_evidence_sha256"]}
        if evidence.get('formal_metadata'):
            request['formal_metadata'] = evidence['formal_metadata']
        if evidence.get('preprint_metadata'):
            request['preprint_metadata'] = evidence['preprint_metadata']
        if client is None:
            raise ValueError("supported native bridge client required")
        preflight = client._send("POST", "/zotero-local-bridge/v1/merge/preflight", request)
        result["prewrite_library_snapshot"] = items
        result["preflight"] = preflight
        if not execute:
            result["status"] = "ready_to_execute"
            return result
        if journal_path is None:
            raise ValueError("write-ahead journal path required")
        result["status"] = "apply_pending_readback"
        save_json(journal_path, result)
        # Never resend a write after a timeout: reconcile the saved keys instead.
        result["apply"] = client._send("POST", "/zotero-local-bridge/v1/merge/apply",
                                     {**request, "snapshot_digest": preflight["snapshot_digest"], "receipt": preflight["receipt"]})
        verified = read_zotero_items(base_url)
        result["postwrite_library_snapshot"] = verified
        matches = find_existing_parent_keys(verified, paper)
        result["post_merge_parent_keys"] = matches
        original_pdf_keys = {row["key"] for row in items if row.get("data", {}).get("parentItem") in expected
                             and row.get("data", {}).get("contentType") == "application/pdf"}
        final_pdf_keys = {row["key"] for row in all_children(verified, plan["keep_parent_key"])
                          if row.get("data", {}).get("contentType") == "application/pdf"}
        result["post_merge_pdf_keys"] = sorted(final_pdf_keys)
        if matches != [plan["keep_parent_key"]] or not original_pdf_keys.issubset(final_pdf_keys):
            raise ValueError("post-merge uniqueness or attachment reconciliation failed")
        result["status"] = "merged_verified"
    except Exception as exc:
        result["status"] = "manual_review"
        result["reason"] = str(exc)
    finally:
        if journal_path is not None:
            save_json(journal_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge verified duplicate Zotero parent items without changing retained attachment keys")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--doi")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--token-path", required=True, type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:23119")
    args = parser.parse_args(argv)
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    groups = [
        group
        for group in plan.get("groups", [])
        if not args.doi or normalize_doi(group.get("doi")) == normalize_doi(args.doi)
    ]
    if args.limit is not None:
        groups = groups[:args.limit]
    import sys
    sibling = Path(__file__).resolve().parents[2] / "read-paper-analysis-highlight" / "scripts"
    if sibling.is_dir():
        sys.path.insert(0, str(sibling))
    from zotero_local_bridge_client import ZoteroLocalBridgeClient
    client = ZoteroLocalBridgeClient(token_path=args.token_path, base_url=args.base_url, timeout=30)
    results = []
    for index, group in enumerate(groups):
        journal = Path(args.output).with_name(Path(args.output).stem + f"-group-{index}.json")
        result = merge_one(group, args.execute, args.base_url, client=client, journal_path=journal)
        results.append(result)
        if result['status'] == 'manual_review':
            break
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
