from __future__ import annotations

import argparse
import json
from pathlib import Path

from check_obsidian_links import block_ids_in, headings_in, iter_markdown_files
from obsidian_vault import find_vault_root, normalize_markdown_basename


WORKING_DIRECTORY_NAMES = {
    "backup",
    "backups",
    "skill-with-plugin",
    "temp",
    "temporary",
    "tmp",
}


def is_working_artifact(path: Path, vault: Path) -> bool:
    return any(
        directory.casefold() in WORKING_DIRECTORY_NAMES
        or directory.casefold().startswith("tmp")
        for directory in path.relative_to(vault).parts[:-1]
    )
def find_notes_by_basename(start: Path, name: str) -> list[Path]:
    """Find every non-temporary note with this basename in the actual vault."""
    vault = find_vault_root(start)
    target = normalize_markdown_basename(name).casefold()
    return sorted(
        path
        for path in iter_markdown_files(vault)
        if not is_working_artifact(path, vault) and path.name.casefold() == target
    )




def normalized_term_hits(headings: list[str], block_ids: list[str]) -> list[str]:
    return sorted({*headings, *(block_id.casefold() for block_id in block_ids)})


def build_index(vault: Path) -> dict:
    vault = find_vault_root(vault)
    paths: list[Path] = []
    try:
        paths.extend(iter_markdown_files(vault))
    except OSError:
        pass
    paths.sort(key=lambda path: path.relative_to(vault).as_posix())
    records: list[dict] = []
    for path in paths:
        if is_working_artifact(path, vault):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        headings = sorted(headings_in(text))
        block_ids = sorted(block_ids_in(text))
        records.append(
            {
                "path": path.relative_to(vault).as_posix(),
                "headings": headings,
                "block_ids": block_ids,
                "term_hits": normalized_term_hits(headings, block_ids),
            }
        )
    return {"vault": str(vault), "files": records}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a deterministic Obsidian knowledge index."
    )
    parser.add_argument(
        "--vault",
        type=Path,
        required=True,
        help="Vault root or any path inside it; .obsidian is discovered upward.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload = build_index(args.vault)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
