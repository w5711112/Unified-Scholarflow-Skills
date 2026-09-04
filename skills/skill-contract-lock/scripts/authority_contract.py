from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 3
GATE_IDS = tuple(f"G{index}" for index in range(6))
PHASE_GATES = {
    "work": (),
    "pre_artifact": ("G0", "G1", "G2", "G3"),
    "delivery": GATE_IDS,
}
EVIDENCE_KINDS = {
    "automated_check",
    "artifact_inspection",
    "user_decision",
    "negative_branch",
}
APPLICABILITY_STATES = {"applicable", "not_applicable", "pending"}


@dataclass(frozen=True)
class ValidationError:
    code: str
    message: str


def _error(code: str, message: str) -> ValidationError:
    return ValidationError(code, message)


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def text_sha256(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _resolved(value: Any, task_root: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    try:
        return path.resolve() if path.is_absolute() else (task_root / path).resolve()
    except OSError:
        return None


def _contains(root: Path, target: Path) -> bool:
    return target == root or root in target.parents


def _normalized(value: Path | str) -> str:
    return str(value).replace("\\", "/").casefold()


def _anchored_text(path: Path, start_line: int, end_line: int) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        raise ValueError("anchor is outside source")
    return "\n".join(lines[start_line - 1 : end_line])


def _task_root(data: dict[str, Any]) -> Path | None:
    task = data.get("task")
    if not isinstance(task, dict):
        return None
    value = task.get("task_root")
    if not isinstance(value, str) or not Path(value).is_absolute():
        return None
    try:
        return Path(value).resolve()
    except OSError:
        return None


def _authorized_roots(data: dict[str, Any], task_root: Path) -> tuple[list[Path], list[ValidationError]]:
    errors: list[ValidationError] = []
    scope = data.get("scope")
    if not isinstance(scope, dict):
        return [], [_error("SCOPE_INVALID", "scope must be an object")]
    raw_roots = scope.get("authorized_roots")
    if not isinstance(raw_roots, list) or not raw_roots:
        return [], [_error("SCOPE_INVALID", "authorized_roots must be non-empty")]
    roots: list[Path] = []
    for index, item in enumerate(raw_roots):
        declared_kind: str | None = None
        raw_path: Any = item
        if isinstance(item, dict):
            raw_path = item.get("path")
            declared_kind = item.get("kind")
            if declared_kind not in {"file", "directory"}:
                errors.append(_error("SCOPE_INVALID", f"root {index} has invalid kind"))
                continue
        path = _resolved(raw_path, task_root)
        if path is None or not path.is_absolute():
            errors.append(_error("SCOPE_INVALID", f"root {index} is invalid"))
            continue
        if path.exists() and declared_kind == "file" and not path.is_file():
            errors.append(_error("SCOPE_KIND_MISMATCH", f"root {path} is not a file"))
        if path.exists() and declared_kind == "directory" and not path.is_dir():
            errors.append(_error("SCOPE_KIND_MISMATCH", f"root {path} is not a directory"))
        roots.append(path)
    return roots, errors


def _exclusions(data: dict[str, Any]) -> tuple[list[str], list[ValidationError]]:
    scope = data.get("scope")
    raw = scope.get("exclusions") if isinstance(scope, dict) else None
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        return [], [_error("SCOPE_INVALID", "exclusions must be a string list")]
    return [_normalized(item) for item in raw], []


def _path_allowed(path: Path, roots: Iterable[Path], exclusions: Iterable[str]) -> bool:
    rendered = _normalized(path)
    if any(item and item in rendered for item in exclusions):
        return False
    for root in roots:
        if root.exists() and root.is_file():
            if path == root:
                return True
        elif _contains(root, path):
            return True
    return False


def _all_referenced_paths(data: dict[str, Any], task_root: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for item in data.get("observed_paths", []):
        path = _resolved(item, task_root)
        if path is not None:
            found.append(("observed", path))
    for source in data.get("sources", []):
        if isinstance(source, dict):
            path = _resolved(source.get("path"), task_root)
            if path is not None:
                found.append(("source", path))
    evidence_fields = (
        "target_path",
        "record_path",
        "fact_record_path",
        "inspection_record_path",
    )
    for receipt in data.get("evidence", []):
        if not isinstance(receipt, dict):
            continue
        for field in evidence_fields:
            if field in receipt:
                path = _resolved(receipt.get(field), task_root)
                if path is not None:
                    found.append((field, path))
    audit = data.get("forward_audit")
    if isinstance(audit, dict):
        path = _resolved(audit.get("record_path"), task_root)
        if path is not None:
            found.append(("forward_audit", path))
    return found


def _validate_scope(
    data: dict[str, Any],
    contract_path: Path,
    task_root: Path,
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    expected = (task_root / ".skill-contract" / "contract.json").resolve()
    if contract_path.resolve() != expected:
        errors.append(_error("TASK_ROOT_MISMATCH", "contract is not inside declared task root"))
    roots, root_errors = _authorized_roots(data, task_root)
    exclusions, exclusion_errors = _exclusions(data)
    errors.extend(root_errors)
    errors.extend(exclusion_errors)
    if root_errors or exclusion_errors:
        return errors
    observed = data.get("observed_paths")
    if not isinstance(observed, list) or any(not isinstance(item, str) for item in observed):
        errors.append(_error("OBSERVED_PATHS_INVALID", "observed_paths must be a string list"))
        return errors
    for label, path in _all_referenced_paths(data, task_root):
        if not _path_allowed(path, roots, exclusions):
            errors.append(_error("PATH_OUT_OF_SCOPE", f"{label} path is out of scope: {path}"))
    return errors


def _validate_sources(data: dict[str, Any], task_root: Path) -> tuple[dict[str, dict[str, Any]], list[ValidationError]]:
    errors: list[ValidationError] = []
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        return {}, [_error("SOURCES_INVALID", "sources must be non-empty")]
    sources: dict[str, dict[str, Any]] = {}
    for index, source in enumerate(raw_sources):
        if not isinstance(source, dict):
            errors.append(_error("SOURCE_INVALID", f"source {index} must be an object"))
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id or source_id in sources:
            errors.append(_error("SOURCE_INVALID", f"source {index} has invalid id"))
            continue
        sources[source_id] = source
        if source.get("read_complete") is not True:
            errors.append(_error("SOURCE_UNREAD", f"source {source_id} was not read completely"))
        path = _resolved(source.get("path"), task_root)
        expected_hash = source.get("sha256")
        if path is None or not path.is_file():
            errors.append(_error("SOURCE_MISSING", f"source {source_id} is missing"))
        elif not _is_sha256(expected_hash) or file_sha256(path) != expected_hash.casefold():
            errors.append(_error("SOURCE_HASH_MISMATCH", f"source {source_id} hash changed"))
        references = source.get("mandatory_reference_ids")
        if not isinstance(references, list) or any(not isinstance(item, str) for item in references):
            errors.append(_error("SOURCE_REFERENCES_INVALID", f"source {source_id} references are invalid"))
    for source_id, source in sources.items():
        for reference_id in source.get("mandatory_reference_ids", []):
            if reference_id not in sources:
                errors.append(_error("SOURCE_REFERENCE_MISSING", f"source {source_id} misses {reference_id}"))
    return sources, errors


def _validate_requirements(
    data: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    task_root: Path,
) -> tuple[dict[str, dict[str, Any]], list[ValidationError]]:
    errors: list[ValidationError] = []
    raw_requirements = data.get("requirements")
    if not isinstance(raw_requirements, list) or not raw_requirements:
        return {}, [_error("REQUIREMENTS_INVALID", "requirements must be non-empty")]
    requirements: dict[str, dict[str, Any]] = {}
    for index, requirement in enumerate(raw_requirements):
        if not isinstance(requirement, dict):
            errors.append(_error("REQUIREMENT_INVALID", f"requirement {index} must be an object"))
            continue
        requirement_id = requirement.get("id")
        source_id = requirement.get("source_id")
        if not isinstance(requirement_id, str) or not requirement_id or requirement_id in requirements:
            errors.append(_error("REQUIREMENT_INVALID", f"requirement {index} has invalid id"))
            continue
        requirements[requirement_id] = requirement
        source = sources.get(source_id)
        if source is None:
            errors.append(_error("REQUIREMENT_SOURCE_UNKNOWN", f"requirement {requirement_id} source is unknown"))
            continue
        anchor = requirement.get("anchor")
        if not isinstance(anchor, dict):
            errors.append(_error("REQUIREMENT_ANCHOR_INVALID", f"requirement {requirement_id} lacks anchor"))
        else:
            start = anchor.get("start_line")
            end = anchor.get("end_line")
            source_text = anchor.get("source_text")
            anchor_hash = anchor.get("sha256")
            source_path = _resolved(source.get("path"), task_root)
            try:
                actual = _anchored_text(source_path, start, end) if (
                    source_path is not None
                    and isinstance(start, int)
                    and not isinstance(start, bool)
                    and isinstance(end, int)
                    and not isinstance(end, bool)
                    and source_path.is_file()
                ) else None
            except (OSError, UnicodeError, ValueError):
                actual = None
            if (
                actual is None
                or not isinstance(source_text, str)
                or actual != source_text
                or not _is_sha256(anchor_hash)
                or text_sha256(actual) != anchor_hash.casefold()
            ):
                errors.append(_error("REQUIREMENT_ANCHOR_INVALID", f"requirement {requirement_id} anchor changed"))
        if requirement.get("applicability") not in APPLICABILITY_STATES:
            errors.append(_error("APPLICABILITY_INVALID", f"requirement {requirement_id} applicability is invalid"))
        if not isinstance(requirement.get("stage"), str) or not requirement.get("stage"):
            errors.append(_error("REQUIREMENT_STAGE_INVALID", f"requirement {requirement_id} stage is invalid"))
        dependencies = requirement.get("dependencies")
        evidence_ids = requirement.get("evidence_ids")
        if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
            errors.append(_error("DEPENDENCIES_INVALID", f"requirement {requirement_id} dependencies are invalid"))
        if not isinstance(evidence_ids, list) or any(not isinstance(item, str) for item in evidence_ids):
            errors.append(_error("EVIDENCE_IDS_INVALID", f"requirement {requirement_id} evidence ids are invalid"))
    for requirement_id, requirement in requirements.items():
        for dependency in requirement.get("dependencies", []):
            if dependency not in requirements or dependency == requirement_id:
                errors.append(_error("DEPENDENCY_UNKNOWN", f"requirement {requirement_id} dependency is invalid"))
    return requirements, errors


def _check_file_hash(
    path_value: Any,
    hash_value: Any,
    task_root: Path,
    missing_code: str,
    stale_code: str,
) -> tuple[Path | None, list[ValidationError]]:
    path = _resolved(path_value, task_root)
    if path is None or not path.is_file():
        return path, [_error(missing_code, f"file is missing: {path_value}")]
    if not _is_sha256(hash_value) or file_sha256(path) != hash_value.casefold():
        return path, [_error(stale_code, f"file hash changed: {path}")]
    return path, []


def _validate_evidence(
    data: dict[str, Any],
    requirements: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    task_root: Path,
) -> tuple[dict[str, dict[str, Any]], set[str], list[ValidationError]]:
    errors: list[ValidationError] = []
    stale_ids: set[str] = set()
    raw_evidence = data.get("evidence")
    if not isinstance(raw_evidence, list):
        return {}, set(), [_error("EVIDENCE_INVALID", "evidence must be a list")]
    evidence: dict[str, dict[str, Any]] = {}
    for index, receipt in enumerate(raw_evidence):
        if not isinstance(receipt, dict):
            errors.append(_error("EVIDENCE_INVALID", f"evidence {index} must be an object"))
            continue
        evidence_id = receipt.get("id")
        requirement_id = receipt.get("requirement_id")
        if not isinstance(evidence_id, str) or not evidence_id or evidence_id in evidence:
            errors.append(_error("EVIDENCE_INVALID", f"evidence {index} has invalid id"))
            continue
        evidence[evidence_id] = receipt
        requirement = requirements.get(requirement_id)
        if requirement is None:
            errors.append(_error("EVIDENCE_REQUIREMENT_UNKNOWN", f"evidence {evidence_id} requirement is unknown"))
            stale_ids.add(evidence_id)
            continue
        if receipt.get("kind") not in EVIDENCE_KINDS:
            errors.append(_error("EVIDENCE_KIND_INVALID", f"evidence {evidence_id} kind is invalid"))
            stale_ids.add(evidence_id)
        if receipt.get("result") != "pass":
            errors.append(_error("EVIDENCE_FAILED", f"evidence {evidence_id} did not pass"))
            stale_ids.add(evidence_id)
        source = sources.get(requirement.get("source_id"))
        source_hash = source.get("sha256") if source else None
        if receipt.get("source_sha256") != source_hash:
            errors.append(_error("EVIDENCE_SOURCE_STALE", f"evidence {evidence_id} source is stale"))
            stale_ids.add(evidence_id)
        _, target_errors = _check_file_hash(
            receipt.get("target_path"),
            receipt.get("target_sha256"),
            task_root,
            "EVIDENCE_TARGET_MISSING",
            "EVIDENCE_TARGET_STALE",
        )
        _, record_errors = _check_file_hash(
            receipt.get("record_path"),
            receipt.get("record_sha256"),
            task_root,
            "EVIDENCE_RECORD_MISSING",
            "EVIDENCE_RECORD_STALE",
        )
        errors.extend(target_errors)
        errors.extend(record_errors)
        if target_errors or record_errors:
            stale_ids.add(evidence_id)
        if receipt.get("kind") == "negative_branch":
            _, fact_errors = _check_file_hash(
                receipt.get("fact_record_path"),
                receipt.get("fact_record_sha256"),
                task_root,
                "NEGATIVE_BRANCH_EVIDENCE_REQUIRED",
                "NEGATIVE_BRANCH_EVIDENCE_STALE",
            )
            _, inspection_errors = _check_file_hash(
                receipt.get("inspection_record_path"),
                receipt.get("inspection_record_sha256"),
                task_root,
                "NEGATIVE_BRANCH_EVIDENCE_REQUIRED",
                "NEGATIVE_BRANCH_EVIDENCE_STALE",
            )
            errors.extend(fact_errors)
            errors.extend(inspection_errors)
            if fact_errors or inspection_errors:
                stale_ids.add(evidence_id)
    for requirement_id, requirement in requirements.items():
        for evidence_id in requirement.get("evidence_ids", []):
            receipt = evidence.get(evidence_id)
            if receipt is None or receipt.get("requirement_id") != requirement_id:
                errors.append(_error("EVIDENCE_MISSING", f"requirement {requirement_id} evidence is missing"))
                stale_ids.add(evidence_id)
    return evidence, stale_ids, errors


def derive_requirement_state(
    requirement: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    stale_ids: set[str],
) -> str:
    applicability = requirement.get("applicability")
    if applicability == "pending":
        return "pending"
    evidence_ids = requirement.get("evidence_ids", [])
    current = [
        evidence[item]
        for item in evidence_ids
        if item in evidence and item not in stale_ids
    ]
    if applicability == "not_applicable":
        return "verified" if any(item.get("kind") == "negative_branch" for item in current) else "pending"
    applicable_receipts = [
        item for item in current if item.get("kind") != "negative_branch"
    ]
    return (
        "verified"
        if applicable_receipts and len(applicable_receipts) == len(evidence_ids)
        else "pending"
    )


def _derive_requirement_states(
    requirements: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
    stale_ids: set[str],
) -> dict[str, str]:
    base = {
        requirement_id: derive_requirement_state(requirement, evidence, stale_ids)
        for requirement_id, requirement in requirements.items()
    }
    resolved: dict[str, str] = {}

    def resolve(requirement_id: str, visiting: set[str]) -> str:
        if requirement_id in resolved:
            return resolved[requirement_id]
        if base.get(requirement_id) != "verified" or requirement_id in visiting:
            return "pending"
        dependencies = requirements[requirement_id].get("dependencies", [])
        state = (
            "verified"
            if all(resolve(item, visiting | {requirement_id}) == "verified" for item in dependencies)
            else "pending"
        )
        resolved[requirement_id] = state
        return state

    return {requirement_id: resolve(requirement_id, set()) for requirement_id in requirements}


def derive_gate_state(
    gate: dict[str, Any],
    requirement_states: dict[str, str],
) -> str:
    states = [requirement_states[item] for item in gate.get("requirement_ids", [])]
    return "verified" if all(state == "verified" for state in states) else "pending"


def _validate_gates(
    data: dict[str, Any],
    requirements: dict[str, dict[str, Any]],
    requirement_states: dict[str, str],
    phase: str,
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    gates = data.get("gates")
    if not isinstance(gates, list) or len(gates) != len(GATE_IDS):
        return [_error("GATES_INVALID", "gates must contain G0 through G5")]
    ids = [gate.get("id") if isinstance(gate, dict) else None for gate in gates]
    if tuple(ids) != GATE_IDS:
        errors.append(_error("GATES_INVALID", "gates must be ordered G0 through G5"))
        return errors
    seen: list[str] = []
    gate_states: dict[str, str] = {}
    for gate in gates:
        requirement_ids = gate.get("requirement_ids")
        if not isinstance(requirement_ids, list) or any(not isinstance(item, str) for item in requirement_ids):
            errors.append(_error("GATE_REQUIREMENTS_INVALID", f"gate {gate['id']} requirements are invalid"))
            continue
        for requirement_id in requirement_ids:
            if requirement_id not in requirements:
                errors.append(_error("GATE_REQUIREMENT_UNKNOWN", f"gate {gate['id']} references unknown requirement"))
        seen.extend(requirement_ids)
        if all(item in requirement_states for item in requirement_ids):
            gate_states[gate["id"]] = derive_gate_state(gate, requirement_states)
    if sorted(seen) != sorted(requirements) or len(seen) != len(set(seen)):
        errors.append(_error("GATE_REQUIREMENT_COVERAGE", "each requirement must appear in exactly one gate"))
    for gate_id in PHASE_GATES[phase]:
        if gate_states.get(gate_id) != "verified":
            errors.append(_error("GATE_PENDING", f"gate {gate_id} is not verified"))
    return errors


def _validate_forward_audit(
    data: dict[str, Any],
    sources: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
    task_root: Path,
) -> list[ValidationError]:
    audit = data.get("forward_audit")
    if not isinstance(audit, dict) or audit.get("result") != "pass":
        return [_error("FORWARD_AUDIT_REQUIRED", "delivery requires a passing forward audit")]
    errors: list[ValidationError] = []
    _, record_errors = _check_file_hash(
        audit.get("record_path"),
        audit.get("record_sha256"),
        task_root,
        "FORWARD_AUDIT_REQUIRED",
        "FORWARD_AUDIT_STALE",
    )
    errors.extend(record_errors)
    source_map = audit.get("source_sha256")
    expected_sources = {source_id: item.get("sha256") for source_id, item in sources.items()}
    if source_map != expected_sources:
        errors.append(_error("FORWARD_AUDIT_STALE", "forward audit source snapshot is stale"))
    artifact_map = audit.get("artifact_sha256")
    expected_artifacts: dict[str, Any] = {}
    for item in evidence.values():
        target = _resolved(item.get("target_path"), task_root)
        if target is not None:
            expected_artifacts[str(target)] = item.get("target_sha256")
    if artifact_map != expected_artifacts:
        errors.append(_error("FORWARD_AUDIT_STALE", "forward audit artifact snapshot is stale"))
    return errors


def validate_contract(
    data: dict[str, Any],
    contract_path: Path,
    phase: str = "work",
) -> list[ValidationError]:
    if not isinstance(data, dict):
        return [_error("CONTRACT_INVALID", "contract must be an object")]
    if data.get("schema_version") != SCHEMA_VERSION:
        return [_error("SCHEMA_VERSION_UNSUPPORTED", f"schema_version must be {SCHEMA_VERSION}")]
    if data.get("contract_authority") != "record_only":
        return [_error("CONTRACT_AUTHORITY_INVALID", "contract must be record_only")]
    if phase not in PHASE_GATES:
        return [_error("PHASE_INVALID", "unknown validation phase")]
    task_root = _task_root(data)
    if task_root is None:
        return [_error("TASK_ROOT_INVALID", "task_root must be absolute")]

    errors = _validate_scope(data, contract_path, task_root)
    sources, source_errors = _validate_sources(data, task_root)
    errors.extend(source_errors)
    requirements, requirement_errors = _validate_requirements(data, sources, task_root)
    errors.extend(requirement_errors)
    evidence, stale_ids, evidence_errors = _validate_evidence(
        data,
        requirements,
        sources,
        task_root,
    )
    errors.extend(evidence_errors)
    requirement_states = _derive_requirement_states(requirements, evidence, stale_ids)
    errors.extend(_validate_gates(data, requirements, requirement_states, phase))
    for requirement_id, requirement in requirements.items():
        if (
            requirement.get("applicability") == "not_applicable"
            and requirement_states.get(requirement_id) != "verified"
        ):
            errors.append(
                _error(
                    "NEGATIVE_BRANCH_EVIDENCE_REQUIRED",
                    f"requirement {requirement_id} lacks negative-branch evidence",
                )
            )
    if phase == "delivery":
        errors.extend(_validate_forward_audit(data, sources, evidence, task_root))
    return errors


def _downstream_ids(
    requirements: list[dict[str, Any]],
    seeds: set[str],
) -> set[str]:
    children: dict[str, set[str]] = {}
    for requirement in requirements:
        requirement_id = requirement.get("id")
        if not isinstance(requirement_id, str):
            continue
        for dependency in requirement.get("dependencies", []):
            if isinstance(dependency, str):
                children.setdefault(dependency, set()).add(requirement_id)
    affected = set(seeds)
    stack = list(seeds)
    while stack:
        current = stack.pop()
        for child in children.get(current, set()):
            if child not in affected:
                affected.add(child)
                stack.append(child)
    return affected


def invalidate_contract(
    data: dict[str, Any],
    changed_paths: set[str],
) -> tuple[dict[str, Any], set[str]]:
    updated = deepcopy(data)
    task_root = _task_root(updated)
    if task_root is None:
        return updated, set()
    normalized_changes = {
        _normalized(path)
        for item in changed_paths
        if (path := _resolved(item, task_root)) is not None
    }
    direct: set[str] = set()
    source_to_requirements: dict[str, set[str]] = {}
    for requirement in updated.get("requirements", []):
        if isinstance(requirement, dict):
            source_to_requirements.setdefault(requirement.get("source_id"), set()).add(requirement.get("id"))
    for source in updated.get("sources", []):
        if not isinstance(source, dict) or not isinstance(source.get("path"), str):
            continue
        source_path = _resolved(source["path"], task_root)
        if source_path is not None and _normalized(source_path) in normalized_changes:
            direct.update(source_to_requirements.get(source.get("id"), set()))
    path_fields = (
        "target_path",
        "record_path",
        "fact_record_path",
        "inspection_record_path",
    )
    for receipt in updated.get("evidence", []):
        if not isinstance(receipt, dict):
            continue
        if any(
            isinstance(receipt.get(field), str)
            and (receipt_path := _resolved(receipt[field], task_root)) is not None
            and _normalized(receipt_path) in normalized_changes
            for field in path_fields
        ):
            direct.add(receipt.get("requirement_id"))
    affected = _downstream_ids(updated.get("requirements", []), direct)
    updated["evidence"] = [
        receipt
        for receipt in updated.get("evidence", [])
        if isinstance(receipt, dict) and receipt.get("requirement_id") not in affected
    ]
    for requirement in updated.get("requirements", []):
        if isinstance(requirement, dict) and requirement.get("id") in affected:
            requirement["evidence_ids"] = []
    updated["forward_audit"] = None
    return updated, affected
