"""Remove known cycle intermediates while protecting the workspace and plugin."""

from __future__ import annotations

import argparse
from pathlib import Path


KNOWN_INTERMEDIATE_NAMES = {
    ".search_checkpoint",
    ".search_cycle_lock",
    "tmp-search.json",
}
KNOWN_INTERMEDIATE_PREFIXES = ("temp_", "tmp_", "tmp-", "new_", "_encoding_probe")
KNOWN_INTERMEDIATE_SUFFIXES = (
    "_papers.csv",
    "_papers.json",
    ".search_checkpoint",
    ".tmp.csv",
    ".repaired.csv",
)


def _is_intermediate(path: Path) -> bool:
    name = path.name
    return (
        name in KNOWN_INTERMEDIATE_NAMES
        or name.startswith(KNOWN_INTERMEDIATE_PREFIXES)
        or name.endswith(KNOWN_INTERMEDIATE_SUFFIXES)
    )


def clean_cycle(workspace: Path, core_files: set[str], plugin_root: Path) -> list[Path]:
    workspace = workspace.resolve()
    plugin_root = plugin_root.resolve()
    removed: list[Path] = []
    for path in workspace.iterdir():
        if path.resolve() == plugin_root or plugin_root in path.resolve().parents:
            continue
        if path.name in core_files or not _is_intermediate(path):
            continue
        if path.is_file():
            path.unlink()
            removed.append(path)
        elif path.is_dir():
            for child in sorted(path.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            path.rmdir()
            removed.append(path)

    for cache in sorted(
        [path for path in plugin_root.rglob("__pycache__") if path.is_dir()],
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        for child in sorted(cache.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        cache.rmdir()
        removed.append(cache)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--core-file", action="append", dest="core_files", required=True)
    args = parser.parse_args()
    removed = clean_cycle(args.workspace, set(args.core_files), args.plugin)
    for path in removed:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
