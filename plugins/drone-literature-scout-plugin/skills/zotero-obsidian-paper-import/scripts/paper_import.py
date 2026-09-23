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
import os
import tempfile
import hashlib
from contextlib import contextmanager
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
        "url": paper.get("formal_source_url") or paper.get("source_url") or (f"https://doi.org/{paper['doi']}" if paper.get("doi") else ""),
    }
    if paper.get("doi"):
        item["DOI"] = paper["doi"]
    for field in ("abstractNote", "date", "publicationTitle", "proceedingsTitle", "volume", "issue", "pages", "publisher", "ISSN"):
        if paper.get(field):
            item[field] = paper[field]
    payload = {"items": [item], "uri": item["url"], "sessionID": session_id}
    if paper.get('publication_verification'):
        payload['_publication_verification'] = paper['publication_verification']
    return payload


def validate_publication_pdf(row: dict, proof: dict | None) -> None:
    """Bind expert-reviewed official identity to the exact file and outgoing metadata.

    This enforces the receipt; semantic review of the official page/PDF remains
    the importing agent's responsibility. A URL or a boolean alone is no proof.
    """
    import hashlib
    if not isinstance(proof, dict) or not proof.get('reviewed_at') or not proof.get('identity_basis'):
        raise ValueError('publication_and_pdf_review_required')
    publication = proof.get('publication')
    pdf = proof.get('pdf')
    if not isinstance(publication, dict) or not isinstance(pdf, dict):
        raise ValueError('publication_and_pdf_review_required')
    fields = ('title', 'itemType', 'creators', 'date', 'DOI', 'publicationTitle', 'proceedingsTitle', 'url')
    if any(row.get(field, '') != publication.get(field, '') for field in fields):
        raise ValueError('reviewed_publication_metadata_changed')
    if not row.get('title') or not row.get('creators') or not row.get('date') or not (
            row.get('publicationTitle') or row.get('proceedingsTitle')):
        raise ValueError('complete_publication_metadata_required')
    if row.get('itemType') not in {'journalArticle', 'conferencePaper'} or pdf.get('version') != 'version_of_record':
        raise ValueError('formal_publication_and_pdf_required')
    if proof.get('source_url') != row.get('url'):
        raise ValueError('reviewed_source_changed')
    for url in (proof.get('source_url'), pdf.get('source_url')):
        parsed = urllib.parse.urlparse(url or '')
        host = (parsed.hostname or '').casefold()
        if parsed.scheme not in {'http', 'https'} or not host or host == 'arxiv.org' or host.endswith('.arxiv.org'):
            raise ValueError('formal_publication_source_required')
    path = Path(pdf.get('path') or '')
    if not path.is_file():
        raise ValueError('verified_pdf_file_required')
    data = path.read_bytes()
    if not is_valid_pdf_bytes(data) or hashlib.sha256(data).hexdigest() != pdf.get('sha256'):
        raise ValueError('verified_pdf_changed_or_invalid')


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
    published = item.get("published-print") or item.get("published-online") or item.get("published") or item.get("issued") or {}
    date_parts = (published.get("date-parts") or [[""]])[0]
    return {
        "DOI": normalize_doi(item.get("DOI")),
        "title": title,
        "author": first_author.get("family") or first_author.get("name", ""),
        "authors": [{k: v for k, v in {"firstName": a.get("given", ""), "lastName": a.get("family", ""), "creatorType": "author"}.items() if v} for a in authors],
        "venue": item.get("container-title", [""])[0],
        "year": str(date_parts[0]) if date_parts else "",
        "date": "-".join(str(part) if index == 0 else str(part).zfill(2) for index, part in enumerate(date_parts)),
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


@contextmanager
def connector_write_lock():
    """Serialize this user's local import helpers; never bypass other writers."""
    path = Path(tempfile.gettempdir()) / 'zotero-paper-import-write.lock'
    with path.open('a+b') as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def zotero_connector_save_item(payload: dict[str, Any], base_url: str = "http://localhost:23119", *, reconciliation: dict | None = None) -> tuple[int, bytes]:
    """Final write gate, including callers that bypass the high-level pipeline."""
    def reject(code, reason, **details):
        return code, json.dumps({'reason': reason, **details}, ensure_ascii=False).encode('utf-8')
    rows = payload.get('items')
    if not isinstance(rows, list) or len(rows) != 1:
        return reject(422, 'one_paper_per_write_required')
    row = rows[0]
    if reconciliation is not None:
        reconciliation.clear()
    paper = {'title': row.get('title', ''), 'doi': row.get('DOI'), 'tags': row.get('tags', [])}
    try:
        with connector_write_lock():
            before = read_zotero_items(base_url)
            keys = find_existing_parent_keys(before, paper)
            if keys:
                return reject(409, 'existing_parent_requires_reconciliation', parent_keys=keys)
            if (not row.get('title') or not row.get('creators') or not row.get('date')
                    or not (row.get('publicationTitle') or row.get('proceedingsTitle'))
                    or row.get('itemType') not in {'journalArticle', 'conferencePaper'}):
                return reject(422, 'verified_publication_metadata_required')
            host = (urllib.parse.urlparse(row.get('url', '')).hostname or '').casefold()
            if host == 'arxiv.org' or host.endswith('.arxiv.org'):
                return reject(422, 'formal_publication_source_required')
            try:
                validate_publication_pdf(row, payload.get('_publication_verification'))
            except (ValueError, TypeError, OSError) as exc:
                return reject(422, str(exc))
            # Local evidence includes a local path; it must never enter Connector metadata.
            wire_payload = {key: value for key, value in payload.items() if key != '_publication_verification'}
            status, body = _request_json(f"{base_url}/connector/saveItems", wire_payload)
            if status not in (200, 201):
                return status, body
            after = read_zotero_items(base_url)
            decision = classify_post_write_matches(before, after, paper)
            if reconciliation is not None:
                reconciliation.update(before=before, after=after, decision=decision)
            if decision['status'] != 'unique_parent':
                return reject(409, 'postwrite_reconciliation_required', **decision)
            return status, body
    except OSError as exc:
        # Includes ambiguous transport failure: never automatically resend.
        return reject(409, 'write_unavailable_or_outcome_unknown_reconcile_before_retry', error=str(exc))


def zotero_delete_item(item_key: str, base_url: str = "http://localhost:23119") -> tuple[int, bytes]:
    del base_url
    message = (
        f"Zotero local API DELETE is unsupported for item {item_key}; "
        "manual Zotero UI review is required."
    )
    return 501, message.encode("utf-8")


def zotero_connector_upload_attachment(session_id: str, connector_id: str, pdf_path: str | Path, source_url: str = "", base_url: str = "http://localhost:23119", *, publication_verification: dict | None = None) -> tuple[int, bytes]:
    path = Path(pdf_path)
    try:
        proof = publication_verification
        validate_publication_pdf((proof or {}).get('publication', {}), proof)
        if path.resolve() != Path(proof['pdf']['path']).resolve() or source_url != proof['pdf']['source_url']:
            raise ValueError('upload_does_not_match_verified_pdf')
    except (ValueError, TypeError, OSError) as exc:
        return 422, json.dumps({'reason': str(exc)}).encode('utf-8')
    data = path.read_bytes()
    import hashlib
    if hashlib.sha256(data).hexdigest() != proof['pdf']['sha256']:
        return 422, b'{"reason":"verified_pdf_changed_before_upload"}'
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
    tags = {x.get('tag') for x in paper.get('tags', []) if isinstance(x, dict)}
    if paper.get('number') is not None:
        tags.add(f"obsidian-paper-{paper['number']}")
    tags = {x for x in tags if isinstance(x, str) and re.fullmatch(r'obsidian-paper-\d+', x)}
    matches: list[str] = []
    for item in items:
        data = item.get("data", {})
        if data.get("itemType") in {"attachment", "note", "annotation"} or data.get("parentItem") or data.get('deleted'):
            continue
        key = item.get("key")
        if not key:
            continue
        doi_match = doi and normalize_doi(data.get("DOI")) == doi
        title_match = title_key and _identity_title_key(data.get("title", "")) == title_key
        tag_match = tags.intersection(x.get('tag') for x in data.get('tags', []) if isinstance(x, dict))
        if (doi_match or title_match or tag_match) and key not in matches:
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
    items = list(items)
    matches = find_existing_parent_keys(items, paper)
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError('duplicate_merge_required')
    wanted = matches[0]
    return next((item for item in items if item.get("key") == wanted), None)


def group_duplicate_parents(items: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for item in items:
        data = item.get("data", {})
        if data.get("itemType") in {"attachment", "note", "annotation"} or data.get('parentItem') or data.get('deleted'):
            continue
        doi = normalize_doi(data.get("DOI"))
        key = item.get("key")
        if not key:
            continue
        identities = [doi] if doi else []
        title = _identity_title_key(data.get('title', ''))
        if title:
            identities.append('title:' + title)
        identities.extend('tag:' + x['tag'] for x in data.get('tags', [])
                          if isinstance(x, dict) and re.fullmatch(r'obsidian-paper-\d+', x.get('tag', '')))
        for identity in identities:
            if key not in groups.setdefault(identity, []):
                groups[identity].append(key)
    return {doi: keys for doi, keys in groups.items() if len(keys) > 1}


def existing_identity_conflict(item: dict[str, Any], paper: dict[str, Any]) -> bool:
    data = item.get('data', {})
    left, right = normalize_doi(data.get('DOI')), normalize_doi(paper.get('doi'))
    if left and right and left != right:
        return True
    return bool(_identity_title_key(data.get('title', '')) != _identity_title_key(paper.get('title', '')))

def verified_existing_attachment(paper: dict, items: list[dict]) -> str:
    """Resolve a reviewed formal PDF against current parents and stored files."""
    import hashlib
    keys = find_existing_parent_keys(items, paper)
    if len(keys) != 1:
        raise ValueError('backlink_requires_unique_live_parent')
    if paper.get('parent_key') and paper['parent_key'] != keys[0]:
        raise ValueError('stale_parent_mapping_requires_reconciliation')
    parent = next(item for item in items if item.get('key') == keys[0])
    proof = paper.get('publication_verification')
    validate_publication_pdf(parent.get('data', {}), proof)
    expected_hash = proof['pdf']['sha256']
    matches = []
    for item in items:
        data = item.get('data', {})
        if (data.get('parentItem') != keys[0] or data.get('deleted')
                or data.get('contentType') != 'application/pdf'
                or data.get('linkMode') not in {'imported_file', 'imported_url'}):
            continue
        uri = urllib.parse.urlparse(item.get('links', {}).get('enclosure', {}).get('href', ''))
        if uri.scheme != 'file' or uri.netloc not in {'', 'localhost'}:
            continue
        path = Path(urllib.request.url2pathname(uri.path))
        if path.parent.name != item.get('key') or not path.is_file():
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash:
            matches.append(item['key'])
    preferred = paper.get('attachment_key')
    if preferred:
        if preferred not in matches:
            raise ValueError('stale_or_wrong_version_attachment_mapping')
        return preferred
    if not matches:
        raise ValueError('verified_formal_stored_pdf_required')
    return sorted(matches)[0]


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
        items = read_zotero_items()
        mapping = {}
        for paper in records:
            if paper.get('attachment_key') and paper.get('status') in {'imported_pdf', 'duplicate_existing'}:
                mapping[int(paper['number'])] = verified_existing_attachment(paper, items)
        update_obsidian_file(args.obsidian, mapping, backup=not args.no_backup)
        return 0
    if args.command == "import":
        records = load_json(args.manifest)
        state_dir = Path(args.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        selected = [p for p in records if args.start <= int(p["number"]) <= args.end]
        if len(selected)>10:
            raise ValueError('maximum_10_papers_per_batch')
        for paper in selected:
            items = read_zotero_items()
            existing_keys = find_existing_parent_keys(items, paper)
            if len(existing_keys) > 1:
                paper["duplicate_parent_keys"] = existing_keys
                paper["status"] = "duplicate_merge_required"
                continue
            if existing_keys:
                existing = next(item for item in items if item.get('key') == existing_keys[0])
                if existing_identity_conflict(existing, paper):
                    paper['status'] = 'metadata_conflict'
                    continue
                paper["parent_key"] = existing_keys[0]
                try:
                    paper['attachment_key'] = verified_existing_attachment(paper, items)
                    paper['status'] = 'duplicate_existing'
                except (ValueError, TypeError, OSError) as exc:
                    paper.pop('attachment_key', None)
                    paper['status'] = 'manual_review'
                    paper['reconciliation_reason'] = str(exc)
                continue
            if not args.execute:
                paper["status"] = "dry_run_ready" if paper.get("doi") else "doi_candidate_review"
                continue
            session_id = f"paper-import-{paper['number']}-{uuid.uuid4().hex}"
            connector_id = f"obsidian-paper-{paper['number']}-{uuid.uuid4().hex}"
            reconciliation={}
            status, body = zotero_connector_save_item(build_connector_payload(paper, session_id, connector_id), reconciliation=reconciliation)
            paper["write_status"] = status
            paper["write_response"] = body.decode("utf-8", errors="replace")
            if status not in (200, 201):
                paper["status"] = "manual_review"
                continue
            after_items = reconciliation['after']
            decision = reconciliation['decision']
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
                status, body = zotero_connector_upload_attachment(session_id, connector_id, pdf_path, paper.get("pdf_url", ""), publication_verification=paper.get('publication_verification'))
                paper["attachment_write_status"] = status
                time.sleep(0.8)
                final_items = read_zotero_items()
                try:
                    if status not in (200,201): raise ValueError('attachment_write_not_confirmed')
                    paper['attachment_key']=verified_existing_attachment(paper,final_items)
                    paper['status']='imported_pdf'
                except (ValueError,TypeError,OSError) as exc:
                    paper.pop('attachment_key',None)
                    paper['status']='manual_review'
                    paper['reconciliation_reason']=str(exc)
            else:
                paper["status"] = "imported_metadata"
        save_json(state_dir / "manifest-after-import.json", records)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
