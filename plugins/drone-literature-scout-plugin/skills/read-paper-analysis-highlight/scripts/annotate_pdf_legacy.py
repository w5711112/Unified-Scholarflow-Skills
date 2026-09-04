from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

import fitz

from semantic_selection import validate_semantic_annotation


COLOR_MAP = {
    "yellow": (1.0, 0.85, 0.0),
    "blue": (0.2, 0.5, 1.0),
    "green": (0.2, 0.75, 0.2),
    "orange": (1.0, 0.55, 0.1),
    "red": (0.95, 0.2, 0.2),
    "purple": (0.6, 0.3, 0.8),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pdf_page_count(path: Path) -> int:
    with fitz.open(path) as doc:
        if not doc.is_pdf:
            raise ValueError(f"not a PDF: {path}")
        if not doc.page_count:
            raise ValueError(f"empty PDF: {path}")
        return doc.page_count


def _token(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text)).casefold()
    value = value.replace("–", "-").replace("—", "-").replace("−", "-")
    return "".join(
        character for character in value
        if character.isalnum() or character in {"%", "μ", "µ", "×", "-"}
    )


def _quote_tokens(text: str) -> list[str]:
    return [token for raw in str(text).split() if (token := _token(raw))]


def _page_words(page: fitz.Page) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for raw in page.get_text("words", sort=False):
        x0, y0, x1, y1, text, block, line, word = raw[:8]
        token = _token(text)
        if token:
            words.append({
                "rect": fitz.Rect(x0, y0, x1, y1),
                "text": str(text),
                "token": token,
                "block": int(block),
                "line": int(line),
                "word": int(word),
            })
    return words


def _find_occurrences(words: list[dict[str, Any]], quote: str) -> list[tuple[int, int]]:
    wanted = _quote_tokens(quote)
    if not wanted:
        return []
    tokens = [word["token"] for word in words]
    width = len(wanted)
    return [
        (index, index + width)
        for index in range(0, len(tokens) - width + 1)
        if tokens[index:index + width] == wanted
    ]


def _context_matches(
    words: list[dict[str, Any]], start: int, stop: int, before: str, after: str
) -> bool:
    before_tokens = _quote_tokens(before)
    after_tokens = _quote_tokens(after)
    if before_tokens:
        left = [word["token"] for word in words[max(0, start-len(before_tokens)):start]]
        if left != before_tokens:
            return False
    if after_tokens:
        right = [word["token"] for word in words[stop:stop+len(after_tokens)]]
        if right != after_tokens:
            return False
    return True


def _merge_word_rects(selected: list[dict[str, Any]]) -> list[fitz.Quad]:
    merged: list[tuple[fitz.Rect, int, int]] = []
    for word in selected:
        rect = fitz.Rect(word["rect"])
        if (
            merged
            and merged[-1][1] == word["block"]
            and merged[-1][2] == word["line"]
            and rect.x0 - merged[-1][0].x1 < 8
        ):
            merged[-1] = (merged[-1][0] | rect, word["block"], word["line"])
        else:
            merged.append((rect, word["block"], word["line"]))
    return [fitz.Quad(rect.tl, rect.tr, rect.bl, rect.br) for rect, _, _ in merged]


def _quad_values(quad: fitz.Quad) -> list[float]:
    return [
        float(quad.ul.x), float(quad.ul.y),
        float(quad.ur.x), float(quad.ur.y),
        float(quad.ll.x), float(quad.ll.y),
        float(quad.lr.x), float(quad.lr.y),
    ]


def _resolve_highlight(page: fitz.Page, item: dict[str, Any]) -> dict[str, Any]:
    quote = str(item.get("quote", "")).strip()
    if not quote:
        raise ValueError("text highlight requires quote; raw rect is forbidden")
    words = _page_words(page)
    candidates = _find_occurrences(words, quote)
    context_before = str(item.get("context_before", "")).strip()
    context_after = str(item.get("context_after", "")).strip()
    if context_before or context_after:
        candidates = [
            candidate for candidate in candidates
            if _context_matches(words, candidate[0], candidate[1], context_before, context_after)
        ]
    if not candidates:
        raise ValueError(f"quote not found on page {item['page']}: {quote}")
    occurrence = item.get("occurrence")
    if occurrence is None:
        if len(candidates) != 1:
            raise ValueError(
                f"ambiguous quote on page {item['page']}; "
                f"{len(candidates)} matches require occurrence or context"
            )
        selected_index = 0
    else:
        selected_index = int(occurrence) - 1
        if not 0 <= selected_index < len(candidates):
            raise ValueError(
                f"occurrence {occurrence} out of range for {len(candidates)} matches"
            )
    start, stop = candidates[selected_index]
    selected_words = words[start:stop]
    actual_text = " ".join(word["text"] for word in selected_words)
    if _quote_tokens(actual_text) != _quote_tokens(quote):
        raise ValueError("actual highlighted text does not match quote")
    quads = _merge_word_rects(selected_words)
    if not quads:
        raise ValueError("quote produced no highlight quads")
    return {
        **item,
        "actual_text": actual_text,
        "match_count": len(candidates),
        "quads": [_quad_values(quad) for quad in quads],
        "_fitz_quads": quads,
    }


def _resolve_area(page: fitz.Page, item: dict[str, Any]) -> dict[str, Any]:
    values = [float(value) for value in item["rect"]]
    if len(values) != 4 or values[2] <= values[0] or values[3] <= values[1]:
        raise ValueError(f"invalid annotation rectangle: {values}")
    rect = fitz.Rect(values)
    if not page.rect.contains(rect):
        raise ValueError(f"annotation rectangle outside page: {values}")
    return {**item, "rect": values, "_fitz_rect": rect}


def _normalise_annotation(doc: fitz.Document, item: dict[str, Any]) -> dict[str, Any]:
    validated = validate_semantic_annotation(item)
    page_number = int(validated["page"])
    if not 1 <= page_number <= doc.page_count:
        raise ValueError(f"annotation page out of bounds: {page_number}")
    color = validated.get("color", "yellow")
    if color not in COLOR_MAP:
        raise ValueError(f"unknown annotation color: {color}")
    validated = {**validated, "page": page_number, "color": color}
    page = doc[page_number - 1]
    if validated["annotation_type"] == "highlight":
        return _resolve_highlight(page, validated)
    return _resolve_area(page, validated)


def _public_annotation(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if not key.startswith("_fitz_")}


def annotate_pdf(
    input_pdf: str | Path,
    output_pdf: str | Path,
    backup_pdf: str | Path,
    manifest_path: str | Path,
    annotations: list[dict[str, Any]],
    *,
    overwrite: bool = False,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    source = Path(input_pdf).resolve()
    target = Path(output_pdf).resolve()
    backup = Path(backup_pdf).resolve()
    manifest = Path(manifest_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source == target and not overwrite:
        raise ValueError("overwriting the input PDF requires overwrite=True")
    if expected_sha256 and sha256(source).lower() != expected_sha256.lower():
        raise ValueError("input PDF hash does not match expected_sha256")

    with fitz.open(source) as source_doc:
        if not source_doc.is_pdf or not source_doc.page_count:
            raise ValueError(f"not a readable PDF: {source}")
        normalised = [_normalise_annotation(source_doc, item) for item in annotations]
        page_count = source_doc.page_count

    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        if sha256(backup) != sha256(source):
            raise ValueError(f"existing backup has a different hash: {backup}")
    else:
        shutil.copy2(source, backup)
    original_hash = sha256(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".codex-annotated-", suffix=".pdf", dir=target.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with fitz.open(source) as doc:
            for item in normalised:
                page = doc[item["page"] - 1]
                if item["annotation_type"] == "highlight":
                    annot = page.add_highlight_annot(item["_fitz_quads"])
                else:
                    annot = page.add_rect_annot(item["_fitz_rect"])
                    annot.set_border(width=1.0)
                    annot.set_opacity(0.85)
                annot.set_colors(stroke=COLOR_MAP[item["color"]])
                annot.set_info({
                    "title": "Codex paper analysis",
                    "subject": item.get("kind", "evidence"),
                    "content": item.get("annotation_comment") or item.get("claim", ""),
                })
                annot.update()
            doc.save(temporary, garbage=4, deflate=True)
        annotated_hash = sha256(temporary)
        _pdf_page_count(temporary)
        if target.exists() and target != source and not overwrite:
            raise ValueError(f"output exists; pass overwrite=True to replace it: {target}")
        os.replace(temporary, target)
        public_annotations = [_public_annotation(item) for item in normalised]
        payload = {
            "source_pdf": str(source),
            "annotated_pdf": str(target),
            "backup_pdf": str(backup),
            "original_sha256": original_hash,
            "annotated_sha256": annotated_hash,
            "page_count": page_count,
            "annotation_count": len(public_annotations),
            "storage_mode": "external-staging",
            "annotations": public_annotations,
        }
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    raw = json.loads(Path(args.annotations).read_text(encoding="utf-8"))
    annotations = raw["annotations"] if isinstance(raw, dict) else raw
    result = annotate_pdf(
        args.input, args.output, args.backup, args.manifest, annotations,
        overwrite=args.overwrite, expected_sha256=args.expected_sha256,
    )
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())