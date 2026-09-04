from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def compare_files(left: Path, right: Path) -> bool:
    return left.read_bytes() == right.read_bytes()


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: verify_mirror.py SKILL.md MIRROR.md", file=sys.stderr)
        return 2
    left, right = map(Path, sys.argv[1:])
    if not compare_files(left, right):
        print("MIRROR_MISMATCH", file=sys.stderr)
        return 1
    print(hashlib.sha256(left.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
