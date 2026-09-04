from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    from ecosystem_overview import audit_guides, audit_overview, sync_guides, sync_overview
except ModuleNotFoundError:
    from scripts.ecosystem_overview import audit_guides, audit_overview, sync_guides, sync_overview


@dataclass(frozen=True)
class Finding:
    code: str
    component_id: str
    message: str


@dataclass(frozen=True)
class MigrationPlan:
    component_id: str
    candidate_root: str
    candidate_relative_path: str
    target_root: str
    target_relative_path: str
    target_mirrors: list[str]
    expected_sha256: str
    previous_root: str
    previous_relative_path: str


@dataclass(frozen=True)
class RuntimeProbe:
    interpreter: str
    satisfied: bool
    missing: list[str]
    mismatched: list[str]


IGNORED_PARTS = {".git", "__pycache__", ".pytest_cache", ".staging", ".quarantine"}
IGNORED_NAMES = {"ecosystem-lock.json"}
ALLOWED_STATUS = {"active", "installed", "staging", "quarantine", "retired", "managed_external", "runtime_data"}
LIFECYCLE_EVENT_ROUTES = {
    "incident-promotion": (
        "global.collect-bug-update-accelerate",
        "incident_registry.py",
        "promotion-result",
    ),
    "release-packaging": (
        "global.github-upload",
        "release_tool.py",
        "build",
    ),
}
LOCK_COMPONENT_FIELDS = (
    "id", "kind", "owner", "root", "relative_path", "version",
    "interface_version", "status", "requires", "runtime", "model_policy", "mirrors", "tests",
)


def load_registry(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("ecosystem registry schema_version must be 1")
    return data


def _component_map(data: dict[str, object]) -> dict[str, dict[str, object]]:
    components = data.get("components")
    if not isinstance(components, list):
        raise ValueError("components must be a list")
    return {str(item["id"]): item for item in components if isinstance(item, dict)}


def resolve_component(registry_path: Path, component_id: str) -> Path:
    data = load_registry(registry_path)
    components = _component_map(data)
    if component_id not in components:
        raise KeyError(component_id)
    component = components[component_id]
    if component["status"] not in {"active", "runtime_data", "managed_external"}:
        raise ValueError(f"component is not resolvable: {component_id}")
    return _declared_path(data, str(component["root"]), str(component["relative_path"]))


def run_component_script(registry_path: Path, component_id: str, script_name: str, arguments: list[str]) -> int:
    component_root = resolve_component(registry_path, component_id)
    scripts_root = (component_root / "scripts").resolve()
    script = (scripts_root / script_name).resolve()
    if scripts_root not in script.parents or not script.is_file():
        raise ValueError(f"unknown component script: {script_name}")
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", str(script), *arguments],
        check=False,
        shell=False,
    )
    return int(completed.returncode)


def runtime_key(lock_path: Path) -> str:
    return hashlib.sha256(lock_path.read_bytes()).hexdigest()


def runtime_path(lock_path: Path, kind: str) -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("LOCALAPPDATA is required on Windows")
    return Path(local) / "SkillRuntime" / kind / runtime_key(lock_path)


def _locked_versions(lock_path: Path) -> dict[str, str]:
    locked: dict[str, str] = {}
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, separator, version = stripped.partition("==")
        if not separator or not name or not version:
            raise ValueError(f"lock entry must use name==version: {stripped}")
        locked[name] = version
    return locked


def probe_python_runtime(interpreter: Path, lock_path: Path) -> RuntimeProbe:
    locked = _locked_versions(lock_path)
    probe_code = "\n".join([
        "import importlib.metadata as metadata",
        "import json",
        "import sys",
        "names = json.loads(sys.argv[1])",
        "result = {}",
        "for name in names:",
        "    try:",
        "        result[name] = metadata.version(name)",
        "    except metadata.PackageNotFoundError:",
        "        result[name] = None",
        "print(json.dumps(result, sort_keys=True))",
    ])
    completed = subprocess.run(
        [str(interpreter), "-X", "utf8", "-c", probe_code, json.dumps(sorted(locked))],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        failure = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "probe failed"
        return RuntimeProbe(str(interpreter), False, [failure], [])
    installed = json.loads(completed.stdout)
    missing = sorted(name for name in locked if installed.get(name) is None)
    mismatched = sorted(
        f"{name}: required {locked[name]}, installed {installed[name]}"
        for name in locked
        if installed.get(name) is not None and installed[name] != locked[name]
    )
    return RuntimeProbe(str(interpreter), not missing and not mismatched, missing, mismatched)


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        path for path in root.rglob("*") if path.is_file() and path.name not in IGNORED_NAMES
        and not any(part in IGNORED_PARTS for part in path.parts)
    )
    for path in files:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        payload = path.read_bytes()
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _root_and_relative(data: dict[str, object], candidate: Path, required_kind: str) -> tuple[str, str]:
    resolved = candidate.resolve()
    matches: list[tuple[str, str]] = []
    for root_id, root_item in data["roots"].items():
        if root_item["kind"] != required_kind:
            continue
        root_path = Path(str(root_item["path"])).resolve()
        if resolved == root_path or root_path in resolved.parents:
            matches.append((str(root_id), resolved.relative_to(root_path).as_posix()))
    if len(matches) != 1:
        raise ValueError(f"path must resolve inside exactly one {required_kind} root")
    return matches[0]


def _declared_path(data: dict[str, object], root_id: str, relative_path: str) -> Path:
    roots = data["roots"]
    if root_id not in roots:
        raise ValueError("ROOT_UNKNOWN")
    root = Path(str(roots[root_id]["path"])).resolve()
    resolved = (root / relative_path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("PATH_OUTSIDE_ROOT")
    return resolved


def _write_file_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".next", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_registry(registry_path: Path, data: dict[str, object]) -> None:
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _write_file_atomic(registry_path, payload)


def _restore_registry(registry_path: Path, previous_registry_bytes: bytes) -> None:
    _write_file_atomic(registry_path, previous_registry_bytes)


def _write_new_file_atomic(path: Path, payload: bytes) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".next", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def dependency_order(data: dict[str, object], component_ids: list[str]) -> list[str]:
    components = _component_map(data)
    visiting: set[str] = set()
    visited: set[str] = set()
    ordered: list[str] = []

    def visit(component_id: str) -> None:
        if component_id in visited:
            return
        if component_id in visiting:
            raise ValueError("PROVIDER_CYCLE")
        if component_id not in components:
            raise KeyError(component_id)
        visiting.add(component_id)
        for provider_id in components[component_id].get("requires", []):
            visit(str(provider_id))
        visiting.remove(component_id)
        visited.add(component_id)
        ordered.append(component_id)

    for requested in component_ids:
        visit(requested)
    return ordered


def _source_cache_findings(data: dict[str, object]) -> list[Finding]:
    findings: list[Finding] = []
    for component_id, item in _component_map(data).items():
        if item.get("status") != "active" or item.get("kind") not in {"skill", "plugin"}:
            continue
        try:
            canonical = _declared_path(data, str(item["root"]), str(item["relative_path"]))
        except (KeyError, ValueError):
            continue
        if not canonical.exists():
            continue
        for path in canonical.rglob("*"):
            if path.name in {"__pycache__", ".pytest_cache"} or path.suffix.lower() in {".pyc", ".pyo"}:
                findings.append(Finding("SOURCE_CACHE_PRESENT", component_id, str(path)))
    return findings


def validate_registry(data: dict[str, object]) -> list[Finding]:
    findings: list[Finding] = []
    rows, roots = data.get("components"), data.get("roots")
    if not isinstance(rows, list) or not isinstance(roots, dict):
        return [Finding("REGISTRY_SHAPE", "registry", "roots must be an object and components must be a list")]
    ids = [str(item.get("id", "")) for item in rows if isinstance(item, dict)]
    for component_id in sorted(set(ids)):
        if ids.count(component_id) != 1:
            findings.append(Finding("DUPLICATE_COMPONENT_ID", component_id, "component id must occur once"))
    components = _component_map(data)
    active_paths: dict[str, str] = {}
    for component_id, item in components.items():
        status, root_id = str(item.get("status", "")), str(item.get("root", ""))
        if status not in ALLOWED_STATUS:
            findings.append(Finding("STATUS_INVALID", component_id, status))
        if root_id not in roots:
            findings.append(Finding("ROOT_UNKNOWN", component_id, root_id))
            continue
        root_kind = str(roots[root_id].get("kind", ""))
        if status == "active" and root_kind != "authority":
            findings.append(Finding("ACTIVE_ROOT_NOT_AUTHORITY", component_id, root_kind))
        if status == "managed_external" and root_kind != "external":
            findings.append(Finding("EXTERNAL_ROOT_INVALID", component_id, root_kind))
        if status == "runtime_data" and root_kind != "derived":
            findings.append(Finding("RUNTIME_ROOT_INVALID", component_id, root_kind))
        try:
            canonical = _declared_path(data, root_id, str(item.get("relative_path", "")))
        except ValueError:
            findings.append(Finding("PATH_OUTSIDE_ROOT", component_id, str(item.get("relative_path", ""))))
            continue
        if status == "active":
            key = os.path.normcase(str(canonical))
            if key in active_paths:
                findings.append(Finding("DUPLICATE_ACTIVE_PATH", component_id, active_paths[key]))
            active_paths[key] = component_id
            if not canonical.exists():
                findings.append(Finding("ACTIVE_PATH_MISSING", component_id, str(canonical)))
        for provider_id in item.get("requires", []):
            provider = components.get(str(provider_id))
            if provider is None:
                findings.append(Finding("PROVIDER_MISSING", component_id, str(provider_id)))
            elif provider.get("status") == "retired":
                findings.append(Finding("PROVIDER_RETIRED", component_id, str(provider_id)))
        model_policy = str(item.get("model_policy", ""))
        if model_policy.startswith("explicit:") and not component_id.startswith("modeling."):
            findings.append(Finding("MODEL_POLICY_FORBIDDEN", component_id, model_policy))
        staging_paths, rollback_paths = item.get("staging_paths", []), item.get("rollback_paths", [])
        if len(staging_paths) > 1:
            findings.append(Finding("MULTIPLE_STAGING", component_id, str(staging_paths)))
        if len(rollback_paths) > 1:
            findings.append(Finding("MULTIPLE_ROLLBACK", component_id, str(rollback_paths)))
        for mirror_relative in item.get("mirrors", []):
            try:
                mirror = _declared_path(data, root_id, str(mirror_relative))
            except ValueError:
                findings.append(Finding("MIRROR_OUTSIDE_ROOT", component_id, str(mirror_relative)))
                continue
            skill_file = canonical / "SKILL.md" if canonical.is_dir() else canonical
            if status == "active" and (not mirror.is_file() or mirror.read_bytes() != skill_file.read_bytes()):
                findings.append(Finding("MIRROR_MISMATCH", component_id, str(mirror)))
        if status == "active" and item.get("kind") == "plugin":
            versions = {str(item.get("version", ""))}
            manifest, architecture = canonical / ".codex-plugin" / "plugin.json", canonical / "architecture-manifest.json"
            if manifest.is_file():
                versions.add(str(json.loads(manifest.read_text(encoding="utf-8"))["version"]))
            if architecture.is_file():
                value = json.loads(architecture.read_text(encoding="utf-8"))
                if "release_version" in value:
                    versions.add(str(value["release_version"]))
            if len(versions) != 1:
                findings.append(Finding("VERSION_MISMATCH", component_id, str(sorted(versions))))
    for component_id, item in components.items():
        previous = item.get("previous_path")
        if previous is None:
            continue
        if not isinstance(previous, dict):
            findings.append(Finding("PREVIOUS_PATH_INVALID", component_id, str(previous)))
            continue
        previous_root, previous_relative = str(previous.get("root", "")), str(previous.get("relative_path", ""))
        if previous_root not in roots or not previous_relative:
            findings.append(Finding("PREVIOUS_PATH_INVALID", component_id, str(previous)))
            continue
        try:
            previous_path = _declared_path(data, previous_root, previous_relative)
        except ValueError:
            findings.append(Finding("PREVIOUS_PATH_INVALID", component_id, str(previous)))
            continue
        if os.path.normcase(str(previous_path)) in active_paths:
            findings.append(Finding("PREVIOUS_PATH_ACTIVE", component_id, active_paths[os.path.normcase(str(previous_path))]))
    try:
        dependency_order(data, list(components))
    except KeyError:
        pass
    except ValueError:
        findings.append(Finding("PROVIDER_CYCLE", "registry", "requires graph contains a cycle"))
    findings.extend(_source_cache_findings(data))
    return findings


def _audit_ids(data: dict[str, object], changed: list[str]) -> set[str]:
    components = _component_map(data)
    selected, pending = set(changed), list(changed)
    while pending:
        current = pending.pop()
        if current not in components:
            continue
        for provider in components[current].get("requires", []):
            if provider in components and provider not in selected:
                selected.add(provider)
                pending.append(provider)
        for consumer_id, consumer in components.items():
            if current in consumer.get("requires", []) and consumer_id not in selected:
                selected.add(consumer_id)
                pending.append(consumer_id)
    return selected


def audit_components(data: dict[str, object], changed: list[str]) -> list[Finding]:
    selected = _audit_ids(data, changed)
    relationship_findings = {
        "DUPLICATE_ACTIVE_PATH",
        "PREVIOUS_PATH_ACTIVE",
        "PROVIDER_CYCLE",
    }
    return [
        item
        for item in validate_registry(data)
        if item.component_id in selected
        or item.component_id == "registry"
        or item.code in relationship_findings
    ]


def after_lifecycle_event(
    registry_path: Path,
    changed_component_ids: list[str],
    previous_registry_bytes: bytes | None = None,
) -> int:
    try:
        data = load_registry(registry_path)
        findings = audit_components(data, changed_component_ids)
        print(json.dumps([asdict(item) for item in findings], ensure_ascii=False, indent=2))
    except Exception:
        if previous_registry_bytes is not None:
            _restore_registry(registry_path, previous_registry_bytes)
        raise
    if not findings:
        return 0
    if previous_registry_bytes is not None:
        _restore_registry(registry_path, previous_registry_bytes)
    return 2


def register_component(registry_path: Path, record_path: Path) -> str:
    data = load_registry(registry_path)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
        raise ValueError("component record must contain a non-empty id")
    component_id = str(record["id"])
    if component_id in _component_map(data):
        raise ValueError("DUPLICATE_COMPONENT_ID")
    data["components"].append(record)
    _write_registry(registry_path, data)
    return component_id


def _changed_registry_components(
    before: dict[str, object], after: dict[str, object]
) -> set[str]:
    before_components = _component_map(before)
    after_components = _component_map(after)
    changed = {
        component_id
        for component_id in set(before_components) | set(after_components)
        if before_components.get(component_id) != after_components.get(component_id)
    }
    if any(before.get(field) != after.get(field) for field in ("schema_version", "ecosystem_release", "roots", "overview", "guides")):
        changed.update(before_components)
        changed.update(after_components)
    return changed


def run_lifecycle_script(
    registry_path: Path,
    event: str,
    arguments: list[str],
    changed_component_ids: list[str],
) -> int:
    component_id, script_name, required_command = LIFECYCLE_EVENT_ROUTES[event]
    if not arguments or arguments[0] != required_command:
        raise ValueError("LIFECYCLE_EVENT_ROUTE_MISMATCH")
    previous_registry_bytes = registry_path.read_bytes()
    before = load_registry(registry_path)
    changed = set(changed_component_ids) | {component_id}
    preflight_findings = audit_components(before, sorted(changed))
    if preflight_findings:
        print(json.dumps([asdict(item) for item in preflight_findings], ensure_ascii=False, indent=2))
        return 2
    try:
        result = run_component_script(registry_path, component_id, script_name, arguments)
        if result != 0:
            _restore_registry(registry_path, previous_registry_bytes)
            return result
        changed.update(_changed_registry_components(before, load_registry(registry_path)))
        return after_lifecycle_event(
            registry_path,
            sorted(changed),
            previous_registry_bytes,
        )
    except Exception:
        _restore_registry(registry_path, previous_registry_bytes)
        raise


def _active_registry_sha256(data: dict[str, object]) -> str:
    active = [{field: item.get(field) for field in LOCK_COMPONENT_FIELDS} for item in sorted(_component_map(data).values(), key=lambda row: str(row["id"])) if item["status"] == "active"]
    payload = {"schema_version": data["schema_version"], "ecosystem_release": data["ecosystem_release"], "roots": data["roots"], "overview": data.get("overview"), "guides": data.get("guides"), "components": active}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_lock(registry_path: Path) -> dict[str, object]:
    data = load_registry(registry_path)
    findings = validate_registry(data)
    if findings:
        raise ValueError(findings[0].code)
    components: dict[str, object] = {}
    for component_id, item in sorted(_component_map(data).items()):
        if item["status"] == "active":
            canonical = resolve_component(registry_path, component_id)
            components[component_id] = {"version": item["version"], "interface_version": item["interface_version"], "root": item["root"], "relative_path": item["relative_path"], "content_sha256": _tree_sha256(canonical)}
    return {"schema_version": 1, "ecosystem_release": data["ecosystem_release"], "registry_sha256": _active_registry_sha256(data), "components": components}


def plan_migration(registry_path: Path, component_id: str, candidate: Path, target: Path, expected_sha256: str, target_mirrors: list[str]) -> MigrationPlan:
    data = load_registry(registry_path)
    component = _component_map(data)[component_id]
    if _tree_sha256(candidate) != expected_sha256:
        raise ValueError("SOURCE_HASH_DRIFT")
    candidate_root, candidate_relative = _root_and_relative(data, candidate, "derived")
    target_root, target_relative = _root_and_relative(data, target, "authority")
    if target.exists() and _tree_sha256(target) != expected_sha256:
        raise ValueError("TARGET_COLLISION")
    target_root_path = Path(str(data["roots"][target_root]["path"])).resolve()
    for mirror_relative in target_mirrors:
        mirror = (target_root_path / mirror_relative).resolve()
        if target_root_path not in mirror.parents:
            raise ValueError("MIRROR_OUTSIDE_ROOT")
    plan = MigrationPlan(component_id, candidate_root, candidate_relative, target_root, target_relative, list(target_mirrors), expected_sha256, str(component["root"]), str(component["relative_path"]))
    staging = {"root": candidate_root, "relative_path": candidate_relative, "sha256": expected_sha256}
    if component.get("staging_paths", []) and component["staging_paths"] != [staging]:
        raise ValueError("MULTIPLE_STAGING")
    component["staging_paths"] = [staging]
    findings = validate_registry(data)
    if findings:
        raise ValueError(findings[0].code)
    _write_registry(registry_path, data)
    return plan


def activate_migration(registry_path: Path, plan: MigrationPlan) -> None:
    data = load_registry(registry_path)
    component = _component_map(data)[plan.component_id]
    try:
        active_path = _declared_path(data, str(component["root"]), str(component["relative_path"]))
        previous_path = _declared_path(data, plan.previous_root, plan.previous_relative_path)
    except (KeyError, ValueError):
        raise ValueError("MIGRATION_PLAN_INVALID") from None
    if (
        (str(component["root"]), str(component["relative_path"]))
        != (plan.previous_root, plan.previous_relative_path)
        or active_path != previous_path
    ):
        raise ValueError("MIGRATION_PLAN_INVALID")
    try:
        candidate_root, candidate_relative = _root_and_relative(data, _declared_path(data, plan.candidate_root, plan.candidate_relative_path), "derived")
        target_root, target_relative = _root_and_relative(data, _declared_path(data, plan.target_root, plan.target_relative_path), "authority")
    except (KeyError, ValueError):
        raise ValueError("MIGRATION_PLAN_INVALID") from None
    if (candidate_root, candidate_relative, target_root, target_relative) != (plan.candidate_root, plan.candidate_relative_path, plan.target_root, plan.target_relative_path):
        raise ValueError("MIGRATION_PLAN_INVALID")
    trusted_mirrors: list[str] = []
    try:
        for mirror_relative in plan.target_mirrors:
            mirror_root, mirror_relative_path = _root_and_relative(
                data, _declared_path(data, plan.target_root, mirror_relative), "authority"
            )
            if mirror_root != plan.target_root or mirror_relative_path != mirror_relative:
                raise ValueError("MIRROR_PLAN_DRIFT")
            trusted_mirrors.append(mirror_relative)
    except (KeyError, ValueError):
        raise ValueError("MIGRATION_PLAN_INVALID") from None
    candidate = _declared_path(data, plan.candidate_root, plan.candidate_relative_path)
    if _tree_sha256(candidate) != plan.expected_sha256:
        raise ValueError("SOURCE_HASH_DRIFT")
    target = _declared_path(data, plan.target_root, plan.target_relative_path)
    staging = [{"root": plan.candidate_root, "relative_path": plan.candidate_relative_path, "sha256": plan.expected_sha256}]
    if component.get("staging_paths", []) != staging:
        raise ValueError("STAGING_PLAN_MISMATCH")
    staging_parent: Path | None = None
    try:
        if target.exists():
            if _tree_sha256(target) != plan.expected_sha256:
                raise ValueError("TARGET_COLLISION")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            staging_parent = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
            staged_target = staging_parent / "payload"
            shutil.copytree(candidate, staged_target)
            os.rename(staged_target, target)
        if _tree_sha256(target) != plan.expected_sha256:
            raise ValueError("TARGET_HASH_DRIFT")
        component.update({"previous_path": {"root": plan.previous_root, "relative_path": plan.previous_relative_path}, "root": plan.target_root, "relative_path": plan.target_relative_path, "mirrors": trusted_mirrors, "staging_paths": []})
        findings = validate_registry(data)
        if findings:
            raise ValueError(findings[0].code)
        _write_registry(registry_path, data)
    finally:
        if staging_parent is not None and staging_parent.exists():
            shutil.rmtree(staging_parent)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path(__file__).resolve().parents[1] / "ecosystem-registry.json")
    sub = parser.add_subparsers(dest="command", required=True)
    resolve_parser = sub.add_parser("resolve"); resolve_parser.add_argument("component_id")
    audit_parser = sub.add_parser("audit"); audit_parser.add_argument("--json", action="store_true"); audit_parser.add_argument("--components", nargs="*")
    sub.add_parser("sync-overview")
    guides_parser = sub.add_parser("sync-guides"); guides_parser.add_argument("components", nargs="*")
    lock_parser = sub.add_parser("build-lock"); lock_parser.add_argument("--output", type=Path, required=True)
    run_parser = sub.add_parser("run"); run_parser.add_argument("component_id"); run_parser.add_argument("script_name"); run_parser.add_argument("arguments", nargs=argparse.REMAINDER)
    lifecycle_parser = sub.add_parser("run-lifecycle"); lifecycle_parser.add_argument("--event", required=True, choices=tuple(LIFECYCLE_EVENT_ROUTES)); lifecycle_parser.add_argument("--changed-component", action="append", default=[]); lifecycle_parser.add_argument("arguments", nargs=argparse.REMAINDER)
    register_parser = sub.add_parser("register-component"); register_parser.add_argument("--record", type=Path, required=True)
    plan_parser = sub.add_parser("plan-migration"); plan_parser.add_argument("--component", required=True); plan_parser.add_argument("--candidate", type=Path, required=True); plan_parser.add_argument("--target", type=Path, required=True); plan_parser.add_argument("--sha256", required=True); plan_parser.add_argument("--target-mirror", action="append", default=[]); plan_parser.add_argument("--output", type=Path, required=True)
    activate_parser = sub.add_parser("activate-migration"); activate_parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "resolve": print(resolve_component(args.registry, args.component_id)); return 0
    if args.command == "audit":
        data = load_registry(args.registry); findings = audit_components(data, args.components) if args.components else validate_registry(data)
        overview_config = data.get("overview")
        if isinstance(overview_config, dict) and overview_config.get("enabled") is True:
            findings.extend(
                Finding(item.code, item.component_id, item.message)
                for item in audit_overview(args.registry, args.components)
            )
        guides_config = data.get("guides")
        if isinstance(guides_config, dict) and guides_config.get("enabled") is True:
            findings.extend(
                Finding(item.code, item.component_id, item.message)
                for item in audit_guides(args.registry, args.components)
            )
        print(json.dumps([item.__dict__ for item in findings], ensure_ascii=False, indent=2) if args.json else "\n".join(item.code for item in findings)); return 0 if not findings else 2
    if args.command == "sync-overview":
        print(json.dumps(sync_overview(args.registry), ensure_ascii=False, indent=2))
        return 0
    if args.command == "sync-guides":
        selected = list(args.components) or None
        print(json.dumps(sync_guides(args.registry, selected), ensure_ascii=False, indent=2))
        return 0
    if args.command == "run":
        return run_component_script(args.registry, args.component_id, args.script_name, list(args.arguments))
    if args.command == "run-lifecycle":
        arguments = list(args.arguments)
        if arguments[:1] == ["--"]:
            arguments = arguments[1:]
        return run_lifecycle_script(
            args.registry,
            args.event,
            arguments,
            list(args.changed_component),
        )
    if args.command == "register-component":
        previous_registry_bytes = args.registry.read_bytes()
        try:
            component_id = register_component(args.registry, args.record)
            return after_lifecycle_event(args.registry, [component_id], previous_registry_bytes)
        except Exception:
            _restore_registry(args.registry, previous_registry_bytes)
            raise
    if args.command == "plan-migration":
        if args.output.exists():
            raise FileExistsError(args.output)
        previous_registry_bytes = args.registry.read_bytes()
        created_output = False
        try:
            plan = plan_migration(
                args.registry,
                args.component,
                args.candidate,
                args.target,
                args.sha256,
                list(args.target_mirror),
            )
            payload = (json.dumps(asdict(plan), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            _write_new_file_atomic(args.output, payload)
            created_output = True
            result = after_lifecycle_event(args.registry, [plan.component_id], previous_registry_bytes)
            if result != 0:
                args.output.unlink(missing_ok=True)
            return result
        except Exception:
            _restore_registry(args.registry, previous_registry_bytes)
            if created_output:
                args.output.unlink(missing_ok=True)
            raise
    if args.command == "activate-migration":
        previous_registry_bytes = args.registry.read_bytes()
        try:
            plan = MigrationPlan(**json.loads(args.plan.read_text(encoding="utf-8")))
            activate_migration(args.registry, plan)
            return after_lifecycle_event(args.registry, [plan.component_id], previous_registry_bytes)
        except Exception:
            _restore_registry(args.registry, previous_registry_bytes)
            raise
    lock = build_lock(args.registry)
    payload = (json.dumps(lock, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _write_file_atomic(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
