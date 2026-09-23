from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse
from obsidian_vault import find_vault_root



DEFAULT_EXCLUDED_DIR_NAMES = {
    ".git",
    ".obsidian",
    ".trash",
    "<NOTE_VAULT_NAME>",
    "无人机方向分析kimi",
}
WIKI_LINK_RE = re.compile(r"(?P<embed>!)?\[\[(?P<body>[^\]\n]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"(?P<embed>!)?\[[^\]\n]*\]\((?P<body>[^)\n]+)\)")
FENCE_MARK = chr(96)


@dataclass(frozen=True)
class LinkRef:
    source: Path
    raw: str
    target: str
    anchor: str
    is_wiki: bool
    is_embed: bool
    target_start: int
    target_end: int
    line: int


@dataclass(frozen=True)
class LinkIssue:
    source: Path
    line: int
    kind: str
    target: str
    message: str


@dataclass
class ScanReport:
    markdown_files: int
    link_count: int
    external_links: int
    issues: list[LinkIssue] = field(default_factory=list)

    def as_dict(self, vault: Path) -> dict:
        return {
            "markdown_files": self.markdown_files,
            "link_count": self.link_count,
            "external_links": self.external_links,
            "issues": [
                {
                    "source": ref.source.relative_to(vault).as_posix(),
                    "line": ref.line,
                    "kind": ref.kind,
                    "target": ref.target,
                    "message": ref.message,
                }
                for ref in self.issues
            ],
        }


def should_skip_directory(name: str, excluded: set[str]) -> bool:
    return (
        name in excluded
        or name.startswith(".")
        or name.startswith(".codex-phase-1-backup-")
        or name.startswith("tmp_")
        or name.startswith("temp_")
        or name.startswith("临时")
    )


def iter_vault_files(
    vault: Path,
    excluded_dir_names: set[str] | None = None,
) -> list[Path]:
    excluded = DEFAULT_EXCLUDED_DIR_NAMES | (excluded_dir_names or set())
    files: list[Path] = []
    for root, directories, filenames in __import__("os").walk(vault, topdown=True):
        directories[:] = [
            name for name in directories if not should_skip_directory(name, excluded)
        ]
        root_path = Path(root)
        files.extend(root_path / filename for filename in filenames)
    return sorted(files)


def iter_markdown_files(
    vault: Path,
    excluded_dir_names: set[str] | None = None,
) -> list[Path]:
    return [
        path
        for path in iter_vault_files(vault, excluded_dir_names)
        if path.suffix.casefold() == ".md"
    ]

def fenced_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    offset = 0
    start: int | None = None
    fence_char = ""
    for line in text.splitlines(keepends=True):
        match = re.match(
            r"^\s*(?P<fence>" + re.escape(FENCE_MARK) + r"{3,}|~{3,})",
            line,
        )
        if match:
            marker = match.group("fence")
            if start is None:
                start = offset
                fence_char = marker[0]
            elif marker[0] == fence_char:
                ranges.append((start, offset + len(line)))
                start = None
        offset += len(line)
    if start is not None:
        ranges.append((start, len(text)))
    return ranges


def inline_code_ranges(text: str) -> list[tuple[int, int]]:
    """Return Markdown code-span ranges delimited by equal backtick runs."""
    ranges: list[tuple[int, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        cursor = 0
        while cursor < len(line):
            opener = re.search(r"(?<!\\)(?<!`)(`+)(?!`)", line[cursor:])
            if opener is None:
                break
            start = cursor + opener.start()
            ticks = opener.group(1)
            content_start = cursor + opener.end()
            closer = re.search(
                r"(?<!`)" + re.escape(ticks) + r"(?!`)",
                line[content_start:],
            )
            if closer is None:
                cursor = content_start
                continue
            end = content_start + closer.end()
            ranges.append((offset + start, offset + end))
            cursor = end
        offset += len(line)
    return ranges
def inside_ranges(offset: int, ranges: Iterable[tuple[int, int]]) -> bool:
    return any(start <= offset < end for start, end in ranges)


def split_target(body: str) -> tuple[str, str]:
    target = body.split("|", 1)[0].strip()
    # In a Markdown table, Obsidian WikiLink aliases use ``\|`` so the
    # table parser does not treat the alias separator as a new column.
    # The backslash belongs to Markdown escaping, not to the link target.
    if target.endswith("\\"):
        target = target[:-1].rstrip()
    if "#" not in target:
        return target, ""
    file_target, anchor = target.split("#", 1)
    return file_target.strip(), anchor.strip()


def iter_links(source: Path, text: str) -> list[LinkRef]:
    excluded_ranges = fenced_ranges(text) + inline_code_ranges(text)
    refs: list[LinkRef] = []
    patterns = (
        (WIKI_LINK_RE, True),
        (MARKDOWN_LINK_RE, False),
    )
    for pattern, is_wiki in patterns:
        for match in pattern.finditer(text):
            if inside_ranges(match.start(), excluded_ranges):
                continue
            body = match.group("body").strip()
            target, anchor = split_target(body)
            if not target:
                continue
            body_start = match.start("body")
            target_offset = body.find(target)
            refs.append(
                LinkRef(
                    source=source,
                    raw=match.group(0),
                    target=target,
                    anchor=anchor,
                    is_wiki=is_wiki,
                    is_embed=bool(match.group("embed")),
                    target_start=body_start + target_offset,
                    target_end=body_start + target_offset + len(target),
                    line=text.count("\n", 0, match.start()) + 1,
                )
            )
    return sorted(refs, key=lambda ref: (ref.target_start, ref.target_end))


def is_external(target: str) -> bool:
    parsed = urlparse(target)
    return bool(parsed.scheme) or target.startswith("//")


def normalize_heading(value: str) -> str:
    value = re.sub(r"[*_~=]", "", value)
    value = re.sub(r"\s+", " ", value.strip())
    return value.casefold()


def headings_in(text: str) -> set[str]:
    headings: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            headings.add(normalize_heading(match.group(1)))
    return headings


def block_ids_in(text: str) -> set[str]:
    block_ids: set[str] = set()
    for line in text.splitlines():
        match = re.search(r"(?:^|\s)\^([A-Za-z0-9][A-Za-z0-9_-]*)\s*$", line)
        if match:
            block_ids.add(match.group(1))
    return block_ids


def path_candidates(vault: Path, source: Path, target: str, is_wiki: bool) -> list[Path]:
    clean_target = unquote(target).replace("\\", "/").lstrip("/")
    if not clean_target:
        return []
    raw = Path(clean_target)
    if is_wiki:
        direct = vault / raw
        candidates = [direct]
        if direct.suffix == "":
            candidates.append(direct.with_suffix(".md"))
        return candidates
    direct = source.parent / raw
    candidates = [direct]
    if direct.suffix == "":
        candidates.append(direct.with_suffix(".md"))
    return candidates


def build_basename_index(
    vault: Path,
    excluded_dir_names: set[str] | None = None,
) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for path in iter_vault_files(vault, excluded_dir_names):
        index.setdefault(path.name.casefold(), []).append(path)
    return index


def resolve_file(
    vault: Path,
    ref: LinkRef,
    basename_index: dict[str, list[Path]],
) -> tuple[Path | None, str | None, list[Path]]:
    if is_external(ref.target):
        return None, "external", []
    candidates = path_candidates(vault, ref.source, ref.target, ref.is_wiki)
    existing = [path for path in candidates if path.exists()]
    if existing:
        return existing[0], None, existing
    if ref.is_wiki:
        clean_target = unquote(ref.target.replace("\\", "/"))
        name = Path(clean_target).name
        if Path(name).suffix == "" and not ref.is_embed:
            name += ".md"
        moved = basename_index.get(name.casefold(), [])
        if len(moved) == 1:
            return None, "relocatable-file", moved
        if len(moved) > 1:
            return None, "ambiguous-file", moved
    return None, "missing-file", []


def check_anchor(path: Path, anchor: str) -> str | None:
    if not anchor:
        return None
    text = path.read_text(encoding="utf-8")
    if anchor.startswith("^"):
        return None if anchor[1:] in block_ids_in(text) else "missing-block"
    return None if normalize_heading(anchor) in headings_in(text) else "missing-heading"


def analyze_ref(
    vault: Path,
    ref: LinkRef,
    basename_index: dict[str, list[Path]],
) -> tuple[str | None, Path | None, list[Path]]:
    path, status, alternatives = resolve_file(vault, ref, basename_index)
    if status == "external":
        return "external", None, []
    if path is not None:
        return check_anchor(path, ref.anchor), path, alternatives
    if status == "relocatable-file" and alternatives:
        candidate = alternatives[0]
        anchor_status = check_anchor(candidate, ref.anchor)
        return anchor_status or status, candidate, alternatives
    return status, None, alternatives


def scan_vault(
    vault: Path,
    excluded_dir_names: set[str] | None = None,
) -> ScanReport:
    vault = find_vault_root(vault)
    files = iter_markdown_files(vault, excluded_dir_names)
    basename_index = build_basename_index(vault, excluded_dir_names)
    issues: list[LinkIssue] = []
    link_count = 0
    external_count = 0
    for source in files:
        text = source.read_text(encoding="utf-8")
        for ref in iter_links(source, text):
            link_count += 1
            kind, _, alternatives = analyze_ref(vault, ref, basename_index)
            if kind is None:
                continue
            if kind == "external":
                external_count += 1
                continue
            if kind == "relocatable-file":
                message = "旧路径失效，但同名目标唯一；可安全修复"
            elif kind == "ambiguous-file":
                message = "旧路径失效，但同名目标不唯一；禁止猜测"
            else:
                message = kind
            issues.append(
                LinkIssue(
                    source=source,
                    line=ref.line,
                    kind=kind,
                    target=ref.target + (("#" + ref.anchor) if ref.anchor else ""),
                    message=message
                    + (
                        " candidates="
                        + ",".join(path.relative_to(vault).as_posix() for path in alternatives)
                        if kind == "ambiguous-file"
                        else ""
                    ),
                )
            )
    return ScanReport(
        markdown_files=len(files),
        link_count=link_count,
        external_links=external_count,
        issues=issues,
    )


def replacement_target(vault: Path, ref: LinkRef, candidate: Path) -> str:
    relative = candidate.relative_to(vault).as_posix()
    if ref.is_wiki and not Path(ref.target).suffix.lower() == ".md":
        relative = relative.removesuffix(".md")
    return relative


def repair_links(
    vault: Path,
    excluded_dir_names: set[str] | None = None,
) -> int:
    vault = find_vault_root(vault)
    files = iter_markdown_files(vault, excluded_dir_names)
    basename_index = build_basename_index(vault, excluded_dir_names)
    total_changes = 0
    for source in files:
        source_bytes = source.read_bytes()
        text = source_bytes.decode("utf-8")
        edits: list[tuple[int, int, str]] = []
        for ref in iter_links(source, text):
            kind, candidate, alternatives = analyze_ref(vault, ref, basename_index)
            if kind != "relocatable-file" or candidate is None or len(alternatives) != 1:
                continue
            new_target = replacement_target(vault, ref, candidate)
            edits.append((ref.target_start, ref.target_end, new_target))
        if not edits:
            continue
        for start, end, new_target in reversed(edits):
            text = text[:start] + new_target + text[end:]
        source.write_bytes(text.encode("utf-8"))
        total_changes += len(edits)
    return total_changes

def main() -> int:
    parser = argparse.ArgumentParser(description="检查并修复 Obsidian Vault 的本地 Markdown 链接")
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    vault = find_vault_root(args.vault)
    changes = repair_links(vault) if args.repair else 0
    report = scan_vault(vault)
    payload = report.as_dict(vault)
    payload["repaired_links"] = changes
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "markdown_files={markdown_files} links={link_count} "
            "external={external_links} repaired={repaired_links} "
            "issues={issues}".format(**payload)
        )
        for issue in payload["issues"]:
            print(
                "{source}:{line} [{kind}] {target} {message}".format(**issue)
            )
    return 1 if report.issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
