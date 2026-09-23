from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path


BRIDGE_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_FILES = (
    "annotation_bridge.js",
    "bootstrap.js",
    "link_bridge.js",
    "manifest.json",
    "merge_bridge.js",
)
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def package_xpi(output: str | Path) -> dict[str, str]:
    output_path = Path(output).resolve()
    if output_path.suffix.lower() != ".xpi":
        raise ValueError("output must use the .xpi extension")
    missing = [name for name in PACKAGE_FILES if not (BRIDGE_ROOT / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing package inputs: {missing}")

    manifest = json.loads((BRIDGE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    plugin_id = manifest["applications"]["zotero"]["id"]
    version = manifest["version"]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".zotero-local-bridge-",
        suffix=".xpi.tmp",
        dir=output_path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for name in PACKAGE_FILES:
                info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(
                    info,
                    (BRIDGE_ROOT / name).read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
        os.replace(temporary, output_path)
    finally:
        if temporary.exists():
            temporary.unlink()

    return {
        "output": str(output_path),
        "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "plugin_id": plugin_id,
        "version": version,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the deterministic Zotero Local Bridge XPI.")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            package_xpi(args.output),
            ensure_ascii=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
