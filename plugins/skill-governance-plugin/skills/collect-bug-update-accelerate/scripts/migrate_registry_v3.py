from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from problem_families import load_family_catalog
from registry_v3 import (
    apply_v3_plan,
    family_report,
    plan_v3_migration,
    validate_v3,
    verify_conservation,
)
from incident_registry import registry_lock, validate_registry


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.restore.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def migrate_path(
    registry_path: Path,
    *,
    apply: bool,
    report_path: Path | None = None,
    preview_path: Path | None = None,
) -> dict[str, Any]:
    registry_resolved = registry_path.resolve()
    output_paths = [item.resolve() for item in (report_path, preview_path) if item is not None]
    if registry_resolved in output_paths:
        raise ValueError("report and preview paths must differ from the registry path")
    if len(output_paths) != len(set(output_paths)):
        raise ValueError("report and preview paths must differ from each other")
    if apply:
        with registry_lock(registry_path):
            return _migrate_path_unlocked(
                registry_path,
                apply=True,
                report_path=report_path,
                preview_path=preview_path,
            )
    return _migrate_path_unlocked(
        registry_path,
        apply=False,
        report_path=report_path,
        preview_path=preview_path,
    )


def _migrate_path_unlocked(
    registry_path: Path,
    *,
    apply: bool,
    report_path: Path | None,
    preview_path: Path | None,
) -> dict[str, Any]:
    source_bytes = registry_path.read_bytes()
    source_file_sha256 = hashlib.sha256(source_bytes).hexdigest()
    source = json.loads(source_bytes.decode("utf-8"))
    if source.get("schema_version") == 3:
        validate_v3(source)
        result = {
            "status": "already-v3",
            "registry": str(registry_path),
            "source_file_sha256": source_file_sha256,
            "family_report": family_report(source),
        }
        if report_path is not None:
            _write_json_atomic(report_path, result)
        return result
    validate_registry(source)
    plan = plan_v3_migration(source, load_family_catalog())
    migrated = apply_v3_plan(source, plan)
    conservation = verify_conservation(source, migrated, plan)
    result = {
        "status": "applied" if apply else "dry-run",
        "registry": str(registry_path),
        "source_file_sha256": source_file_sha256,
        "plan": plan.to_dict(),
        "conservation": conservation.to_dict(),
        "family_report": family_report(migrated),
    }
    if preview_path is not None:
        _write_json_atomic(preview_path, migrated)
    if apply:
        if hashlib.sha256(registry_path.read_bytes()).hexdigest() != source_file_sha256:
            raise ValueError("registry bytes changed after dry-run planning")
        stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
        backup = registry_path.with_name(f"{registry_path.name}.v2-{stamp}.bak")
        if backup.exists():
            raise FileExistsError(f"backup already exists: {backup}")
        shutil.copyfile(registry_path, backup)
        if backup.read_bytes() != source_bytes:
            backup.unlink(missing_ok=True)
            raise ValueError("byte backup verification failed")
        try:
            _write_json_atomic(registry_path, migrated)
            reread = json.loads(registry_path.read_text(encoding="utf-8"))
            validate_v3(reread)
            result["backup"] = str(backup)
            result["target_file_sha256"] = hashlib.sha256(registry_path.read_bytes()).hexdigest()
            if report_path is not None:
                _write_json_atomic(report_path, result)
        except Exception:
            _write_bytes_atomic(registry_path, source_bytes)
            raise
    elif report_path is not None:
        _write_json_atomic(report_path, result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Explicit schema v2 to v3 incident migration")
    parser.add_argument("--registry", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--preview", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = migrate_path(
            args.registry,
            apply=args.apply,
            report_path=args.report,
            preview_path=args.preview,
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
