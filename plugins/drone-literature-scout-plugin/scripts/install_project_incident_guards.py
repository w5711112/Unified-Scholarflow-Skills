from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE_BOOTSTRAP = Path.home() / ".agents" / "plugins" / "sources" / "skill-governance-plugin"
BOOTSTRAP_REGISTRY = GOVERNANCE_BOOTSTRAP / "ecosystem-registry.json"


def resolve_incident_provider(registry_path: Path = BOOTSTRAP_REGISTRY) -> dict[str, Any]:
    """Resolve the global incident provider only through the bootstrap registry."""
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    component_id = "global.collect-bug-update-accelerate"
    component = next(
        (item for item in registry.get("components", []) if item.get("id") == component_id),
        None,
    )
    if component is None or component.get("status") != "active":
        raise ValueError("global incident provider is not an active registry component")
    root = registry.get("roots", {}).get(component.get("root"), {})
    root_path = root.get("path")
    relative_path = component.get("relative_path")
    if not isinstance(root_path, str) or not isinstance(relative_path, str):
        raise ValueError("global incident provider has no resolvable registry path")
    provider_root = Path(root_path) / relative_path
    script_root = provider_root / "scripts"
    bootstrap = next(
        (
            item
            for item in registry.get("components", [])
            if item.get("id") == "global.skill-governance-plugin"
        ),
        None,
    )
    if bootstrap is None:
        raise ValueError("governance bootstrap component is absent from the registry")
    bootstrap_root = registry.get("roots", {}).get(bootstrap.get("root"), {})
    bootstrap_path = bootstrap_root.get("path")
    bootstrap_relative = bootstrap.get("relative_path")
    if not isinstance(bootstrap_path, str) or not isinstance(bootstrap_relative, str):
        raise ValueError("governance bootstrap has no resolvable registry path")
    skillctl = Path(bootstrap_path) / bootstrap_relative / "scripts" / "skillctl.py"
    script_name = "incident_registry.py"
    if not (script_root / script_name).is_file() or not skillctl.is_file():
        raise FileNotFoundError("resolved global incident provider bootstrap is incomplete")
    return {
        "component_id": component_id,
        "script_name": script_name,
        "provider_root": provider_root,
        "script_root": script_root,
        "skillctl": skillctl,
    }


INCIDENT_PROVIDER = resolve_incident_provider()
SKILL_ROOT = INCIDENT_PROVIDER["provider_root"]
REFERENCE_ROOT = SKILL_ROOT / "references"
DEFAULT_SCOPE_PATH = REFERENCE_ROOT / "project-scope.json"
DEFAULT_TEMPLATE_PATH = REFERENCE_ROOT / "project-incident-guard.md"
INCIDENT_SCRIPT_ROOT = INCIDENT_PROVIDER["script_root"]
SKILLCTL_PATH = INCIDENT_PROVIDER["skillctl"]
if str(INCIDENT_SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(INCIDENT_SCRIPT_ROOT))

from incident_registry import empty_registry, load_registry, save_registry_atomic  # noqa: E402


BEGIN_MARKER = "<!-- BEGIN COLLECT-BUG-UPDATE-ACCELERATE -->"
END_MARKER = "<!-- END COLLECT-BUG-UPDATE-ACCELERATE -->"
LEGACY_LOCAL_REGISTRY_RELATIVE_PATH = Path(".codex") / "collect-bug-update-accelerate" / "incident-registry.json"
EXPECTED_EXCLUSIONS = {
    "ordinary-chatgpt-chats",
    "projectless-tasks",
    "other-projects",
}


def _canonical_path(value: str | Path) -> str:
    return str(Path(value).resolve()).casefold()


def load_scope(path: Path) -> dict[str, Any]:
    scope = json.loads(Path(path).read_text(encoding="utf-8"))
    if scope.get("schema_version") != 1:
        raise ValueError("project scope schema_version must be 1")
    roots = scope.get("approved_project_roots")
    if not isinstance(roots, list) or len(roots) != 6:
        raise ValueError("project scope must contain exactly six approved roots")
    if not all(isinstance(root, str) and Path(root).is_absolute() for root in roots):
        raise ValueError("every approved project root must be an absolute path")
    canonical_roots = [_canonical_path(root) for root in roots]
    if len(set(canonical_roots)) != 6:
        raise ValueError("approved project roots must be unique")
    provider = scope.get("incident_provider")
    if provider != {
        "component_id": "global.collect-bug-update-accelerate",
        "script_name": "incident_registry.py",
    }:
        raise ValueError("scope must name the stable global incident provider")
    value = scope.get("public_registry_path")
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError("public_registry_path must be absolute")
    relative = scope.get("local_registry_relative_path")
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("local_registry_relative_path must be relative")
    if ".." in Path(relative).parts:
        raise ValueError("local_registry_relative_path cannot escape the project")
    exclusions = scope.get("exclusions")
    if not isinstance(exclusions, list) or set(exclusions) != EXPECTED_EXCLUSIONS:
        raise ValueError("scope exclusions must be exact")
    return scope


def _assert_approved(project_root: Path, scope: dict[str, Any]) -> Path:
    resolved = Path(project_root).resolve()
    approved = {
        _canonical_path(root)
        for root in scope.get("approved_project_roots", [])
    }
    if _canonical_path(resolved) not in approved:
        raise ValueError("target is outside the approved project scope: {}".format(resolved))
    return resolved


def render_guard(project_root: Path, scope: dict[str, Any]) -> str:
    root = _assert_approved(project_root, scope)
    template = DEFAULT_TEMPLATE_PATH.read_text(encoding="utf-8")
    local_registry = root / Path(scope["local_registry_relative_path"])
    replacements = {
        "{PROJECT_ROOT}": str(root),
        "{LOCAL_REGISTRY}": str(local_registry),
        "{PUBLIC_REGISTRY}": scope["public_registry_path"],
        "{SKILLCTL}": str(SKILLCTL_PATH),
        "{INCIDENT_COMPONENT}": scope["incident_provider"]["component_id"],
        "{INCIDENT_SCRIPT}": scope["incident_provider"]["script_name"],
    }
    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    unresolved = [placeholder for placeholder in replacements if placeholder in rendered]
    if unresolved:
        raise ValueError("unresolved guard placeholders: {}".format(unresolved))
    if rendered.count(BEGIN_MARKER) != 1 or rendered.count(END_MARKER) != 1:
        raise ValueError("guard template must contain exactly one managed block")
    return rendered.strip() + "\n"


def merge_managed_block(existing: str, rendered: str) -> str:
    if rendered.count(BEGIN_MARKER) != 1 or rendered.count(END_MARKER) != 1:
        raise ValueError("rendered guard must contain exactly one managed block")
    begin_count = existing.count(BEGIN_MARKER)
    end_count = existing.count(END_MARKER)
    if begin_count != end_count or begin_count not in {0, 1}:
        raise ValueError("existing AGENTS.md has malformed managed markers")
    eol = "\r\n" if "\r\n" in existing else "\n"
    block = rendered.strip().replace("\r\n", "\n").replace("\n", eol)
    if begin_count == 0:
        prefix = existing.rstrip()
        return (prefix + eol + eol if prefix else "") + block + eol
    start = existing.index(BEGIN_MARKER)
    end = existing.index(END_MARKER, start) + len(END_MARKER)
    return existing[:start] + block + existing[end:]


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".{}.{}.{}.tmp".format(path.name, os.getpid(), uuid.uuid4().hex))
    try:
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def apply_project_guard(
    project_root: Path,
    scope: dict[str, Any],
    *,
    apply: bool,
) -> dict[str, Any]:
    root = _assert_approved(project_root, scope)
    if not root.is_dir():
        raise FileNotFoundError("approved project root does not exist: {}".format(root))
    agents_path = root / "AGENTS.md"
    local_registry = root / Path(scope["local_registry_relative_path"])
    legacy_registry = root / LEGACY_LOCAL_REGISTRY_RELATIVE_PATH
    existing = agents_path.read_text(encoding="utf-8") if agents_path.is_file() else ""
    rendered = render_guard(root, scope)
    merged = merge_managed_block(existing, rendered)
    agents_change_needed = merged != existing
    registry_missing = not local_registry.is_file()
    legacy_payload = load_registry(legacy_registry) if legacy_registry.is_file() else None
    current_payload = None if registry_missing else load_registry(local_registry)
    if current_payload is not None and legacy_payload is not None:
        current_by_id = {item["id"]: item for item in current_payload["incidents"]}
        legacy_is_preserved = all(
            current_by_id.get(item["id"]) == item for item in legacy_payload["incidents"]
        )
        if current_payload["incidents"] and legacy_payload["incidents"] and not legacy_is_preserved:
            raise ValueError("new registry does not fully preserve the non-empty legacy registry")
    initial_payload = legacy_payload if legacy_payload is not None else empty_registry()
    agents_changed = False
    registry_created = False
    legacy_registry_migrated = False
    if apply and agents_change_needed:
        _write_text_atomic(agents_path, merged)
        agents_changed = True
    if apply and registry_missing:
        save_registry_atomic(local_registry, initial_payload)
        registry_created = True
        legacy_registry_migrated = legacy_payload is not None
    return {
        "project_root": str(root),
        "agents_path": str(agents_path),
        "local_registry": str(local_registry),
        "agents_change_needed": agents_change_needed,
        "registry_missing": registry_missing,
        "agents_changed": agents_changed,
        "registry_created": registry_created,
        "legacy_registry_migrated": legacy_registry_migrated,
    }


def run(scope: dict[str, Any], *, apply: bool) -> tuple[list[dict[str, Any]], int]:
    reports: list[dict[str, Any]] = []
    failures = 0
    for raw_root in scope["approved_project_roots"]:
        root = Path(raw_root)
        if not root.is_dir():
            reports.append({"project_root": str(root), "project_missing": True})
            failures += 1
            continue
        try:
            reports.append(apply_project_guard(root, scope, apply=apply))
        except (OSError, ValueError) as exc:
            reports.append({"project_root": str(root), "error": str(exc)})
            failures += 1
    return reports, failures


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install or check approved project incident guards.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--scope", type=Path, default=DEFAULT_SCOPE_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    scope = load_scope(args.scope)
    reports, failures = run(scope, apply=args.apply)
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "check",
                "targets": len(reports),
                "failures": failures,
                "reports": reports,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if args.apply and failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
