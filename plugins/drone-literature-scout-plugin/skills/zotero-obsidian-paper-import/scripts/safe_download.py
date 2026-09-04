from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

from pypdf import PdfReader

from paper_import import is_valid_pdf_bytes, load_json


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{3,}", value.lower()) if token not in {"the", "for", "and", "with", "from", "using"}}


def pdf_title_matches(target_title: str, extracted_title: str) -> bool:
    target = _tokens(target_title)
    actual = _tokens(extracted_title)
    if not target or not actual:
        return False
    overlap = len(target & actual) / len(target)
    ratio = SequenceMatcher(None, "".join(sorted(target)), "".join(sorted(actual))).ratio()
    return overlap >= 0.55 or ratio >= 0.72


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages[:2])


def candidate_urls(paper: dict) -> list[str]:
    urls = []
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
    if paper.get("url", "").lower().endswith(".pdf"):
        urls.append(paper["url"])
    return list(dict.fromkeys(urls))


def download_verified(paper: dict, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"{int(paper['number']):03d}.pdf"
    paper = dict(paper)
    paper["pdf_candidates"] = candidate_urls(paper)
    for url in paper["pdf_candidates"]:
        part = target.with_suffix(".part")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "zotero-obsidian-paper-import/1.0", "Accept": "application/pdf"})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
            if not is_valid_pdf_bytes(data):
                raise ValueError("response is not a valid PDF")
            part.write_bytes(data)
            extracted = extract_pdf_text(part)
            if not pdf_title_matches(paper["title"], extracted):
                raise ValueError("PDF title does not match the Obsidian paper title")
            part.replace(target)
            paper["pdf_path"] = str(target.resolve())
            paper["pdf_url"] = url
            paper["pdf_identity"] = "verified"
            paper["pdf_status"] = "downloaded"
            return paper
        except Exception as exc:
            paper.setdefault("pdf_rejections", []).append({"url": url, "reason": str(exc)})
            if part.exists():
                part.unlink()
        time.sleep(0.4)
    paper["pdf_status"] = "download_failed"
    return paper


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--only-status", default="ready")
    args = parser.parse_args()
    records = load_json(args.input)
    output = [download_verified(paper, Path(args.output_dir)) if paper.get("status") == args.only_status else paper for paper in records]
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
