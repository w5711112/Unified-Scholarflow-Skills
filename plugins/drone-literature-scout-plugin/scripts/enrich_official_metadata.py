"""Enrich legacy corpus rows from their existing official paper records.

The script never treats a search engine or third-party index as final evidence.
It follows only the paper URL already stored in the corpus, extracts publisher
metadata, and records failures for later manual verification.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import time
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from corpus_tools import CSV_FIELDS, extract_identifier, is_official_record_url, parse_csv_rows


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, list[str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "meta":
            return
        values = {str(key).casefold(): (value or "").strip() for key, value in attrs}
        key = (values.get("name") or values.get("property") or values.get("itemprop") or "").casefold()
        value = values.get("content") or ""
        if key and value:
            self.meta.setdefault(key, []).append(value)


def normalize_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def extract_metadata(page: str) -> tuple[str, str, str]:
    """Return publisher abstract, PDF link, and DOI from official HTML metadata."""

    parser = MetadataParser()
    parser.feed(page)
    abstract = ""
    for key in ("citation_abstract", "dc.description", "description"):
        for value in parser.meta.get(key, []):
            candidate = normalize_text(value)
            if len(candidate) >= 280:
                abstract = candidate
                break
        if abstract:
            break
    if not abstract:
        body_match = re.search(
            r"<(?:div|section)[^>]+(?:id|class)=[\"'][^\"']*abstract[^\"']*[\"'][^>]*>(.*?)</(?:div|section)>",
            page,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if body_match:
            candidate = normalize_text(body_match.group(1))
            if len(candidate) >= 280:
                abstract = candidate
    pdf = ""
    for key in ("citation_pdf_url", "pdf_url"):
        if parser.meta.get(key):
            pdf = parser.meta[key][0].strip()
            break
    doi = ""
    for key in ("citation_doi", "dc.identifier", "doi"):
        if parser.meta.get(key):
            identifier = extract_identifier(parser.meta[key][0])
            if identifier and identifier.startswith("doi:"):
                doi = identifier.removeprefix("doi:")
                break
    return abstract, pdf, doi


def fetch(url: str, timeout: int) -> tuple[str, str]:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; DroneLiteratureScout/0.2)"})
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace"), response.geturl()


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in CSV_FIELDS} for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.4)
    parser.add_argument("--retry-failed", action="store_true", help="retry rows that were previously marked needs_access")
    args = parser.parse_args()

    rows = parse_csv_rows(args.csv)
    report: list[dict[str, str]] = []
    processed = 0
    for row in rows:
        complete_record = (row.get("abstract_source_url") or "").strip() and len((row.get("abstract") or "").strip()) >= 280
        if processed >= args.limit or complete_record or (not args.retry_failed and (row.get("verification_date") or "").strip()):
            continue
        processed += 1
        url = (row.get("url") or "").strip()
        try:
            page, final_url = fetch(url, args.timeout)
            abstract, pdf, doi = extract_metadata(page)
            if not is_official_record_url(final_url):
                raise ValueError("redirect did not resolve to an official record")
            if not abstract:
                raise ValueError("official page did not expose a complete abstract metadata field")
            if not pdf and "openaccess.thecvf.com/content/" in final_url and "/html/" in final_url:
                pdf = final_url.replace("/html/", "/papers/").replace("_paper.html", "_paper.pdf")
            row["abstract"] = abstract
            row["abstract_source_url"] = final_url
            row["doi"] = doi or (extract_identifier(url) or "").removeprefix("doi:")
            row["fulltext_status"] = "needs_access" if pdf else "abstract_only"
            row["fulltext_url"] = pdf
            row["verification_date"] = date.today().isoformat()
            report.append({"title": row["title"], "status": "abstract_enriched", "url": final_url})
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
            row["verification_date"] = date.today().isoformat()
            row["fulltext_status"] = "needs_access"
            report.append({"title": row.get("title", ""), "status": "needs_manual_verification", "reason": str(error)})
        time.sleep(args.sleep_seconds)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_csv(args.output, rows)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"processed": processed, "enriched": sum(item["status"] == "abstract_enriched" for item in report), "needs_manual": sum(item["status"] != "abstract_enriched" for item in report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
