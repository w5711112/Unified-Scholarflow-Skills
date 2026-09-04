from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from types import ModuleType
from typing import Any


DEPENDENCIES = {
    "fitz": "PyMuPDF",
    "yaml": "PyYAML",
}


def ensure_import(
    import_name: str,
    *,
    importer: Callable[[str], ModuleType] = importlib.import_module,
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
    executable: str = sys.executable,
) -> dict[str, Any]:
    distribution = DEPENDENCIES.get(import_name)
    if distribution is None:
        raise ValueError(f"dependency is not allow-listed: {import_name}")

    installed = False
    try:
        module = importer(import_name)
    except ModuleNotFoundError as error:
        if error.name not in {import_name, import_name.split(".", 1)[0]}:
            raise
        runner(
            [
                executable,
                "-m",
                "pip",
                "install",
                distribution,
            ],
            check=True,
        )
        importlib.invalidate_caches()
        module = importer(import_name)
        installed = True

    return {
        "import_name": import_name,
        "distribution": distribution,
        "executable": executable,
        "installed": installed,
        "version": getattr(module, "__version__", None),
    }


def ensure_dependencies(import_names: Sequence[str]) -> list[dict[str, Any]]:
    return [ensure_import(name) for name in import_names]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "imports",
        nargs="*",
        default=["fitz", "yaml"],
        choices=sorted(DEPENDENCIES),
    )
    args = parser.parse_args()
    reports = ensure_dependencies(args.imports)
    print(json.dumps(reports, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
