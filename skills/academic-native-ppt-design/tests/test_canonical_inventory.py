from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MERGED_TESTS = {
    "behavioral-scenarios.md": "03c33dcb2bf3453c8b4781afbf181928be4ef74b439eb070dbb6310664d980dc",
    "test_audit_pptx.py": "b929038eb88fffe8e98ff253984a1bb2511ff19c5cdbb6b16053e6f7c3d79fa7",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_canonical_skill_contains_only_the_verified_unique_test_additions() -> None:
    for name, expected in EXPECTED_MERGED_TESTS.items():
        path = ROOT / "tests" / name
        assert path.is_file()
        assert sha256(path) == expected


def test_canonical_skill_excludes_generated_caches_and_business_decks() -> None:
    assert not any(path.name in {"__pycache__", ".pytest_cache"} for path in ROOT.rglob("*"))
    assert not any(path.suffix.casefold() == ".pptx" for path in ROOT.rglob("*"))
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for token in ("__pycache__/", ".pytest_cache/", "*.py[cod]"):
        assert token in ignore
