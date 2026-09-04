from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote


DEFAULT_MANAGED_DIRS = ("截图存放位置", "AI绘图存放位置")
MEDIA_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}
EXCLUDED_PARTS = {
    ".git",
    ".obsidian",
    ".superpowers",
    ".trash",
    "__pycache__",
    "node_modules",
    "test-temp",
}
WIKI_LINK_RE = re.compile(r"!?\[\[([^\]\n]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
HTML_MEDIA_RE = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
FENCE_START_RE = re.compile(
    r"^[ ]{0,3}(?:(?:[-+*]|\d+[.)])[ \t]+)?(`{3,}|~{3,})(.*)$"
)
INLINE_CODE_RE = re.compile(r"(`+)(?:(?!\1).)*\1")


def find_vault_root(start: Path) -> Path:
    resolved = start.expanduser().resolve()
    current = resolved.parent if resolved.is_file() else resolved
    for candidate in (current, *current.parents):
        if (candidate / ".obsidian").is_dir():
            return candidate
    raise ValueError(f"no .obsidian directory found above: {resolved}")


def _is_excluded(path: Path, vault: Path) -> bool:
    relative = path.relative_to(vault)
    return any(
        part in EXCLUDED_PARTS
        or part.startswith(".media-test-")
        or part.startswith(".link-test-")
        for part in relative.parts
    )


def _iter_source_files(vault: Path, suffix: str):
    for path in vault.rglob(f"*{suffix}"):
        if path.is_file() and not _is_excluded(path, vault):
            yield path


def _iter_media_files(vault: Path):
    for path in vault.rglob("*"):
        if (
            path.is_file()
            and path.suffix.casefold() in MEDIA_EXTENSIONS
            and not _is_excluded(path, vault)
        ):
            yield path


def _is_fence_close(line: str, marker: str, minimum_length: int) -> bool:
    leading_spaces = len(line) - len(line.lstrip(" "))
    if leading_spaces > 3:
        return False
    remainder = line[leading_spaces:]
    run_length = len(remainder) - len(remainder.lstrip(marker))
    return run_length >= minimum_length and not remainder[run_length:].strip()


def _strip_code(text: str) -> tuple[str, list[dict]]:
    """Strip Markdown code while surfacing an uncertain fence parse.

    A whole-document regular expression can pair the wrong opening and closing
    fences and hide unrelated prose. This line-state parser only closes a fence
    with the same marker. An unclosed fence becomes a warning so deletion can
    fail closed.
    """

    cleaned: list[str] = []
    marker: str | None = None
    minimum_length = 0
    opening_line = 0

    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        content = line.rstrip("\r\n")
        line_break = line[len(content) :]
        if marker is None:
            match = FENCE_START_RE.match(content)
            if match:
                fence = match.group(1)
                marker = fence[0]
                minimum_length = len(fence)
                opening_line = line_number
                cleaned.append(line_break)
            else:
                cleaned.append(INLINE_CODE_RE.sub("", line))
            continue

        if _is_fence_close(content, marker, minimum_length):
            marker = None
            minimum_length = 0
            opening_line = 0
        cleaned.append(line_break)

    warnings: list[dict] = []
    if marker is not None:
        warnings.append(
            {
                "kind": "unclosed_fence",
                "line": opening_line,
                "marker": marker * minimum_length,
            }
        )
    return "".join(cleaned), warnings


def _normalize_target(raw_target: str) -> str | None:
    target = unquote(raw_target.strip()).replace("\\", "/")
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if target.startswith(("http://", "https://", "data:")):
        return None
    target = target.split("|", 1)[0].split("#", 1)[0].strip()
    if ' "' in target:
        target = target.split(' "', 1)[0].rstrip()
    while target.startswith("./"):
        target = target[2:]
    target = target.lstrip("/")
    if not target or Path(target).suffix.casefold() not in MEDIA_EXTENSIONS:
        return None
    return target


def _extract_targets(text: str) -> list[str]:
    targets: list[str] = []
    for match in WIKI_LINK_RE.finditer(text):
        normalized = _normalize_target(match.group(1))
        if normalized:
            targets.append(normalized)
    for match in MARKDOWN_LINK_RE.finditer(text):
        normalized = _normalize_target(match.group(1))
        if normalized:
            targets.append(normalized)
    for match in HTML_MEDIA_RE.finditer(text):
        normalized = _normalize_target(match.group(1))
        if normalized:
            targets.append(normalized)
    return targets


def _extract_markdown_reference_data(
    text: str,
) -> tuple[list[str], list[str], list[dict]]:
    cleaned, warnings = _strip_code(text)
    return _extract_targets(cleaned), _extract_targets(text), warnings


def _extract_markdown_targets(text: str) -> list[str]:
    semantic, _, _ = _extract_markdown_reference_data(text)
    return semantic


def _extract_canvas_reference_data(
    payload: object,
) -> tuple[list[str], list[str], list[dict]]:
    semantic: list[str] = []
    raw: list[str] = []
    warnings: list[dict] = []
    if isinstance(payload, dict):
        if payload.get("type") == "file" and isinstance(payload.get("file"), str):
            normalized = _normalize_target(payload["file"])
            if normalized:
                semantic.append(normalized)
                raw.append(normalized)
        if isinstance(payload.get("text"), str):
            text_semantic, text_raw, text_warnings = _extract_markdown_reference_data(
                payload["text"]
            )
            semantic.extend(text_semantic)
            raw.extend(text_raw)
            warnings.extend(text_warnings)
        for value in payload.values():
            child_semantic, child_raw, child_warnings = _extract_canvas_reference_data(
                value
            )
            semantic.extend(child_semantic)
            raw.extend(child_raw)
            warnings.extend(child_warnings)
    elif isinstance(payload, list):
        for value in payload:
            child_semantic, child_raw, child_warnings = _extract_canvas_reference_data(
                value
            )
            semantic.extend(child_semantic)
            raw.extend(child_raw)
            warnings.extend(child_warnings)
    return semantic, raw, warnings


def _extract_canvas_targets(payload: object) -> list[str]:
    semantic, _, _ = _extract_canvas_reference_data(payload)
    return semantic


def _relative(path: Path, vault: Path) -> str:
    return path.relative_to(vault).as_posix()


def audit_vault_media(
    start: Path,
    managed_dirs: tuple[str, ...] = DEFAULT_MANAGED_DIRS,
) -> dict:
    vault = find_vault_root(Path(start))
    managed_roots = tuple((vault / name).resolve() for name in managed_dirs)
    all_media = sorted(set(_iter_media_files(vault)))
    managed_media = {
        path
        for path in all_media
        if any(path.is_relative_to(root) for root in managed_roots)
    }

    by_relative = {_relative(path, vault).casefold(): path for path in all_media}
    by_basename: dict[str, list[Path]] = {}
    for path in all_media:
        by_basename.setdefault(path.name.casefold(), []).append(path)

    references: set[tuple[str, str]] = set()
    raw_references: set[tuple[str, str]] = set()
    parse_warnings: list[dict] = []
    markdown_files = list(_iter_source_files(vault, ".md"))
    canvas_files = list(_iter_source_files(vault, ".canvas"))
    for source in markdown_files:
        text = source.read_text(encoding="utf-8-sig")
        source_relative = _relative(source, vault)
        semantic, raw, warnings = _extract_markdown_reference_data(text)
        references.update((source_relative, target) for target in semantic)
        raw_references.update((source_relative, target) for target in raw)
        parse_warnings.extend(
            {"source": source_relative, **warning} for warning in warnings
        )
    for source in canvas_files:
        try:
            payload = json.loads(source.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid Canvas JSON: {source}: {exc}") from exc
        source_relative = _relative(source, vault)
        semantic, raw, warnings = _extract_canvas_reference_data(payload)
        references.update((source_relative, target) for target in semantic)
        raw_references.update((source_relative, target) for target in raw)
        parse_warnings.extend(
            {"source": source_relative, **warning} for warning in warnings
        )

    referenced: set[Path] = set()
    protected: set[Path] = set()
    protected_by_raw_reference: set[Path] = set()
    missing: list[dict] = []
    ambiguous: list[dict] = []
    raw_missing: list[dict] = []
    raw_ambiguous: list[dict] = []

    def resolve(target: str) -> list[Path]:
        target_folded = target.casefold()
        exact = by_relative.get(target_folded)
        if exact:
            candidates = [exact]
        elif "/" in target:
            suffix = "/" + target_folded
            candidates = [
                path
                for relative, path in by_relative.items()
                if relative.endswith(suffix)
            ]
        else:
            candidates = by_basename.get(Path(target).name.casefold(), [])
        return sorted(set(candidates))

    for source, target in sorted(references):
        candidates = resolve(target)
        if len(candidates) == 1:
            referenced.add(candidates[0])
        elif len(candidates) > 1:
            protected.update(candidates)
            ambiguous.append(
                {
                    "source": source,
                    "target": target,
                    "candidates": [_relative(path, vault) for path in candidates],
                }
            )
        else:
            missing.append({"source": source, "target": target})

    for source, target in sorted(raw_references - references):
        candidates = resolve(target)
        if len(candidates) == 1:
            protected.add(candidates[0])
            protected_by_raw_reference.add(candidates[0])
        elif len(candidates) > 1:
            protected.update(candidates)
            protected_by_raw_reference.update(candidates)
            raw_ambiguous.append(
                {
                    "source": source,
                    "target": target,
                    "candidates": [_relative(path, vault) for path in candidates],
                }
            )
        else:
            raw_missing.append({"source": source, "target": target})

    unreferenced = managed_media - referenced - protected
    return {
        "vault": str(vault),
        "managed_dirs": list(managed_dirs),
        "scanned_markdown": len(markdown_files),
        "scanned_canvas": len(canvas_files),
        "managed_media_count": len(managed_media),
        "referenced": sorted(
            _relative(path, vault) for path in referenced if path in managed_media
        ),
        "missing": missing,
        "ambiguous": ambiguous,
        "raw_missing": raw_missing,
        "raw_ambiguous": raw_ambiguous,
        "parse_warnings": sorted(
            parse_warnings,
            key=lambda item: (
                item.get("source", ""),
                item.get("line", 0),
                item.get("kind", ""),
            ),
        ),
        "protected_by_raw_reference": sorted(
            _relative(path, vault)
            for path in protected_by_raw_reference
            if path in managed_media
        ),
        "unreferenced": sorted(_relative(path, vault) for path in unreferenced),
    }


def delete_unreferenced(report: dict, *, apply: bool = False) -> list[str]:
    if not apply:
        return []
    if report.get("parse_warnings"):
        raise ValueError("refusing deletion because a Markdown parse warning exists")
    if any(
        report.get(key)
        for key in ("missing", "ambiguous")
    ):
        raise ValueError("refusing deletion because an unresolved media reference exists")
    vault = find_vault_root(Path(report["vault"]))
    managed_roots = tuple(
        (vault / name).resolve() for name in report.get("managed_dirs", [])
    )
    if not managed_roots:
        raise ValueError("report has no managed media directories")

    candidates: list[tuple[str, Path]] = []
    for relative in report.get("unreferenced", []):
        path = (vault / relative).resolve()
        if not any(path.is_relative_to(root) and path != root for root in managed_roots):
            raise ValueError(
                f"refusing to delete outside managed media directories: {path}"
            )
        if path.is_file():
            candidates.append((relative, path))

    for _, path in candidates:
        path.unlink()
    return [relative for relative, _ in candidates]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit Obsidian image references and conservative orphan candidates."
    )
    parser.add_argument("--vault", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--delete-unreferenced", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.delete_unreferenced:
        parser.error("--apply requires --delete-unreferenced")

    report = audit_vault_media(args.vault)
    deleted: list[str] = []
    if args.delete_unreferenced:
        deleted = delete_unreferenced(report, apply=args.apply)
    report["deleted"] = deleted
    report["dry_run"] = not args.apply

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            "vault={vault}\nmanaged={managed_media_count}\nreferenced={referenced}\n"
            "missing={missing}\nambiguous={ambiguous}\nraw_missing={raw_missing}\n"
            "parse_warnings={parse_warnings}\nunreferenced={unreferenced}\n"
            "deleted={deleted}\ndry_run={dry_run}".format(
                vault=report["vault"],
                managed_media_count=report["managed_media_count"],
                referenced=len(report["referenced"]),
                missing=len(report["missing"]),
                ambiguous=len(report["ambiguous"]),
                raw_missing=len(report["raw_missing"]),
                parse_warnings=len(report["parse_warnings"]),
                unreferenced=len(report["unreferenced"]),
                deleted=len(report["deleted"]),
                dry_run=report["dry_run"],
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
