from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


SCREENSHOT_RE = re.compile(r"^屏幕截图 (\d{4}-\d{2}-\d{2}) (\d{6})\.png$")
META_RE = re.compile(r"<!--\s*rss2026-meta\s+(\{.*?\})\s*-->", re.DOTALL)
HEADING_RE = re.compile(r"^##\s+(RSS2026_\d{3})\s*$", re.MULTILINE)
ALLOWED_TRACKS = {"method/schematic", "data/table", "mixed"}


def screenshot_key(path: Path) -> tuple[datetime, str]:
    match = SCREENSHOT_RE.fullmatch(path.name)
    if not match:
        raise ValueError(f"unsupported screenshot filename: {path.name}")
    stamp = datetime.strptime(" ".join(match.groups()), "%Y-%m-%d %H%M%S")
    return stamp, path.name


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_index(
    source_dir: Path,
    start_filename: str,
    expected_count: int | None = None,
) -> dict[str, Any]:
    source_dir = Path(source_dir)
    files = sorted(
        (
            path
            for path in source_dir.glob("*.png")
            if SCREENSHOT_RE.fullmatch(path.name)
        ),
        key=screenshot_key,
    )
    names = [path.name for path in files]
    if start_filename not in names:
        raise ValueError(f"start file missing: {start_filename}")
    selected = files[names.index(start_filename) :]
    if expected_count is not None and len(selected) != expected_count:
        raise ValueError(f"expected {expected_count} images, got {len(selected)}")

    images: list[dict[str, Any]] = []
    for offset, path in enumerate(selected, start=1):
        batch_id = (offset - 1) // 5 + 1
        logical_id = f"RSS2026_{offset:03d}"
        images.append(
            {
                "logical_id": logical_id,
                "original_filename": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "batch_id": batch_id,
                "batch_position": (offset - 1) % 5 + 1,
                "visible_figure_label": "unknown",
                "domain_tags": [],
                "figure_track": "unknown",
                "analysis_card": (
                    f"rss2026-batches/batch-{batch_id:03d}.md#{logical_id}"
                ),
                "analysis_status": "pending",
                "last_verified": None,
            }
        )

    return {
        "schema_version": 1,
        "corpus": {
            "source_root": str(source_dir.resolve()),
            "start_filename": start_filename,
            "image_count": len(images),
            "batch_size": 5,
            "batch_count": (len(images) + 4) // 5,
        },
        "images": images,
    }


def read_index(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_index(path: Path, index: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(index, ensure_ascii=False, indent=2) + "\n"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _validate_metadata(metadata: Any, logical_id: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(metadata, dict):
        return [f"{logical_id}: metadata must be an object"]
    label = metadata.get("visible_figure_label")
    tags = metadata.get("domain_tags")
    track = metadata.get("figure_track")
    if not isinstance(label, str) or not label.strip():
        errors.append(f"{logical_id}: visible_figure_label must be a string")
    if not isinstance(tags, list) or not all(
        isinstance(tag, str) and tag.strip() for tag in tags
    ):
        errors.append(f"{logical_id}: domain_tags must be a string array")
    if track not in ALLOWED_TRACKS:
        errors.append(f"{logical_id}: invalid figure_track {track!r}")
    return errors


def _card_sections(card_text: str) -> dict[str, str]:
    matches = list(HEADING_RE.finditer(card_text))
    sections: dict[str, str] = {}
    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(card_text)
        sections[match.group(1)] = card_text[match.end() : end]
    return sections


def read_card_metadata(card_path: Path, logical_ids: list[str]) -> dict[str, dict]:
    text = Path(card_path).read_text(encoding="utf-8")
    sections = _card_sections(text)
    parsed: dict[str, dict] = {}
    errors: list[str] = []
    for logical_id in logical_ids:
        section = sections.get(logical_id)
        if section is None:
            errors.append(f"{logical_id}: heading missing")
            continue
        match = META_RE.search(section)
        if match is None:
            errors.append(f"{logical_id}: rss2026-meta missing")
            continue
        try:
            metadata = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            errors.append(f"{logical_id}: invalid metadata JSON: {exc.msg}")
            continue
        metadata_errors = _validate_metadata(metadata, logical_id)
        errors.extend(metadata_errors)
        if not metadata_errors:
            parsed[logical_id] = metadata
    if errors:
        raise ValueError("; ".join(errors))
    return parsed


def freeze_batch(
    index_path: Path,
    batch_id: int,
    card_path: Path,
    verified_date: str,
) -> None:
    index = read_index(index_path)
    batch = [item for item in index.get("images", []) if item.get("batch_id") == batch_id]
    if not batch:
        raise ValueError(f"batch not found: {batch_id}")
    logical_ids = [item["logical_id"] for item in batch]
    metadata = read_card_metadata(card_path, logical_ids)

    updated = deepcopy(index)
    for item in updated["images"]:
        logical_id = item["logical_id"]
        if logical_id not in metadata:
            continue
        entry = metadata[logical_id]
        item["visible_figure_label"] = entry["visible_figure_label"]
        item["domain_tags"] = entry["domain_tags"]
        item["figure_track"] = entry["figure_track"]
        item["analysis_status"] = "frozen"
        item["last_verified"] = verified_date
    write_index(index_path, updated)


def validate_index(
    index: dict[str, Any],
    source_dir: Path,
    references_root: Path,
) -> list[str]:
    errors: list[str] = []
    images = index.get("images")
    corpus = index.get("corpus")
    if not isinstance(images, list) or not isinstance(corpus, dict):
        return ["index must contain corpus object and images array"]

    if corpus.get("image_count") != len(images):
        errors.append("corpus image_count does not match images")
    expected_batches = (len(images) + 4) // 5
    if corpus.get("batch_count") != expected_batches:
        errors.append("corpus batch_count does not match images")

    seen_names: set[str] = set()
    for offset, item in enumerate(images, start=1):
        logical_id = f"RSS2026_{offset:03d}"
        expected_batch = (offset - 1) // 5 + 1
        expected_position = (offset - 1) % 5 + 1
        if item.get("logical_id") != logical_id:
            errors.append(f"entry {offset}: logical_id is not continuous")
        if item.get("batch_id") != expected_batch:
            errors.append(f"{logical_id}: wrong batch_id")
        if item.get("batch_position") != expected_position:
            errors.append(f"{logical_id}: wrong batch_position")

        filename = item.get("original_filename")
        if not isinstance(filename, str) or filename in seen_names:
            errors.append(f"{logical_id}: original_filename missing or duplicate")
            continue
        seen_names.add(filename)
        path = Path(source_dir) / filename
        if not path.is_file():
            errors.append(f"{logical_id}: source file missing: {filename}")
            continue
        if path.stat().st_size != item.get("size_bytes"):
            errors.append(f"{logical_id}: size_bytes mismatch")
        if sha256_file(path) != item.get("sha256"):
            errors.append(f"{logical_id}: sha256 mismatch")

        if item.get("analysis_status") == "frozen":
            card_ref = item.get("analysis_card", "")
            relative, separator, anchor = card_ref.partition("#")
            card_path = Path(references_root) / relative
            if not separator or anchor != logical_id or not card_path.is_file():
                errors.append(f"{logical_id}: frozen analysis_card missing")
                continue
            try:
                metadata = read_card_metadata(card_path, [logical_id])[logical_id]
            except (OSError, ValueError) as exc:
                errors.append(f"{logical_id}: invalid frozen card: {exc}")
                continue
            for key in ("visible_figure_label", "domain_tags", "figure_track"):
                if item.get(key) != metadata.get(key):
                    errors.append(f"{logical_id}: frozen {key} mismatch")
    return errors


def _build_command(args: argparse.Namespace) -> int:
    index = build_index(
        Path(args.source_dir),
        args.start_filename,
        expected_count=args.expected_count,
    )
    write_index(Path(args.output), index)
    corpus = index["corpus"]
    print(
        f"WROTE {corpus['image_count']} images, "
        f"{corpus['batch_count']} batches -> {args.output}"
    )
    return 0


def _check_command(args: argparse.Namespace) -> int:
    index_path = Path(args.index)
    index = read_index(index_path)
    references_root = Path(args.references_root) if args.references_root else index_path.parent
    errors = validate_index(index, Path(args.source_dir), references_root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    corpus = index["corpus"]
    print(f"{corpus['image_count']} images, {corpus['batch_count']} batches, OK")
    return 0


def _freeze_command(args: argparse.Namespace) -> int:
    freeze_batch(Path(args.index), args.batch_id, Path(args.card), args.date)
    print(f"FROZEN batch {args.batch_id:03d}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and verify the read-only RSS 2026 figure corpus index")
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build")
    build.add_argument("--source-dir", required=True)
    build.add_argument("--start-filename", required=True)
    build.add_argument("--expected-count", type=int)
    build.add_argument("--output", required=True)
    build.set_defaults(handler=_build_command)

    check = commands.add_parser("check")
    check.add_argument("--source-dir", required=True)
    check.add_argument("--index", required=True)
    check.add_argument("--references-root")
    check.set_defaults(handler=_check_command)

    freeze = commands.add_parser("freeze-batch")
    freeze.add_argument("--index", required=True)
    freeze.add_argument("--batch-id", type=int, required=True)
    freeze.add_argument("--card", required=True)
    freeze.add_argument("--date", required=True)
    freeze.set_defaults(handler=_freeze_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
