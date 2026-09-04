from __future__ import annotations

import argparse
import copy
import html
import json
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable


DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
HEADING_RE = re.compile(r"^###\s+(\d+)\.\s+(.*?)\s*$")
SOURCE_RE = re.compile(r"^-\s+\*\*来源\*\*：(.+)$")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if "未找到" in text or "not found" in text.lower():
        return None
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.I)
    text = re.sub(r"^doi\s*:\s*", "", text, flags=re.I)
    match = DOI_RE.search(text)
    if not match:
        return None
    doi = match.group(0).rstrip(".,;:)]}>")
    return doi.lower() or None


def _title_key(value: str) -> str:
    value = html.unescape(value or "").lower()
    return re.sub(r"[^a-z0-9]+", "", value)


def _identity_title_key(value: str) -> str:
    """Normalize title variants while preserving enough identity for duplicate blocking."""
    text = html.unescape(value or "").strip()
    text = re.sub(r"\s*[（(][^（）()]*[）)]\s*$", "", text)
    return re.sub(r"[^\w]+", "", text.casefold(), flags=re.UNICODE)


def _first_link(value: str) -> str | None:
    match = re.search(r"\]\((https?://[^)]+)\)", value)
    return match.group(1) if match else None


def _authors_from_text(value: str) -> list[dict[str, str]]:
    authors = []
    for name in value.split(","):
        name = name.strip()
        if not name:
            continue
        parts = name.split()
        if len(parts) == 1:
            authors.append({"name": parts[0], "creatorType": "author"})
        else:
            authors.append({"firstName": " ".join(parts[:-1]), "lastName": parts[-1], "creatorType": "author"})
    return authors


def parse_paper_index(path: str | Path, start: int, end: int) -> list[dict[str, Any]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        heading = HEADING_RE.match(line)
        if heading:
            if current is not None and start <= current["number"] <= end:
                records.append(current)
            number = int(heading.group(1))
            title = heading.group(2)
            year_match = YEAR_RE.search(title)
            current = {
                "number": number,
                "title": title,
                "year": year_match.group(0) if year_match else "",
                "source_url": None,
                "doi": None,
                "authors": [],
                "status": "unresolved",
            }
            continue
        if current is None:
            continue
        source = SOURCE_RE.match(line)
        if source:
            source_text = source.group(1)
            current["source_url"] = _first_link(source_text)
            current["doi"] = normalize_doi(source_text)
            paper_id = re.search(r"\^([\w-]+)", source_text)
            if paper_id:
                current["paper_id"] = paper_id.group(1)
    if current is not None and start <= current["number"] <= end:
        records.append(current)
    records.sort(key=lambda row: row["number"])
    expected = list(range(start, end + 1))
    actual = [row["number"] for row in records]
    if actual != expected:
        raise ValueError(f"paper number range is not contiguous: expected {expected[:3]}...{expected[-3:]}, got {actual[:3]}...{actual[-3:]}")
    return records


def accept_doi_candidate(candidate: dict[str, Any], target: dict[str, Any]) -> bool:
    candidate_title = _title_key(str(candidate.get("title", "")))
    target_title = _title_key(str(target.get("title", "")))
    if not candidate_title or not target_title:
        return False
    title_score = SequenceMatcher(None, candidate_title, target_title).ratio()
    if title_score < 0.92:
        return False
    author = str(candidate.get("author") or candidate.get("first_author") or "").lower()
    target_author = str(target.get("first_author") or target.get("author") or "").lower()
    if author and target_author and not (author in target_author or target_author in author):
        return False
    matches = 0
    if author and target_author:
        matches += 1
    if str(candidate.get("venue", "")).lower() and str(candidate.get("venue", "")).lower() in str(target.get("venue", "")).lower():
        matches += 1
    if str(candidate.get("year", "")) and str(candidate.get("year", "")) == str(target.get("year", "")):
        matches += 1
    return matches >= 1 if not target_author else matches >= 2


def is_valid_pdf_bytes(data: bytes) -> bool:
    return len(data) >= 256 and data[:5] == b"%PDF-" and not data[:128].lstrip().lower().startswith((b"<!doctype", b"<html"))


def build_connector_payload(paper: dict[str, Any], session_id: str, connector_id: str) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": connector_id,
        "itemType": paper.get("itemType", "journalArticle"),
        "title": paper["title"],
        "creators": paper.get("authors", []),
        "tags": [{"tag": f"obsidian-paper-{paper['number']}"}],
        "collections": [],
        "url": paper.get("source_url") or (f"https://doi.org/{paper['doi']}" if paper.get("doi") else ""),
    }
    if paper.get("doi"):
        item["DOI"] = paper["doi"]
    for field in ("abstractNote", "date", "publicationTitle", "proceedingsTitle", "volume", "issue", "pages", "publisher", "ISSN"):
        if paper.get(field):
            item[field] = paper[field]
    return {"items": [item], "uri": item["url"], "sessionID": session_id}


def update_source_line(line: str, attachment_key: str | None) -> str:
    if not attachment_key:
        return line
    link = f"[Zotero的PDF](zotero://open-pdf/library/items/{attachment_key})"
    pattern = r"\[Zotero的PDF\]\(zotero://open-pdf/library/items/[^)]+\)"
    if re.search(pattern, line):
        return re.sub(pattern, link, line)
    if "^paper-" in line:
        return line.replace(" ^paper-", f"，{link} ^paper-", 1)
    return line.rstrip() + f"，{link}"


def fetch_json(url: str, timeout: int = 30) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "zotero-obsidian-paper-import/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def crossref_item_to_candidate(item: dict[str, Any]) -> dict[str, Any]:
    authors = item.get("author", [])
    first_author = authors[0] if authors else {}
    title = (item.get("title") or [""])[0]
    published = item.get("published-print") or item.get("published-online") or item.get("issued") or {}
    date_parts = (published.get("date-parts") or [[""]])[0]
    return {
        "DOI": normalize_doi(item.get("DOI")),
        "title": title,
        "author": first_author.get("family") or first_author.get("name", ""),
        "authors": [{k: v for k, v in {"firstName": a.get("given", ""), "lastName": a.get("family", ""), "creatorType": "author"}.items() if v} for a in authors],
        "venue": item.get("container-title", [""])[0],
        "year": str(date_parts[0]) if date_parts else "",
        "url": item.get("URL", ""),
        "abstractNote": re.sub(r"<[^>]+>", "", item.get("abstract", "")),
        "publicationTitle": item.get("container-title", [""])[0] if item.get("type") == "journal-article" else "",
        "proceedingsTitle": item.get("container-title", [""])[0] if item.get("type") != "journal-article" else "",
        "volume": item.get("volume", ""),
        "issue": item.get("issue", ""),
        "pages": item.get("page", ""),
        "publisher": item.get("publisher", ""),
        "ISSN": (item.get("ISSN") or [""])[0],
        "itemType": "journalArticle" if item.get("type") == "journal-article" else "conferencePaper",
    }


def query_crossref(title: str, rows: int = 5) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"query.bibliographic": title, "rows": rows})
    data = fetch_json(f"https://api.crossref.org/works?{query}")
    return [crossref_item_to_candidate(item) for item in data.get("message", {}).get("items", [])]


def _request_json(url: str, payload: dict[str, Any]) -> tuple[int, bytes]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json", "X-Zotero-Connector-API-Version": "3"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def zotero_connector_save_item(payload: dict[str, Any], base_url: str = "http://localhost:23119") -> tuple[int, bytes]:
    return _request_json(f"{base_url}/connector/saveItems", payload)


def zotero_delete_item(item_key: str, base_url: str = "http://localhost:23119") -> tuple[int, bytes]:
    encoded_key = urllib.parse.quote(item_key, safe="")
    request = urllib.request.Request(
        f"{base_url}/api/users/0/items/{encoded_key}",
        method="DELETE",
        headers={"User-Agent": "zotero-obsidian-paper-import/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def zotero_connector_upload_attachment(session_id: str, connector_id: str, pdf_path: str | Path, source_url: str = "", base_url: str = "http://localhost:23119") -> tuple[int, bytes]:
    path = Path(pdf_path)
    data = path.read_bytes()
    metadata = json.dumps({"sessionID": session_id, "parentItemID": connector_id, "title": path.name, "url": source_url}, ensure_ascii=False)
    request = urllib.request.Request(f"{base_url}/connector/saveAttachment", data=data, method="POST", headers={"Content-Type": "application/pdf", "Content-Length": str(len(data)), "X-Metadata": metadata})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def read_zotero_items(base_url: str = "http://localhost:23119") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    start = 0
    page_size = 100
    while True:
        page = fetch_json(f"{base_url}/api/users/0/items?limit={page_size}&start={start}")
        if not isinstance(page, list):
            raise ValueError("Zotero items API returned a non-list payload")
        items.extend(page)
        if len(page) < page_size:
            return items
        start += len(page)


def find_existing_parent_keys(items: Iterable[dict[str, Any]], paper: dict[str, Any]) -> list[str]:
    """Return all parent keys matching DOI or a normalized title identity."""
    doi = normalize_doi(paper.get("doi"))
    title_key = _identity_title_key(paper.get("title", ""))
    matches: list[str] = []
    for item in items:
        data = item.get("data", {})
        if data.get("itemType") in {"attachment", "note"} or data.get("parentItem"):
            continue
        key = item.get("key")
        if not key:
            continue
        doi_match = doi and normalize_doi(data.get("DOI")) == doi
        title_match = title_key and _identity_title_key(data.get("title", "")) == title_key
        if doi_match or title_match:
            matches.append(key)
    return matches


def classify_post_write_matches(
    before_items: Iterable[dict[str, Any]],
    after_items: Iterable[dict[str, Any]],
    paper: dict[str, Any],
) -> dict[str, Any]:
    before_keys = set(find_existing_parent_keys(before_items, paper))
    after_keys = find_existing_parent_keys(after_items, paper)
    result: dict[str, Any] = {
        "status": "",
        "parent_key": after_keys[0] if len(after_keys) == 1 else "",
        "duplicate_parent_keys": after_keys,
        "rollback_parent_key": "",
    }
    if len(after_keys) == 1:
        result["status"] = "unique_parent"
        return result
    if len(after_keys) > 1:
        newly_created = [key for key in after_keys if key not in before_keys]
        if len(newly_created) == 1:
            result["rollback_parent_key"] = newly_created[0]
        result["status"] = "duplicate_merge_required"
        return result
    result["status"] = "manual_review"
    return result


def find_existing(items: Iterable[dict[str, Any]], paper: dict[str, Any]) -> dict[str, Any] | None:
    matches = find_existing_parent_keys(items, paper)
    if not matches:
        return None
    wanted = matches[0]
    return next((item for item in items if item.get("key") == wanted), None)


def group_duplicate_parents(items: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for item in items:
        data = item.get("data", {})
        if data.get("itemType") == "attachment":
            continue
        doi = normalize_doi(data.get("DOI"))
        key = item.get("key")
        if not doi or not key:
            continue
        groups.setdefault(doi, []).append(key)
    return {doi: keys for doi, keys in groups.items() if len(keys) > 1}

def update_obsidian_file(path: str | Path, attachment_by_number: dict[int, str], backup: bool = True) -> int:
    path = Path(path)
    original = path.read_text(encoding="utf-8")
    if backup:
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    lines = original.splitlines(keepends=True)
    current_number: int | None = None
    changed = 0
    output: list[str] = []
    for line in lines:
        heading = HEADING_RE.match(line.rstrip("\r\n"))
        if heading:
            current_number = int(heading.group(1))
        if current_number in attachment_by_number and SOURCE_RE.match(line.rstrip("\r\n")):
            newline = "\n" if line.endswith("\n") else ""
            updated = update_source_line(line.rstrip("\r\n"), attachment_by_number[current_number])
            line = updated + newline
            if line != output[-1] if output else True:
                changed += 1
        output.append(line)
    path.write_text("".join(output), encoding="utf-8", newline="")
    return changed


def save_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Obsidian -> Zotero paper import helper")
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract")
    extract.add_argument("--obsidian", required=True)
    extract.add_argument("--output", required=True)
    extract.add_argument("--start", type=int, default=12)
    extract.add_argument("--end", type=int, default=102)
    crossref = sub.add_parser("crossref")
    crossref.add_argument("--manifest", required=True)
    crossref.add_argument("--output", required=True)
    crossref.add_argument("--sleep", type=float, default=0.5)
    imp = sub.add_parser("import")
    imp.add_argument("--manifest", required=True)
    imp.add_argument("--state-dir", required=True)
    imp.add_argument("--start", type=int, default=12)
    imp.add_argument("--end", type=int, default=102)
    imp.add_argument("--batch-size", type=int, default=10)
    imp.add_argument("--execute", action="store_true")
    backfill = sub.add_parser("backfill")
    backfill.add_argument("--manifest", required=True)
    backfill.add_argument("--obsidian", required=True)
    backfill.add_argument("--no-backup", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.command == "extract":
        save_json(args.output, parse_paper_index(args.obsidian, args.start, args.end))
        return 0
    if args.command == "crossref":
        records = load_json(args.manifest)
        for paper in records:
            if paper.get("doi"):
                continue
            candidates = query_crossref(paper["title"])
            target = {"title": paper["title"], "year": paper.get("year", ""), "venue": paper["title"]}
            accepted = next((c for c in candidates if accept_doi_candidate(c, target)), None)
            paper["doi_candidates"] = candidates
            if accepted:
                paper["doi"] = accepted["DOI"]
                paper.update({k: v for k, v in accepted.items() if k not in {"DOI", "title", "author", "venue", "year"} and v})
                paper["status"] = "ready"
            else:
                paper["status"] = "doi_candidate_review" if candidates else "no_public_doi_confirmed"
            time.sleep(args.sleep)
        save_json(args.output, records)
        return 0
    if args.command == "backfill":
        records = load_json(args.manifest)
        mapping = {int(p["number"]): p["attachment_key"] for p in records if p.get("attachment_key") and p.get("status") in {"imported_pdf", "duplicate_existing"}}
        update_obsidian_file(args.obsidian, mapping, backup=not args.no_backup)
        return 0
    if args.command == "import":
        records = load_json(args.manifest)
        state_dir = Path(args.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        items = read_zotero_items()
        duplicate_groups = group_duplicate_parents(items)
        selected = [p for p in records if args.start <= int(p["number"]) <= args.end]
        for paper in selected:
            items = read_zotero_items()
            existing_keys = find_existing_parent_keys(items, paper)
            if len(existing_keys) > 1:
                paper["duplicate_parent_keys"] = existing_keys
                paper["status"] = "duplicate_merge_required"
                continue
            if existing_keys:
                paper["parent_key"] = existing_keys[0]
                paper["status"] = "duplicate_existing"
                continue
            if not args.execute:
                paper["status"] = "dry_run_ready" if paper.get("doi") else "doi_candidate_review"
                continue
            session_id = f"paper-import-{paper['number']}-{uuid.uuid4().hex}"
            connector_id = f"obsidian-paper-{paper['number']}-{uuid.uuid4().hex}"
            status, body = zotero_connector_save_item(build_connector_payload(paper, session_id, connector_id))
            paper["write_status"] = status
            paper["write_response"] = body.decode("utf-8", errors="replace")
            if status not in (200, 201):
                paper["status"] = "manual_review"
                continue
            time.sleep(0.5)
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
            parent = find_existing(after_items, paper)
            if not parent:
                paper["status"] = "manual_review"
                continue
            paper["parent_key"] = parent.get("key")
            pdf_path = paper.get("pdf_path")
            if pdf_path and Path(pdf_path).exists() and is_valid_pdf_bytes(Path(pdf_path).read_bytes()[:1024]):
                status, body = zotero_connector_upload_attachment(session_id, connector_id, pdf_path, paper.get("source_url", ""))
                paper["attachment_write_status"] = status
                time.sleep(0.8)
                children = fetch_json(f"http://localhost:23119/api/users/0/items/{parent['key']}/children?limit=100")
                attachments = [x for x in children if x.get("data", {}).get("contentType") == "application/pdf"]
                if status in (200, 201) and attachments:
                    paper["attachment_key"] = attachments[-1].get("key")
                    paper["status"] = "imported_pdf"
                else:
                    paper["status"] = "imported_metadata"
            else:
                paper["status"] = "imported_metadata"
            items = read_zotero_items()
            duplicate_groups = group_duplicate_parents(items)
        save_json(state_dir / "manifest-after-import.json", records)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
