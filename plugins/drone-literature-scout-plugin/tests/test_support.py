from __future__ import annotations

import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_ROOT = (
    PLUGIN_ROOT.parent / "\u8fd0\u884c\u6570\u636e" / "test-temp"
)


@contextmanager
def writable_test_directory() -> Iterator[str]:
    """Create a writable fixture directory inside the workspace runtime area."""

    DEFAULT_TEST_ROOT.mkdir(parents=True, exist_ok=True)
    fixture_root = DEFAULT_TEST_ROOT / f"plugin-case-{uuid.uuid4().hex}"
    fixture_root.mkdir()
    try:
        yield str(fixture_root)
    finally:
        shutil.rmtree(fixture_root, ignore_errors=False)
