from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORTABLE_TEST_ASSETS = ("behavioral-scenarios.md", "test_audit_pptx.py")


def test_public_skill_contains_portable_test_assets() -> None:
    for name in PORTABLE_TEST_ASSETS:
        path = ROOT / "tests" / name
        assert path.is_file()


def test_canonical_skill_excludes_generated_caches_and_business_decks() -> None:
    assert not any(path.name in {"__pycache__", ".pytest_cache"} for path in ROOT.rglob("*"))
    assert not any(path.suffix.casefold() == ".pptx" for path in ROOT.rglob("*"))
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for token in ("__pycache__/", ".pytest_cache/", "*.py[cod]"):
        assert token in ignore
