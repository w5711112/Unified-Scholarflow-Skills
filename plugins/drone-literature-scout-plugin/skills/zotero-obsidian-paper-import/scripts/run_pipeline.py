from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from paper_import import (
    accept_doi_candidate,
    build_connector_payload,
    crossref_item_to_candidate,
    fetch_json,
    find_existing_parent_keys,
    is_valid_pdf_bytes,
    load_json,
    normalize_doi,
    read_zotero_items,
    save_json,
    zotero_connector_save_item,
    zotero_connector_upload_attachment,
    zotero_delete_item,
    classify_post_write_matches,
)


def clean_title(title: str) -> str:
    return re.sub(r"\s*[（(][^（）()]*[）)]\s*$", "", title).strip()


def crossref_by_doi(doi: str) -> dict:
    encoded = urllib.parse.quote(doi, safe="")
    data = fetch_json(f"https://api.crossref.org/works/{encoded}")
    return crossref_item_to_candidate(data.get("message", {}))


def crossref_by_title(title: str, rows: int = 20) -> list[dict]:
    query = urllib.parse.urlencode({"query.title": clean_title(title), "rows": rows})
    data = fetch_json(f"https://api.crossref.org/works?{query}")
    return [crossref_item_to_candidate(item) for item in data.get("message", {}).get("items", [])]


def enrich_records(records: list[dict], sleep_seconds: float = 0.7) -> list[dict]:
    output = []
    for paper in records:
        paper = dict(paper)
        target = {
            "title": clean_title(paper["title"]),
            "first_author": paper.get("first_author", ""),
            "venue": paper.get("venue", ""),
            "year": paper.get("year", ""),
        }
        candidates = []
        try:
            if paper.get("doi"):
                candidates = [crossref_by_doi(paper["doi"])]
                paper["doi_evidence"] = "crossref_work"
            else:
                candidates = crossref_by_title(paper["title"])
                paper["doi_candidates"] = candidates
            accepted = next((candidate for candidate in candidates if candidate.get("DOI") and accept_doi_candidate(candidate, target)), None)
            if accepted:
                paper["doi"] = accepted["DOI"]
                for key, value in accepted.items():
                    if key not in {"DOI", "title", "author", "venue", "year"} and value:
                        paper[key] = value
                paper["status"] = "ready"
            elif paper.get("doi"):
                paper["status"] = "metadata_conflict"
            else:
                paper["status"] = "doi_candidate_review" if candidates else "no_public_doi_confirmed"
        except Exception as exc:
            paper["status"] = "manual_review"
            paper["enrichment_error"] = str(exc)
        output.append(paper)
        time.sleep(sleep_seconds)
    return output


def pdf_candidates(paper: dict) -> list[str]:
    urls: list[str] = []
    source = paper.get("source_url") or ""
    if source.lower().endswith(".pdf") or "/pdf" in source.lower():
        urls.append(source)
    if "arxiv.org/abs/" in source:
        urls.append(source.replace("/abs/", "/pdf/"))
    if "proceedings.mlr.press" in source and source.endswith(".html"):
        urls.append(source[:-5] + ".pdf")
    if "roboticsproceedings.org" in source and source.endswith(".html"):
        urls.append(source[:-5] + ".pdf")
    ieee = re.search(r"ieeexplore\.ieee\.org/document/(\d+)", source)
    if ieee:
        urls.append(f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={ieee.group(1)}&ref=")
    if "nature.com/articles/" in source:
        urls.append(source.rstrip("/") + ".pdf")
    if "science.org/doi/" in source:
        urls.append(source.replace("/doi/", "/doi/pdf/"))
    crossref_url = paper.get("url") or ""
    if crossref_url.lower().endswith(".pdf"):
        urls.append(crossref_url)
    return list(dict.fromkeys(urls))


def download_pdf(paper: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{int(paper['number']):03d}.pdf"
    for url in pdf_candidates(paper):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "zotero-obsidian-paper-import/1.0", "Accept": "application/pdf"})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
            if is_valid_pdf_bytes(data):
                target.write_bytes(data)
                paper["pdf_path"] = str(target.resolve())
                paper["pdf_url"] = url
                paper["pdf_status"] = "downloaded"
                return paper
            paper.setdefault("pdf_rejections", []).append({"url": url, "reason": "not_pdf"})
        except Exception as exc:
            paper.setdefault("pdf_rejections", []).append({"url": url, "reason": str(exc)})
    paper["pdf_status"] = "download_failed"
    return paper


def import_records(records: list[dict], execute: bool) -> list[dict]:
    items = read_zotero_items()
    for paper in records:
        items = read_zotero_items()
        existing_keys = find_existing_parent_keys(items, paper)
        if len(existing_keys) > 1:
            paper["duplicate_parent_keys"] = existing_keys
            paper["status"] = "duplicate_merge_required"
            continue
        if existing_keys:
            existing = next(item for item in items if item.get("key") == existing_keys[0])
            paper["parent_key"] = existing.get("key")
            paper["status"] = "duplicate_existing"
            children = fetch_json(f"http://localhost:23119/api/users/0/items/{existing['key']}/children?limit=100")
            pdfs = [child for child in children if child.get("data", {}).get("contentType") == "application/pdf"]
            if pdfs:
                paper["attachment_key"] = pdfs[0].get("key")
            continue
        if not execute:
            paper["status"] = "dry_run_ready"
            continue
        session_id = f"paper-import-{paper['number']}-{int(time.time())}"
        connector_id = f"obsidian-paper-{paper['number']}-{int(time.time() * 1000)}"
        status, body = zotero_connector_save_item(build_connector_payload(paper, session_id, connector_id))
        paper["write_status"] = status
        paper["write_response"] = body.decode("utf-8", errors="replace")
        if status not in (200, 201):
            paper["status"] = "manual_review"
            continue
        time.sleep(0.8)
        after_items = read_zotero_items()
        decision = classify_post_write_matches(items, after_items, paper)
        paper["post_write_parent_keys"] = decision["duplicate_parent_keys"]
        if decision["status"] != "unique_parent":
            paper["duplicate_parent_keys"] = decision["duplicate_parent_keys"]
            rollback_key = decision["rollback_parent_key"]
            if rollback_key:
                rollback_status, rollback_body = zotero_delete_item(rollback_key)
                paper["rollback_parent_key"] = rollback_key
                paper["rollback_status"] = rollback_status
                paper["rollback_response"] = rollback_body.decode("utf-8", errors="replace")
                verified_items = read_zotero_items()
                remaining_keys = find_existing_parent_keys(verified_items, paper)
                paper["post_rollback_parent_keys"] = remaining_keys
                if rollback_status in (200, 204) and len(remaining_keys) == 1:
                    paper["status"] = "write_rolled_back_duplicate"
                else:
                    paper["status"] = "duplicate_merge_required"
            else:
                paper["status"] = decision["status"]
            continue
        items = after_items
        parent = next(item for item in items if item.get("key") == decision["parent_key"])
        paper["parent_key"] = parent.get("key")
        pdf_path = paper.get("pdf_path")
        if pdf_path and Path(pdf_path).exists() and is_valid_pdf_bytes(Path(pdf_path).read_bytes()[:1024]):
            upload_status, upload_body = zotero_connector_upload_attachment(session_id, connector_id, pdf_path, paper.get("pdf_url", ""))
            paper["attachment_write_status"] = upload_status
            paper["attachment_write_response"] = upload_body.decode("utf-8", errors="replace")
            time.sleep(1.0)
            children = fetch_json(f"http://localhost:23119/api/users/0/items/{parent['key']}/children?limit=100")
            pdfs = [child for child in children if child.get("data", {}).get("contentType") == "application/pdf"]
            if upload_status in (200, 201) and pdfs:
                paper["attachment_key"] = pdfs[-1].get("key")
                paper["status"] = "imported_pdf"
            else:
                paper["status"] = "imported_metadata"
        else:
            paper["status"] = "imported_metadata"
        items = read_zotero_items()
    return records


def main(argv: list[str] | None = None) -> int:
    command = (argv or sys.argv[1:])[0] if (argv or sys.argv[1:]) else ""
    args = argv or sys.argv[1:]
    if command == "enrich":
        records = load_json(args[args.index("--input") + 1])
        result = enrich_records(records)
        save_json(args[args.index("--output") + 1], result)
        return 0
    if command == "download":
        records = load_json(args[args.index("--input") + 1])
        output_dir = Path(args[args.index("--output-dir") + 1])
        result = [download_pdf(dict(paper), output_dir) for paper in records]
        save_json(args[args.index("--output") + 1], result)
        return 0
    if command == "import":
        records = load_json(args[args.index("--input") + 1])
        execute = "--execute" in args
        result = import_records(records, execute)
        save_json(args[args.index("--output") + 1], result)
        return 0
    raise SystemExit("usage: run_pipeline.py enrich|download|import --input FILE --output FILE [--output-dir DIR] [--execute]")


if __name__ == "__main__":
    raise SystemExit(main())
