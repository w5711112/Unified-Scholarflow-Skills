from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_import import (
    HEADING_RE,
    SOURCE_RE,
    _title_key,
    fetch_json,
    normalize_doi,
    parse_paper_index,
    read_zotero_items,
)
from run_pipeline import clean_title


def source_links(path: Path, start: int, end: int) -> dict[int, dict[str, str]]:
    result: dict[int, dict[str, str]] = {}
    current: int | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            current = int(heading.group(1))
            continue
        if current is None or not start <= current <= end:
            continue
        source = SOURCE_RE.match(line)
        if not source:
            continue
        text = source.group(1)
        attachment = re.search(r"zotero://open-pdf/library/items/([A-Z0-9]+)", text)
        result[current] = {
            "attachment_key": attachment.group(1) if attachment else "",
            "doi": normalize_doi(text) or "",
        }
    return result


def is_numbered_pdf_title(title: str) -> bool:
    return len(title) == 7 and title[:3].isdigit() and title[3:] == ".pdf"


def parent_summary(item: dict[str, Any], children_by_parent: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    data = item.get("data", {})
    key = item.get("key", "")
    creators = data.get("creators") or []
    attachments = [
        child.get("key")
        for child in children_by_parent.get(key, [])
        if child.get("data", {}).get("contentType") == "application/pdf"
    ]
    return {
        "key": key,
        "title": data.get("title", ""),
        "DOI": normalize_doi(data.get("DOI")) or "",
        "creators": len(creators),
        "date": data.get("date", ""),
        "publicationTitle": data.get("publicationTitle", ""),
        "proceedingsTitle": data.get("proceedingsTitle", ""),
        "publisher": data.get("publisher", ""),
        "pages": data.get("pages", ""),
        "url": data.get("url", ""),
        "pdf_attachment_keys": attachments,
    }


def audit(
    obsidian_path: Path,
    output_path: Path,
    start: int = 12,
    end: int = 102,
    skip: set[int] | None = None,
) -> dict[str, Any]:
    skip = skip or set()
    records = parse_paper_index(obsidian_path, start, end)
    links = source_links(obsidian_path, start, end)
    items = read_zotero_items()
    parents = [item for item in items if item.get("data", {}).get("itemType") != "attachment"]
    attachments = [item for item in items if item.get("data", {}).get("itemType") == "attachment"]

    children_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    numbered_by_number: dict[int, list[dict[str, Any]]] = defaultdict(list)
    attachment_by_key: dict[str, dict[str, Any]] = {}
    for attachment in attachments:
        key = attachment.get("key", "")
        attachment_by_key[key] = attachment
        parent_key = attachment.get("data", {}).get("parentItem")
        if parent_key:
            children_by_parent[parent_key].append(attachment)
        title = attachment.get("data", {}).get("title", "")
        if is_numbered_pdf_title(title):
            numbered_by_number[int(title[:3])].append(attachment)

    parent_summaries = {
        item.get("key", ""): parent_summary(item, children_by_parent)
        for item in parents
    }
    doi_groups: dict[str, list[str]] = defaultdict(list)
    title_year_groups: dict[str, list[str]] = defaultdict(list)
    for item in parents:
        summary = parent_summaries[item.get("key", "")]
        if summary["DOI"]:
            doi_groups[summary["DOI"]].append(summary["key"])
        title = _title_key(clean_title(summary["title"]))
        year = re.search(r"\b(?:19|20)\d{2}\b", summary["date"] or summary["title"])
        if title and year:
            title_year_groups[f"{title}:{year.group(0)}"].append(summary["key"])

    duplicate_doi = {
        doi: keys for doi, keys in doi_groups.items() if len(keys) > 1
    }
    duplicate_title_year = {
        group: keys for group, keys in title_year_groups.items() if len(keys) > 1
    }

    paper_audit: list[dict[str, Any]] = []
    for record in records:
        number = int(record["number"])
        if number in skip:
            continue
        target_title = _title_key(clean_title(record["title"]))
        target_doi = normalize_doi(record.get("doi")) or links.get(number, {}).get("doi", "")
        doi_parent_keys = [
            key
            for key, summary in parent_summaries.items()
            if target_doi and summary["DOI"] == target_doi
        ]
        title_parent_keys = [
            key
            for key, summary in parent_summaries.items()
            if target_title and _title_key(clean_title(summary["title"])) == target_title
        ]
        link_key = links.get(number, {}).get("attachment_key", "")
        link_attachment = attachment_by_key.get(link_key)
        numbered_keys = [item.get("key", "") for item in numbered_by_number.get(number, [])]
        metadata_missing: list[str] = []
        candidate_keys = list(dict.fromkeys(doi_parent_keys + title_parent_keys))
        for parent_key in candidate_keys:
            summary = parent_summaries[parent_key]
            if target_doi and not summary["DOI"]:
                metadata_missing.append(f"{parent_key}:DOI")
            if summary["creators"] == 0:
                metadata_missing.append(f"{parent_key}:creators")
            if not summary["date"]:
                metadata_missing.append(f"{parent_key}:date")
            if not summary["publicationTitle"] and not summary["proceedingsTitle"]:
                metadata_missing.append(f"{parent_key}:venue")
            if not summary["url"]:
                metadata_missing.append(f"{parent_key}:url")
        paper_audit.append(
            {
                "number": number,
                "index_title": record["title"],
                "index_doi": target_doi,
                "obsidian_attachment_key": link_key,
                "linked_attachment_exists": bool(link_attachment),
                "linked_parent_key": link_attachment.get("data", {}).get("parentItem") if link_attachment else "",
                "numbered_attachment_keys": numbered_keys,
                "doi_parent_keys": doi_parent_keys,
                "title_parent_keys": title_parent_keys,
                "metadata_missing": sorted(set(metadata_missing)),
            }
        )

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {"start": start, "end": end, "skip": sorted(skip)},
        "zotero": {
            "items": len(items),
            "parents": len(parents),
            "attachments": len(attachments),
            "numbered_pdf_numbers": len(numbered_by_number),
            "duplicate_doi_groups": duplicate_doi,
            "duplicate_title_year_groups": duplicate_title_year,
        },
        "papers": paper_audit,
        "parent_summaries": parent_summaries,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--obsidian", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start", type=int, default=12)
    parser.add_argument("--end", type=int, default=102)
    parser.add_argument("--skip", nargs="*", type=int, default=[89, 99])
    args = parser.parse_args()
    result = audit(
        Path(args.obsidian),
        Path(args.output),
        args.start,
        args.end,
        set(args.skip),
    )
    print(json.dumps(result["zotero"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
