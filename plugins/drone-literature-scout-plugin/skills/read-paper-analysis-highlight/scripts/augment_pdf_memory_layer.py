from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence
from urllib.parse import quote

import fitz


BRIDGE_ORIGIN = "https://obsidian-link.invalid"
DEFAULT_LINK_LABEL = "返回 Obsidian的对应精读位置"


class MemoryLayerError(ValueError):
    """Raised when a PDF memory/navigation layer cannot be added safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _without_layout_whitespace(value: str) -> str:
    return re.sub(r"\s+", "", value)


def build_obsidian_uri(vault: str, relative_note: str, block_id: str) -> str:
    vault = vault.strip()
    block_id = block_id.strip().removeprefix("^")
    if not vault:
        raise MemoryLayerError("Obsidian vault name is required")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", block_id):
        raise MemoryLayerError("block_id must contain only letters, digits, _ or -")

    normalized = relative_note.replace("\\", "/").strip("/")
    note_path = PurePosixPath(normalized)
    if note_path.suffix.lower() == ".md":
        note_path = note_path.with_suffix("")
    if not note_path.parts or ".." in note_path.parts:
        raise MemoryLayerError("relative_note must stay inside the vault")

    target = f"{note_path.as_posix()}#^{block_id}"
    return (
        "obsidian://open?vault="
        + quote(vault, safe="")
        + "&file="
        + quote(target, safe="")
    )


def build_zotero_bridge_url(obsidian_uri: str) -> str:
    if not obsidian_uri.startswith("obsidian://open?"):
        raise MemoryLayerError("obsidian_uri must use obsidian://open")
    return (
        f"{BRIDGE_ORIGIN}/open?uri="
        + quote(obsidian_uri, safe="")
    )


def _rect(value: Sequence[float], name: str, page_rect: fitz.Rect) -> fitz.Rect:
    if len(value) != 4:
        raise MemoryLayerError(f"{name} must contain four coordinates")
    numbers = [float(number) for number in value]
    if not all(math.isfinite(number) for number in numbers):
        raise MemoryLayerError(f"{name} contains a non-finite coordinate")
    rect = fitz.Rect(numbers)
    if rect.is_empty or rect.is_infinite or rect.width <= 0 or rect.height <= 0:
        raise MemoryLayerError(f"{name} must have positive area")
    tolerance = 0.01
    if (
        rect.x0 < page_rect.x0 - tolerance
        or rect.y0 < page_rect.y0 - tolerance
        or rect.x1 > page_rect.x1 + tolerance
        or rect.y1 > page_rect.y1 + tolerance
    ):
        raise MemoryLayerError(f"{name} lies outside page 1")
    return rect


def _overlap_area(left: fitz.Rect, right: fitz.Rect) -> float:
    intersection = left & right
    return 0.0 if intersection.is_empty else intersection.get_area()


def _embedded_markup_count(document: fitz.Document) -> int:
    return sum(
        1
        for page in document
        for _annotation in (page.annots() or ())
    )


def add_memory_layer(
    *,
    source: Path,
    output: Path,
    memory_sentence: str,
    obsidian_uri: str,
    memory_rect: Sequence[float],
    link_rect: Sequence[float],
    protected_rects: Iterable[Sequence[float]] = (),
    font_path: Path | None = None,
    memory_font_size: float = 8.5,
    link_font_size: float = 7.5,
    link_label: str = DEFAULT_LINK_LABEL,
) -> dict[str, object]:
    source = Path(source).resolve()
    output = Path(output).resolve()
    if not source.is_file():
        raise MemoryLayerError(f"source PDF does not exist: {source}")
    if source == output:
        raise MemoryLayerError("source and output must be different files")
    if output.exists():
        raise MemoryLayerError(f"output already exists: {output}")
    if not memory_sentence.strip():
        raise MemoryLayerError("memory_sentence is required")
    if not obsidian_uri.startswith("obsidian://open?"):
        raise MemoryLayerError("obsidian_uri must use obsidian://open")
    bridge_url = build_zotero_bridge_url(obsidian_uri)
    if not link_label.strip():
        raise MemoryLayerError("link_label is required")
    if memory_font_size <= 0 or link_font_size <= 0:
        raise MemoryLayerError("font sizes must be positive")

    font_path = Path(font_path).resolve() if font_path is not None else None
    if font_path is not None and not font_path.is_file():
        raise MemoryLayerError(f"font file does not exist: {font_path}")

    document = fitz.open(source)
    try:
        if document.page_count < 1:
            raise MemoryLayerError("PDF has no pages")
        if _embedded_markup_count(document) != 0:
            raise MemoryLayerError(
                "source is not annotation-free; start from the verified clean backup"
            )

        page = document[0]
        page_rect = page.rect
        memory_box = _rect(memory_rect, "memory_rect", page_rect)
        link_box = _rect(link_rect, "link_rect", page_rect)
        protected_boxes = [
            _rect(value, f"protected_rect[{index}]", page_rect)
            for index, value in enumerate(protected_rects)
        ]
        for protected in protected_boxes:
            if _overlap_area(memory_box, protected) > 0:
                raise MemoryLayerError("memory_rect overlaps protected content")
            if _overlap_area(link_box, protected) > 0:
                raise MemoryLayerError("link_rect overlaps protected content")
        if _overlap_area(memory_box, link_box) > 0:
            raise MemoryLayerError("memory_rect overlaps link_rect")

        font_name = "helv"
        if font_path is not None:
            font_name = "paper-memory-font"
            page.insert_font(fontname=font_name, fontfile=str(font_path))

        memory_result = page.insert_textbox(
            memory_box,
            memory_sentence.strip(),
            fontname=font_name,
            fontsize=float(memory_font_size),
            color=(0.06, 0.27, 0.31),
            align=fitz.TEXT_ALIGN_CENTER,
            overlay=True,
        )
        if memory_result < 0:
            raise MemoryLayerError(
                f"memory sentence does not fit memory_rect (deficit={memory_result:.2f})"
            )

        link_result = page.insert_textbox(
            link_box,
            link_label.strip(),
            fontname=font_name,
            fontsize=float(link_font_size),
            color=(0.08, 0.30, 0.70),
            align=fitz.TEXT_ALIGN_LEFT,
            overlay=True,
        )
        if link_result < 0:
            raise MemoryLayerError(
                f"Obsidian link label does not fit link_rect (deficit={link_result:.2f})"
            )
        page.draw_line(
            fitz.Point(link_box.x0, link_box.y1 - 1.0),
            fitz.Point(link_box.x1, link_box.y1 - 1.0),
            color=(0.08, 0.30, 0.70),
            width=0.45,
            overlay=True,
        )
        page.insert_link(
            {
                "kind": fitz.LINK_URI,
                "from": link_box,
                "uri": bridge_url,
            }
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        document.save(output, garbage=4, deflate=True)
    except Exception:
        document.close()
        if output.exists():
            output.unlink()
        raise
    else:
        document.close()

    checked = fitz.open(output)
    try:
        extracted = checked[0].get_text()
        if _without_layout_whitespace(
            memory_sentence.strip()
        ) not in _without_layout_whitespace(extracted):
            raise MemoryLayerError("saved PDF does not contain the exact memory sentence")
        saved_links = checked[0].get_links()
        matching_links = [
            link
            for link in saved_links
            if link.get("uri") == bridge_url
        ]
        if len(matching_links) != 1:
            raise MemoryLayerError("saved PDF must contain exactly one Zotero bridge link")
        direct_obsidian_links = [
            link
            for link in saved_links
            if link.get("uri") == obsidian_uri
        ]
        if direct_obsidian_links:
            raise MemoryLayerError("saved PDF must not embed a direct obsidian:// link")
        if _embedded_markup_count(checked) != 0:
            raise MemoryLayerError("memory layer unexpectedly created markup annotations")
        page_count = checked.page_count
    except Exception:
        checked.close()
        output.unlink(missing_ok=True)
        raise
    else:
        checked.close()

    return {
        "source": str(source),
        "output": str(output),
        "source_sha256": _sha256(source),
        "output_sha256": _sha256(output),
        "page_count": page_count,
        "memory_sentence": memory_sentence.strip(),
        "memory_rect": list(map(float, memory_rect)),
        "memory_font_size": float(memory_font_size),
        "obsidian_uri": obsidian_uri,
        "bridge_url": bridge_url,
        "bridge_url_count": 1,
        "direct_obsidian_uri_count": 0,
        "link_rect": list(map(float, link_rect)),
        "link_label": link_label.strip(),
        "link_font_size": float(link_font_size),
        "protected_rects": [list(map(float, rect)) for rect in protected_rects],
        "embedded_markup_count": 0,
        "document_link_count_added": 1,
    }


def _parse_rect(value: str) -> tuple[float, float, float, float]:
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("rect must be x0,y0,x1,y1")
    try:
        return tuple(float(part) for part in parts)  # type: ignore[return-value]
    except ValueError as error:
        raise argparse.ArgumentTypeError("rect coordinates must be numbers") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--memory-sentence", required=True)
    parser.add_argument("--memory-rect", required=True, type=_parse_rect)
    parser.add_argument("--link-rect", required=True, type=_parse_rect)
    parser.add_argument("--protected-rect", action="append", type=_parse_rect, default=[])
    parser.add_argument("--font-path", type=Path)
    parser.add_argument("--memory-font-size", type=float, default=8.5)
    parser.add_argument("--link-font-size", type=float, default=7.5)
    parser.add_argument("--link-label", default=DEFAULT_LINK_LABEL)
    parser.add_argument("--obsidian-uri")
    parser.add_argument("--vault")
    parser.add_argument("--relative-note")
    parser.add_argument("--block-id")
    args = parser.parse_args()

    obsidian_uri = args.obsidian_uri
    if not obsidian_uri:
        if not all((args.vault, args.relative_note, args.block_id)):
            parser.error(
                "provide --obsidian-uri or all of --vault, --relative-note and --block-id"
            )
        obsidian_uri = build_obsidian_uri(
            args.vault,
            args.relative_note,
            args.block_id,
        )

    report = add_memory_layer(
        source=args.source,
        output=args.output,
        memory_sentence=args.memory_sentence,
        obsidian_uri=obsidian_uri,
        memory_rect=args.memory_rect,
        link_rect=args.link_rect,
        protected_rects=args.protected_rect,
        font_path=args.font_path,
        memory_font_size=args.memory_font_size,
        link_font_size=args.link_font_size,
        link_label=args.link_label,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
