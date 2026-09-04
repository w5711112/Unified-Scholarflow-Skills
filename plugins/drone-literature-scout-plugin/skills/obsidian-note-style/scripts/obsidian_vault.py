from __future__ import annotations

from pathlib import Path


def find_vault_root(start: Path) -> Path:
    """Return the nearest ancestor that is an actual Obsidian vault root."""
    resolved = start.expanduser().resolve()
    current = resolved.parent if resolved.is_file() else resolved
    for candidate in (current, *current.parents):
        if (candidate / ".obsidian").is_dir():
            return candidate
    raise ValueError(
        f"No Obsidian vault root containing a .obsidian directory was found above: {resolved}"
    )


def normalize_markdown_basename(name: str) -> str:
    """Normalize a requested note basename and reject paths masquerading as names."""
    candidate = name.strip()
    if not candidate or Path(candidate).name != candidate:
        raise ValueError("note name must be a non-empty basename, not a path")
    return candidate if candidate.casefold().endswith(".md") else candidate + ".md"
