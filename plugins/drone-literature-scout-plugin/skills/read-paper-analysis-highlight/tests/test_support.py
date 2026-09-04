from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_ROOT = (
    SKILL_ROOT.parents[2] / "\u8fd0\u884c\u6570\u636e" / "test-temp"
)


@contextmanager
def writable_test_directory() -> Iterator[str]:
    """Create a normal writable fixture directory outside the skill source tree."""

    DEFAULT_TEST_ROOT.mkdir(parents=True, exist_ok=True)
    fixture_root = DEFAULT_TEST_ROOT / f"case-{uuid.uuid4().hex}"
    fixture_root.mkdir()
    try:
        yield str(fixture_root)
    finally:
        shutil.rmtree(fixture_root, ignore_errors=False)
