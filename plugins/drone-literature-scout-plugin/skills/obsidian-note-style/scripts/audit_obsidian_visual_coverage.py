from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from check_obsidian_links import iter_markdown_files
from obsidian_vault import find_vault_root


MANAGED_MEDIA_DIRS = ("截图存放位置", "AI绘图存放位置")
WORKING_DIRECTORY_NAMES = {
    ".codex-runtime",
    ".git",
    ".obsidian",
    ".trash",
    "backup",
    "backups",
    "skill-with-plugin",
    "temp",
    "temporary",
    "tmp",
}
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})[ \t]+(.+?)\s*$")
FENCE_RE = re.compile(r"^\s*(?:[-+*]\s+)?(?P<fence>`{3,}|~{3,})")
WIKILINK_IMAGE_RE = re.compile(r"!\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def is_working_artifact(path: Path, vault: Path) -> bool:
    parts = path.relative_to(vault).parts[:-1]
    folded = [part.casefold() for part in parts]
    if any(
        part in WORKING_DIRECTORY_NAMES or part.startswith("tmp")
        for part in folded
    ):
        return True
    return any(
        folded[index] == "docs" and folded[index + 1] == "superpowers"
        for index in range(len(folded) - 1)
    )


def normalized_heading(raw: str) -> str:
    return re.sub(r"\s+#+\s*$", "", raw).strip()


def managed_images_in(line: str) -> list[str]:
    images: list[str] = []
    for match in WIKILINK_IMAGE_RE.finditer(line):
        target = match.group(1).strip().replace("\\", "/")
        if any(
            target.casefold().startswith(directory.casefold() + "/")
            for directory in MANAGED_MEDIA_DIRS
        ):
            images.append(target)
    return images


def sections_in(text: str, path: str) -> list[dict]:
    sections: list[dict] = []
    current: dict | None = None
    fence_char: str | None = None
    fence_length = 0

    def finish_current() -> None:
        nonlocal current
        if current is None:
            return
        current["managed_images"] = sorted(set(current["managed_images"]))
        current["has_managed_image"] = bool(current["managed_images"])
        sections.append(current)
        current = None

    for line_number, line in enumerate(text.splitlines(), start=1):
        fence_match = FENCE_RE.match(line)
        if fence_char is not None:
            if fence_match:
                fence = fence_match.group("fence")
                if fence[0] == fence_char and len(fence) >= fence_length:
                    fence_char = None
                    fence_length = 0
            continue
        if fence_match:
            fence = fence_match.group("fence")
            fence_char = fence[0]
            fence_length = len(fence)
            continue

        heading_match = HEADING_RE.match(line)
        if heading_match:
            finish_current()
            heading = normalized_heading(heading_match.group(2))
            if heading:
                current = {
                    "path": path,
                    "heading": heading,
                    "level": len(heading_match.group(1)),
                    "line": line_number,
                    "managed_images": [],
                }
            continue

        if current is not None:
            current["managed_images"].extend(managed_images_in(line))

    finish_current()
    return sections


def audit_visual_coverage(start: Path) -> dict:
    vault = find_vault_root(start)
    paths: list[Path] = []
    try:
        paths.extend(iter_markdown_files(vault))
    except OSError:
        pass
    paths.sort(key=lambda path: path.relative_to(vault).as_posix())

    sections: list[dict] = []
    scanned_markdown = 0
    for path in paths:
        if is_working_artifact(path, vault):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        scanned_markdown += 1
        relative = path.relative_to(vault).as_posix()
        sections.extend(sections_in(text, relative))

    return {
        "vault": str(vault),
        "scanned_markdown": scanned_markdown,
        "sections": sections,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Audit heading sections for managed Obsidian figures."
    )
    parser.add_argument(
        "--vault",
        type=Path,
        required=True,
        help="Vault root or any path inside it; .obsidian is discovered upward.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full JSON report.")
    args = parser.parse_args()

    report = audit_visual_coverage(args.vault)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        missing = sum(not section["has_managed_image"] for section in report["sections"])
        print(
            f"scanned_markdown={report['scanned_markdown']} "
            f"sections={len(report['sections'])} without_managed_image={missing}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
