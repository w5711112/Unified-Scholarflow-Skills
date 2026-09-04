"""Keep focused tests importable from either the Skill or project root."""

from pathlib import Path
import sys


def ensure_skill_root_on_path() -> None:
    skill_root = str(Path(__file__).resolve().parents[1])
    if skill_root not in sys.path:
        sys.path.insert(0, skill_root)
