from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from incident_registry import (
    ALLOWED_STATUSES,
    _contains_sensitive_key,
    _guard_failure,
    canonical_component,
    normalize_signature,
)
from problem_families import ClassificationResult, classify_problem, load_family_catalog


SCHEMA_VERSION = 3
FAMILY_ID_ALIASES = {
    "python.dependency.missing-module": "python.import.module-not-found",
    "apply-patch.context.anchor-mismatch": "apply-patch.context.expected-lines-not-found",
    "ripgrep.pattern.shell-quoting": "ripgrep.pattern.regex-parse",
}
REQUIRED_EVENT_FIELDS = {
    "event_id",
    "legacy_id",
    "component",
    "symptom_signature",
    "family_id",
    "classification_confidence",
    "candidate_family_ids",
    "solution_id",
    "root_cause",
    "diagnosis_evidence",
    "verification",
    "environment",
    "first_seen",
    "last_seen",
    "occurrences",
    "status",
    "source_scope",
    "owner_skill",
    "legacy_reuse_success_count",
    "legacy_reuse_failure_count",
    "legacy_fields",
}
SOLUTION_CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "references" / "solution-catalog.json"
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def registry_sha256(registry: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(registry)).hexdigest()


def _short_hash(*parts: str) -> str:
    raw = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def load_solution_catalog(path: Path = SOLUTION_CATALOG_PATH) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    solutions = data.get("solutions")
    if not isinstance(solutions, list):
        raise ValueError("solution catalog must contain solutions[]")
    return solutions


def merged_family_catalog(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Return authority families plus registry-local families for runtime classification."""
    catalog = load_family_catalog()
    known_ids = {str(item.get("family_id")) for item in catalog}
    catalog.extend(
        copy.deepcopy(item)
        for item in registry.get("problem_families", [])
        if str(item.get("family_id")) not in known_ids
    )
    return catalog


def materialize_solution_record(record: dict[str, Any]) -> dict[str, Any]:
    """Resolve a lightweight authority-catalog reference without copying its body."""
    if record.get("catalog_source") != "builtin":
        return copy.deepcopy(record)
    authority_fields = {
        "title",
        "steps",
        "applicability_guard",
        "forbidden_routes",
        "verification_contract",
        "migration_equivalence_any",
        "effect_contract",
        "quality_guard",
    }
    forbidden = sorted(authority_fields.intersection(record))
    if forbidden:
        raise ValueError(
            f"builtin solution reference contains authority fields: {forbidden}"
        )
    solution_id = str(record.get("solution_id") or "")
    canonical = next(
        (item for item in load_solution_catalog() if item.get("solution_id") == solution_id),
        None,
    )
    if canonical is None:
        raise ValueError(f"unknown builtin solution reference: {solution_id}")
    if record.get("family_id") != canonical.get("family_id"):
        raise ValueError(
            f"builtin solution reference family mismatch: {solution_id}"
        )
    return {**copy.deepcopy(canonical), **copy.deepcopy(record)}


def _builtin_solution_reference(
    solution: dict[str, Any], *, successes: int = 0, failures: int = 0,
    source_legacy_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "solution_id": solution["solution_id"],
        "family_id": solution["family_id"],
        "catalog_source": "builtin",
        "status": solution.get("status", "verified"),
        "owner_skill": solution.get("owner_skill", "global.collect-bug-update-accelerate"),
        "reuse_success_count": int(successes),
        "reuse_failure_count": int(failures),
        "source_legacy_ids": list(source_legacy_ids or []),
    }


def compact_builtin_solution_references(
    registry: dict[str, Any]
) -> tuple[dict[str, Any], int]:
    """Replace unchanged catalog snapshots with lightweight references."""
    if registry.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("solution compaction requires schema v3")
    if not all(
        isinstance(registry.get(key), list)
        for key in ("problem_families", "solutions", "events")
    ):
        raise ValueError("schema v3 arrays are missing")
    result = copy.deepcopy(registry)
    catalog = {str(item["solution_id"]): item for item in load_solution_catalog()}
    authoritative_keys = {
        "family_id",
        "title",
        "steps",
        "applicability_guard",
        "forbidden_routes",
        "verification_contract",
        "migration_equivalence_any",
        "effect_contract",
        "quality_guard",
        "owner_skill",
    }
    changed = 0
    for index, stored in enumerate(result["solutions"]):
        canonical = catalog.get(str(stored.get("solution_id") or ""))
        if canonical is None or stored.get("catalog_source") == "builtin":
            continue
        if any(
            stored.get(key) != canonical.get(key)
            for key in authoritative_keys
            if key in stored
        ):
            if "catalog_source" not in stored:
                stored["catalog_source"] = "local"
            continue
        runtime_fields = {
            key: copy.deepcopy(value)
            for key, value in stored.items()
            if key
            not in authoritative_keys
            | {
                "solution_id",
                "family_id",
                "catalog_source",
            }
        }
        result["solutions"][index] = {
            **_builtin_solution_reference(
                canonical,
                successes=int(stored.get("reuse_success_count", 0)),
                failures=int(stored.get("reuse_failure_count", 0)),
                source_legacy_ids=list(stored.get("source_legacy_ids", [])),
            ),
            **runtime_fields,
        }
        changed += 1
    validate_v3(result)
    return result, changed


def refresh_authority_catalog(
    registry: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, int]]:
    """Apply declared authority-family renames without changing event evidence."""
    if registry.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("catalog refresh requires schema v3")
    if not all(
        isinstance(registry.get(key), list)
        for key in ("problem_families", "solutions", "events")
    ):
        raise ValueError("schema v3 arrays are missing")
    result = copy.deepcopy(registry)
    authority = {str(item["family_id"]): item for item in load_family_catalog()}
    changed_families = 0
    changed_events = 0
    changed_solutions = 0
    for old_id, new_id in FAMILY_ID_ALIASES.items():
        old_family = next(
            (item for item in result["problem_families"] if item.get("family_id") == old_id),
            None,
        )
        if old_family is not None:
            canonical = copy.deepcopy(authority[new_id])
            existing_new = next(
                (item for item in result["problem_families"] if item.get("family_id") == new_id),
                None,
            )
            combined_solution_ids = sorted(
                set(canonical.get("solution_ids", []))
                | set(old_family.get("solution_ids", []))
                | set((existing_new or {}).get("solution_ids", []))
            )
            canonical["solution_ids"] = combined_solution_ids
            result["problem_families"] = [
                item
                for item in result["problem_families"]
                if item.get("family_id") not in {old_id, new_id}
            ]
            result["problem_families"].append(canonical)
            changed_families += 1
        for event in result["events"]:
            event_changed = False
            if event.get("family_id") == old_id:
                event["family_id"] = new_id
                event_changed = True
            candidates = event.get("candidate_family_ids", [])
            if old_id in candidates:
                event["candidate_family_ids"] = sorted(
                    {new_id if item == old_id else item for item in candidates}
                )
                event_changed = True
            if event_changed:
                changed_events += 1
        for solution in result["solutions"]:
            if solution.get("family_id") == old_id:
                solution["family_id"] = new_id
                changed_solutions += 1
    result["problem_families"].sort(key=lambda item: str(item["family_id"]))
    total = changed_families + changed_events + changed_solutions
    if total:
        result["updated_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    validate_v3(result)
    return result, {
        "families": changed_families,
        "events": changed_events,
        "solutions": changed_solutions,
        "total": total,
    }


@dataclass(frozen=True)
class MigrationPlan:
    source_sha256: str
    legacy_id_map: dict[str, str]
    registry: dict[str, Any]
    unclassified_legacy_ids: tuple[str, ...]
    conflicts: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_sha256": self.source_sha256,
            "legacy_id_map": dict(self.legacy_id_map),
            "unclassified_legacy_ids": list(self.unclassified_legacy_ids),
            "conflicts": list(self.conflicts),
            "summary": {
                "events": len(self.registry["events"]),
                "problem_families": len(self.registry["problem_families"]),
                "solutions": len(self.registry["solutions"]),
                "unclassified": len(self.unclassified_legacy_ids),
            },
        }


@dataclass(frozen=True)
class ConservationReport:
    ok: bool
    mismatches: dict[str, dict[str, int]]
    source_counts: dict[str, int]
    target_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mismatches": self.mismatches,
            "source_counts": self.source_counts,
            "target_counts": self.target_counts,
        }


def _unclassified_id(component: str, symptom: str) -> str:
    canonical = canonical_component(component) or "unknown"
    return f"unclassified.{canonical}.{_short_hash(canonical, normalize_signature(symptom))}"


def _event_from_incident(
    incident: dict[str, Any], classification: ClassificationResult
) -> dict[str, Any]:
    legacy_id = str(incident["id"])
    component = canonical_component(str(incident.get("component") or ""))
    symptom = str(incident.get("symptom_signature") or "")
    family_id = classification.family_id or _unclassified_id(component, symptom)
    event_id = f"event.{_short_hash(legacy_id, family_id)}"
    return {
        "event_id": event_id,
        "legacy_id": legacy_id,
        "component": component,
        "symptom_signature": symptom,
        "family_id": family_id,
        "classification_confidence": classification.confidence,
        "candidate_family_ids": list(classification.candidate_family_ids),
        "solution_id": None,
        "root_cause": incident.get("root_cause", "unconfirmed"),
        "diagnosis_evidence": incident.get("diagnosis_evidence", ""),
        "verification": incident.get("verification", "not-yet-verified"),
        "environment": copy.deepcopy(incident.get("environment") or {}),
        "first_seen": incident.get("first_seen"),
        "last_seen": incident.get("last_seen"),
        "occurrences": int(incident.get("occurrences", 1)),
        "status": incident.get("status", "observed"),
        "source_scope": incident.get("source_scope", "current-task"),
        "owner_skill": incident.get("owner_skill", "collect-bug-update-accelerate"),
        "legacy_reuse_success_count": int(incident.get("reuse_success_count", 0)),
        "legacy_reuse_failure_count": int(incident.get("reuse_failure_count", 0)),
        "legacy_fields": {
            key: copy.deepcopy(value)
            for key, value in incident.items()
            if key
            not in {
                "id",
                "component",
                "symptom_signature",
                "root_cause",
                "diagnosis_evidence",
                "verification",
                "environment",
                "first_seen",
                "last_seen",
                "occurrences",
                "status",
                "source_scope",
                "owner_skill",
                "reuse_success_count",
                "reuse_failure_count",
            }
        },
    }


def plan_v3_migration(
    v2_registry: dict[str, Any], family_catalog: list[dict[str, Any]]
) -> MigrationPlan:
    if v2_registry.get("schema_version") != 2:
        raise ValueError("migration requires a schema v2 registry")
    incidents = v2_registry.get("incidents")
    if not isinstance(incidents, list):
        raise ValueError("schema v2 registry must contain incidents[]")
    solutions_by_id = {
        str(item["solution_id"]): copy.deepcopy(item) for item in load_solution_catalog()
    }
    family_by_id = {str(item["family_id"]): copy.deepcopy(item) for item in family_catalog}
    used_families: set[str] = set()
    used_solutions: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    legacy_id_map: dict[str, str] = {}
    unclassified: list[str] = []
    conflicts: list[str] = []

    for incident in incidents:
        legacy_id = str(incident.get("id") or "")
        if not legacy_id or legacy_id in legacy_id_map:
            conflicts.append(f"duplicate-or-empty-legacy-id:{legacy_id}")
            continue
        classification = classify_problem(
            str(incident.get("component") or ""),
            str(incident.get("symptom_signature") or ""),
            {},
            incident.get("environment") or {},
            family_catalog,
        )
        event = _event_from_incident(incident, classification)
        legacy_id_map[legacy_id] = event["event_id"]
        if classification.family_id is None:
            unclassified.append(legacy_id)
            events.append(event)
            continue
        used_families.add(classification.family_id)
        family = family_by_id[classification.family_id]
        available = [sid for sid in family.get("solution_ids", []) if sid in solutions_by_id]
        solution_confirmed = str(incident.get("known_good_solution") or "").strip().lower() not in {
            "",
            "unconfirmed",
        }
        if len(available) == 1 and solution_confirmed and incident.get("status") in {"verified", "promoted"}:
            solution_id = available[0]
            solution_template = solutions_by_id[solution_id]
            normalized_legacy_solution = normalize_signature(
                str(incident.get("known_good_solution") or "")
            )
            equivalence_markers = [
                normalize_signature(str(item))
                for item in solution_template.get("migration_equivalence_any", [])
            ]
            equivalent = bool(equivalence_markers) and any(
                marker in normalized_legacy_solution for marker in equivalence_markers
            )
            if equivalent:
                event["solution_id"] = solution_id
                event["legacy_reuse_success_count"] = 0
                event["legacy_reuse_failure_count"] = 0
                solution = used_solutions.setdefault(
                    solution_id,
                    _builtin_solution_reference(solution_template),
                )
                solution["reuse_success_count"] += int(incident.get("reuse_success_count", 0))
                solution["reuse_failure_count"] += int(incident.get("reuse_failure_count", 0))
                solution["source_legacy_ids"].append(legacy_id)
        events.append(event)

    registry = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": v2_registry.get("updated_at"),
        "problem_families": [family_by_id[item] for item in sorted(used_families)],
        "solutions": [used_solutions[item] for item in sorted(used_solutions)],
        "events": events,
        "migration": {
            "from_schema_version": 2,
            "source_sha256": registry_sha256(v2_registry),
            "legacy_id_map": dict(legacy_id_map),
            "unclassified_legacy_ids": list(unclassified),
            "conflicts": list(conflicts),
        },
    }
    return MigrationPlan(
        source_sha256=registry_sha256(v2_registry),
        legacy_id_map=legacy_id_map,
        registry=registry,
        unclassified_legacy_ids=tuple(unclassified),
        conflicts=tuple(conflicts),
    )


def apply_v3_plan(v2_registry: dict[str, Any], plan: MigrationPlan) -> dict[str, Any]:
    if registry_sha256(v2_registry) != plan.source_sha256:
        raise ValueError("source hash changed after migration plan was created")
    if set(plan.legacy_id_map) != {str(item.get("id")) for item in v2_registry.get("incidents", [])}:
        raise ValueError("migration plan does not map every legacy incident id")
    migrated = copy.deepcopy(plan.registry)
    validate_v3(migrated)
    report = verify_conservation(v2_registry, migrated, plan)
    if not report.ok:
        raise ValueError(f"migration conservation failed: {report.mismatches}")
    return migrated


def _unique_ids(items: list[dict[str, Any]], key: str) -> set[str]:
    values = [str(item.get(key) or "") for item in items]
    if any(not value for value in values) or len(values) != len(set(values)):
        raise ValueError(f"{key} values must be non-empty and unique")
    return set(values)


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    )


def _validate_solution_contract(solution: dict[str, Any]) -> None:
    solution_id = solution.get("solution_id")
    if not _string_list(solution.get("steps")) or not solution.get("steps"):
        raise ValueError(f"solution steps must be a non-empty string array: {solution_id}")
    guard = solution.get("applicability_guard")
    if not isinstance(guard, dict):
        raise ValueError(f"solution applicability_guard must be an object: {solution_id}")
    unknown_guard_fields = set(guard) - {"os", "shell_contains", "environment_equals"}
    if unknown_guard_fields:
        raise ValueError(f"solution guard has unsupported fields: {sorted(unknown_guard_fields)}")
    for key in ("os", "shell_contains"):
        if key in guard and not _string_list(guard[key]):
            raise ValueError(f"solution guard {key} must be a non-empty string array: {solution_id}")
    if "environment_equals" in guard and not isinstance(guard["environment_equals"], dict):
        raise ValueError(f"solution guard environment_equals must be an object: {solution_id}")
    if not _string_list(solution.get("forbidden_routes", [])) and solution.get("forbidden_routes") != []:
        raise ValueError(f"solution forbidden_routes must be a string array: {solution_id}")
    if not str(solution.get("verification_contract", "")).strip():
        raise ValueError(f"solution verification_contract must be non-empty: {solution_id}")
    effect_contract = solution.get("effect_contract")
    if (
        not isinstance(effect_contract, dict)
        or not str(effect_contract.get("expected_effect", "")).strip()
        or not _string_list(effect_contract.get("forbidden_side_effects", []))
        and effect_contract.get("forbidden_side_effects") != []
        or not isinstance(effect_contract.get("domain_semantics"), bool)
    ):
        raise ValueError(f"solution has incomplete effect_contract: {solution_id}")
    if effect_contract.get("domain_semantics") is True and not str(
        solution.get("regression_test", "")
    ).strip():
        raise ValueError(
            f"domain-semantics solution requires a regression_test: {solution_id}"
        )
    quality_guard = solution.get("quality_guard")
    if quality_guard is not None:
        if (
            not isinstance(quality_guard, dict)
            or not str(quality_guard.get("preserve_output_fidelity", "")).strip()
            or (
                not _string_list(quality_guard.get("forbidden_downgrade_routes", []))
                and quality_guard.get("forbidden_downgrade_routes") != []
            )
        ):
            raise ValueError(f"solution has invalid quality_guard: {solution_id}")


def validate_v3(registry: dict[str, Any]) -> None:
    if registry.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("registry schema_version must be 3")
    sensitive_key = _contains_sensitive_key(registry)
    if sensitive_key:
        raise ValueError(f"sensitive field is forbidden: {sensitive_key}")
    if not isinstance(registry.get("updated_at"), str) or not registry["updated_at"].strip():
        raise ValueError("updated_at must be a non-empty string")
    families = registry.get("problem_families")
    solutions = registry.get("solutions")
    events = registry.get("events")
    if not all(isinstance(value, list) for value in (families, solutions, events)):
        raise ValueError("problem_families, solutions and events must be arrays")
    family_ids = _unique_ids(families, "family_id")
    solution_ids = _unique_ids(solutions, "solution_id")
    authority_families = {
        str(item["family_id"]): item for item in load_family_catalog()
    }
    authority_solutions = {
        str(item["solution_id"]): item for item in load_solution_catalog()
    }
    authority_identity_owner = {
        tuple(
            str(item.get(key) or "").strip()
            for key in ("component", "operation", "failure_phase", "error_class")
        ): str(item["family_id"])
        for item in authority_families.values()
    }
    family_identity_owner: dict[tuple[str, str, str, str], str] = {}
    for family in families:
        authority = authority_families.get(str(family.get("family_id") or ""))
        listed_solution_ids = family.get("solution_ids")
        if not isinstance(listed_solution_ids, list) or not all(
            isinstance(item, str) and item for item in listed_solution_ids
        ) or len(listed_solution_ids) != len(set(listed_solution_ids)):
            raise ValueError(f"problem family solution_ids must be unique strings: {family.get('family_id')}")
        if authority is not None and any(
            family.get(key) != authority.get(key)
            for key in ("component", "operation", "failure_phase", "error_class")
        ):
            raise ValueError(
                f"authority problem family identity mismatch: {family.get('family_id')}"
            )
        if authority is not None and not set(authority.get("solution_ids", [])).issubset(
            set(listed_solution_ids)
        ):
            raise ValueError(
                f"authority problem family solution ids were removed: {family.get('family_id')}"
            )
        identity = tuple(
            str(family.get(key) or "").strip()
            for key in ("component", "operation", "failure_phase", "error_class")
        )
        if not all(identity):
            raise ValueError(
                f"problem family identity fields must be non-empty: {family.get('family_id')}"
            )
        authority_owner = authority_identity_owner.get(identity)
        if authority_owner is not None and authority_owner != family.get("family_id"):
            raise ValueError(
                "problem family identity is reserved by authority family: "
                f"{authority_owner}"
            )
        previous_owner = family_identity_owner.get(identity)
        if previous_owner is not None:
            raise ValueError(
                "duplicate problem family identity: "
                f"{previous_owner} and {family.get('family_id')}"
            )
        family_identity_owner[identity] = str(family.get("family_id"))
    solution_family = {
        str(item["solution_id"]): str(item["family_id"]) for item in solutions
    }
    family_component = {
        str(item["family_id"]): str(item["component"]) for item in families
    }
    _unique_ids(events, "event_id")
    legacy_ids = [str(item.get("legacy_id") or "") for item in events]
    if any(not item for item in legacy_ids) or len(legacy_ids) != len(set(legacy_ids)):
        raise ValueError("legacy_id values must be non-empty and unique")
    for solution in solutions:
        if solution.get("catalog_source") not in {"builtin", "local"}:
            raise ValueError(
                f"invalid solution catalog_source: {solution.get('solution_id')}"
            )
        if solution.get("catalog_source") == "local" and not str(
            solution.get("title", "")
        ).strip():
            raise ValueError(
                f"local solution title must be non-empty: {solution.get('solution_id')}"
            )
        if (
            str(solution.get("solution_id") or "") in authority_solutions
            and solution.get("catalog_source") != "builtin"
        ):
            raise ValueError(
                f"authority solution id requires builtin reference: {solution.get('solution_id')}"
            )
        materialized = materialize_solution_record(solution)
        if solution.get("family_id") not in family_ids:
            raise ValueError(f"solution references unknown family: {solution.get('solution_id')}")
        owning_family = next(
            item for item in families if item.get("family_id") == solution.get("family_id")
        )
        if solution.get("solution_id") not in owning_family.get("solution_ids", []):
            raise ValueError(
                f"solution is missing from its problem family index: {solution.get('solution_id')}"
            )
        if solution.get("status") not in {"verified", "regressed", "retired"}:
            raise ValueError(f"invalid solution status: {solution.get('status')}")
        for key in ("reuse_success_count", "reuse_failure_count"):
            if int(solution.get(key, -1)) < 0:
                raise ValueError(f"{key} must be non-negative")
        for key in ("steps", "applicability_guard", "verification_contract", "effect_contract"):
            if key not in materialized:
                raise ValueError(f"solution missing {key}: {solution.get('solution_id')}")
        _validate_solution_contract(materialized)
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("every event must be an object")
        missing = REQUIRED_EVENT_FIELDS - set(event)
        if missing:
            raise ValueError(f"event missing fields: {sorted(missing)}")
        for key in (
            "event_id",
            "legacy_id",
            "component",
            "symptom_signature",
            "family_id",
            "classification_confidence",
            "root_cause",
            "verification",
            "first_seen",
            "last_seen",
            "source_scope",
            "owner_skill",
        ):
            if not isinstance(event.get(key), str) or not event[key].strip():
                raise ValueError(f"event field must be a non-empty string: {key}")
        if not isinstance(event.get("diagnosis_evidence"), str):
            raise ValueError("event diagnosis_evidence must be a string")
        if not isinstance(event.get("environment"), dict):
            raise ValueError("event environment must be an object")
        if not isinstance(event.get("candidate_family_ids"), list) or not all(
            isinstance(item, str) and item for item in event["candidate_family_ids"]
        ):
            raise ValueError("event candidate_family_ids must be a string array")
        if not isinstance(event.get("legacy_fields"), dict):
            raise ValueError("event legacy_fields must be an object")
        for key in ("occurrences", "legacy_reuse_success_count", "legacy_reuse_failure_count"):
            value = event.get(key)
            minimum = 1 if key == "occurrences" else 0
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                raise ValueError(f"event {key} must be an integer >= {minimum}")
        if event.get("classification_confidence") not in {
            "explicit",
            "structured-exact",
            "rule-exact",
            "candidate",
            "unclassified",
        }:
            raise ValueError(
                f"invalid classification confidence: {event.get('classification_confidence')}"
            )
        if event.get("source_scope") not in {
            "current-task",
            "same-project-history",
            "runtime-discovery",
        }:
            raise ValueError(f"invalid source_scope: {event.get('source_scope')}")
        family_id = str(event.get("family_id") or "")
        is_unclassified = family_id.startswith("unclassified.")
        if not is_unclassified and family_id not in family_ids:
            raise ValueError(f"event references unknown family: {event.get('event_id')}")
        if (
            not is_unclassified
            and canonical_component(str(event.get("component") or ""))
            != family_component[family_id]
        ):
            raise ValueError(
                f"event component does not match its problem family: {event.get('event_id')}"
            )
        if is_unclassified and event.get("solution_id") is not None:
            raise ValueError("unclassified events cannot reference a solution")
        if event.get("solution_id") is not None and event.get("solution_id") not in solution_ids:
            raise ValueError(f"event references unknown solution: {event.get('event_id')}")
        if (
            event.get("solution_id") is not None
            and solution_family[str(event["solution_id"])] != family_id
        ):
            raise ValueError("event references a solution from a different family")
        if event.get("status") not in ALLOWED_STATUSES:
            raise ValueError(f"invalid event status: {event.get('status')}")
        if int(event.get("occurrences", 0)) < 1:
            raise ValueError("event occurrences must be positive")


def _counts_v2(v2: dict[str, Any]) -> dict[str, int]:
    incidents = v2.get("incidents", [])
    return {
        "legacy_ids": len(incidents),
        "occurrences": sum(int(item.get("occurrences", 1)) for item in incidents),
        "reuse_success": sum(int(item.get("reuse_success_count", 0)) for item in incidents),
        "reuse_failure": sum(int(item.get("reuse_failure_count", 0)) for item in incidents),
    }


def _counts_v3(v3: dict[str, Any]) -> dict[str, int]:
    events = v3.get("events", [])
    solutions = v3.get("solutions", [])
    return {
        "legacy_ids": len({str(item.get("legacy_id")) for item in events}),
        "occurrences": sum(int(item.get("occurrences", 1)) for item in events),
        "reuse_success": sum(int(item.get("reuse_success_count", 0)) for item in solutions)
        + sum(int(item.get("legacy_reuse_success_count", 0)) for item in events),
        "reuse_failure": sum(int(item.get("reuse_failure_count", 0)) for item in solutions)
        + sum(int(item.get("legacy_reuse_failure_count", 0)) for item in events),
    }


def verify_conservation(
    v2_registry: dict[str, Any], v3_registry: dict[str, Any], plan: MigrationPlan
) -> ConservationReport:
    source = _counts_v2(v2_registry)
    target = _counts_v3(v3_registry)
    mismatches = {
        key: {"source": source[key], "target": target[key]}
        for key in source
        if source[key] != target[key]
    }
    if set(plan.legacy_id_map) != {str(item.get("legacy_id")) for item in v3_registry.get("events", [])}:
        mismatches["legacy_id_map"] = {
            "source": len(plan.legacy_id_map),
            "target": len(v3_registry.get("events", [])),
        }
    return ConservationReport(not mismatches and not plan.conflicts, mismatches, source, target)


def family_report(registry: dict[str, Any]) -> dict[str, Any]:
    validate_v3(registry)
    events = registry["events"]
    solutions = registry["solutions"]
    classified = [item for item in events if not item["family_id"].startswith("unclassified.")]
    reusable = [item for item in classified if item.get("solution_id")]
    solution_success = sum(int(item.get("reuse_success_count", 0)) for item in solutions)
    solution_failure = sum(int(item.get("reuse_failure_count", 0)) for item in solutions)
    legacy_success = sum(int(item.get("legacy_reuse_success_count", 0)) for item in events)
    legacy_failure = sum(int(item.get("legacy_reuse_failure_count", 0)) for item in events)
    return {
        "schema_version": 3,
        "events": len(events),
        "problem_families": len(registry["problem_families"]),
        "solutions": len(solutions),
        "unclassified": len(events) - len(classified),
        "reuse_coverage": (len(reusable) / len(events)) if events else 0.0,
        "reuse_success_count": solution_success + legacy_success,
        "reuse_failure_count": solution_failure + legacy_failure,
        "solution_attributed_reuse_success_count": solution_success,
        "solution_attributed_reuse_failure_count": solution_failure,
        "legacy_unattributed_reuse_success_count": legacy_success,
        "legacy_unattributed_reuse_failure_count": legacy_failure,
    }


def event_closure_report(
    registry: dict[str, Any], event_id: str
) -> dict[str, Any]:
    """Report whether one real failure is classified and effect-verified."""
    validate_v3(registry)
    event = next(
        (
            item
            for item in registry["events"]
            if item.get("event_id") == event_id or item.get("legacy_id") == event_id
        ),
        None,
    )
    if event is None:
        raise KeyError(f"event not found: {event_id}")
    reasons: list[str] = []
    family_id = str(event.get("family_id") or "")
    solution_id = event.get("solution_id")
    if family_id.startswith("unclassified."):
        reasons.append("unclassified-family")
    solution = next(
        (
            item
            for item in registry["solutions"]
            if item.get("solution_id") == solution_id
        ),
        None,
    )
    if not solution_id or solution is None:
        reasons.append("missing-solution")
    elif solution.get("status") != "verified":
        reasons.append("solution-not-verified")
    applicable = [
        item
        for item in registry["solutions"]
        if item.get("family_id") == family_id
        and item.get("status") == "verified"
        and _guard_failure(
            materialize_solution_record(item), event.get("environment") or {}
        )
        is None
    ]
    if not applicable:
        reasons.append("no-applicable-verified-solution")
    elif len(applicable) > 1:
        reasons.append("ambiguous-applicable-solutions")
    elif applicable[0].get("solution_id") != solution_id:
        reasons.append("bound-solution-not-applicable")
    if event.get("status") not in {"verified", "promoted"}:
        reasons.append("event-not-verified")
    if str(event.get("verification") or "").strip().lower() in {
        "",
        "not-yet-verified",
        "unconfirmed",
    }:
        reasons.append("missing-effect-verification")
    return {
        "closed": not reasons,
        "incident_id": event["event_id"],
        "family_id": family_id,
        "solution_id": solution_id,
        "reasons": reasons,
    }


def resolve_event_v3(
    registry: dict[str, Any],
    *,
    event_id: str,
    family_id: str,
    solution_id: str,
    family_title: str,
    operation: str,
    failure_phase: str,
    error_class: str,
    root_cause: str,
    diagnosis_evidence: str,
    solution_title: str,
    steps: list[str],
    applicability_guard: dict[str, Any],
    forbidden_routes: list[str],
    verification_contract: str,
    effect_contract: dict[str, Any],
    quality_guard: dict[str, Any] | None,
    regression_test: str | None = None,
    verification: str,
) -> dict[str, Any]:
    """Turn one observed v3 event into a reusable family/solution record."""
    validate_v3(registry)
    required_text = {
        "family_id": family_id,
        "solution_id": solution_id,
        "family_title": family_title,
        "operation": operation,
        "failure_phase": failure_phase,
        "error_class": error_class,
        "root_cause": root_cause,
        "diagnosis_evidence": diagnosis_evidence,
        "solution_title": solution_title,
        "verification_contract": verification_contract,
        "verification": verification,
    }
    missing = sorted(key for key, value in required_text.items() if not str(value).strip())
    if missing:
        raise ValueError(f"v3 resolve requires non-empty fields: {missing}")
    clean_steps = [str(item).strip() for item in steps if str(item).strip()]
    if not clean_steps:
        raise ValueError("v3 resolve requires at least one solution step")
    if not isinstance(applicability_guard, dict):
        raise ValueError("applicability_guard must be an object")
    if (
        not isinstance(effect_contract, dict)
        or not str(effect_contract.get("expected_effect", "")).strip()
        or not isinstance(effect_contract.get("forbidden_side_effects"), list)
        or not isinstance(effect_contract.get("domain_semantics"), bool)
    ):
        raise ValueError(
            "v3 resolve requires expected_effect, forbidden_side_effects, and boolean domain_semantics"
        )
    if quality_guard is not None and not isinstance(quality_guard, dict):
        raise ValueError("quality_guard must be an object or null")
    if effect_contract.get("domain_semantics") is True and not str(
        regression_test or ""
    ).strip():
        raise ValueError("domain-semantics solution requires a regression_test")

    result = copy.deepcopy(registry)
    event = next(
        (
            item
            for item in result["events"]
            if item.get("event_id") == event_id or item.get("legacy_id") == event_id
        ),
        None,
    )
    if event is None:
        raise KeyError(f"event not found: {event_id}")
    component = canonical_component(str(event.get("component") or ""))
    supplied_identity = (
        component,
        operation.strip(),
        failure_phase.strip(),
        error_class.strip(),
    )
    identity_owner = next(
        (
            str(item.get("family_id"))
            for item in merged_family_catalog(result)
            if tuple(
                str(item.get(key) or "").strip()
                for key in ("component", "operation", "failure_phase", "error_class")
            )
            == supplied_identity
        ),
        None,
    )
    if identity_owner is not None and identity_owner != family_id:
        raise ValueError(
            "problem family identity already belongs to "
            f"{identity_owner}; reuse that family_id"
        )
    authority_family = next(
        (item for item in load_family_catalog() if item.get("family_id") == family_id),
        None,
    )
    authority_solution = next(
        (item for item in load_solution_catalog() if item.get("solution_id") == solution_id),
        None,
    )
    if authority_solution is not None:
        raise ValueError(
            f"solution_id is reserved by the authority catalog: {solution_id}"
        )
    family = next(
        (item for item in result["problem_families"] if item.get("family_id") == family_id),
        None,
    )
    if family is None:
        if authority_family is not None:
            family = copy.deepcopy(authority_family)
        else:
            family = {
                "family_id": family_id,
                "title": family_title.strip(),
                "component": component,
                "operation": operation.strip(),
                "failure_phase": failure_phase.strip(),
                "error_class": error_class.strip(),
                "rule_match_enabled": False,
                "solution_ids": [],
                "owner_skill": "global.collect-bug-update-accelerate",
            }
        result["problem_families"].append(family)
    if family.get("component") != component:
        raise ValueError("problem family belongs to a different component")
    for key, value in (
        ("operation", operation),
        ("failure_phase", failure_phase),
        ("error_class", error_class),
    ):
        if family.get(key) != value:
            raise ValueError(f"problem family {key} does not match the supplied value")

    if authority_family is not None:
        authority_solution_map = {
            str(item["solution_id"]): item for item in load_solution_catalog()
        }
        for canonical_id in authority_family.get("solution_ids", []):
            canonical = authority_solution_map.get(str(canonical_id))
            if canonical is None or canonical.get("status") != "verified":
                continue
            if not any(
                item.get("solution_id") == canonical_id for item in result["solutions"]
            ):
                result["solutions"].append(_builtin_solution_reference(canonical))

    existing = next(
        (item for item in result["solutions"] if item.get("solution_id") == solution_id),
        None,
    )
    if existing is not None and existing.get("catalog_source") == "builtin":
        raise ValueError("builtin solution references cannot be overwritten by runtime resolve")
    if existing is not None and existing.get("family_id") != family_id:
        raise ValueError("solution_id already belongs to a different family")
    counts = {
        "reuse_success_count": int((existing or {}).get("reuse_success_count", 0)),
        "reuse_failure_count": int((existing or {}).get("reuse_failure_count", 0)),
        "source_legacy_ids": list((existing or {}).get("source_legacy_ids", [])),
    }
    if str(event.get("legacy_id")) not in counts["source_legacy_ids"]:
        counts["source_legacy_ids"].append(str(event.get("legacy_id")))
    solution = {
        "solution_id": solution_id,
        "family_id": family_id,
        "catalog_source": "local",
        "title": solution_title.strip(),
        "steps": clean_steps,
        "applicability_guard": copy.deepcopy(applicability_guard),
        "forbidden_routes": [str(item).strip() for item in forbidden_routes if str(item).strip()],
        "verification_contract": verification_contract.strip(),
        "effect_contract": copy.deepcopy(effect_contract),
        "quality_guard": copy.deepcopy(quality_guard),
        "regression_test": str(regression_test).strip() if regression_test else None,
        "status": "verified",
        "owner_skill": "global.collect-bug-update-accelerate",
        **counts,
    }
    if existing is None:
        result["solutions"].append(solution)
    else:
        existing.clear()
        existing.update(solution)
    if solution_id not in family.setdefault("solution_ids", []):
        family["solution_ids"].append(solution_id)
        family["solution_ids"].sort()

    event["family_id"] = family_id
    event["classification_confidence"] = "explicit"
    event["candidate_family_ids"] = []
    event["solution_id"] = solution_id
    event["root_cause"] = root_cause.strip()
    event["diagnosis_evidence"] = diagnosis_evidence.strip()
    event["verification"] = verification.strip()
    event["status"] = "verified"
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    event["last_seen"] = now
    result["updated_at"] = now
    result["problem_families"].sort(key=lambda item: str(item["family_id"]))
    result["solutions"].sort(key=lambda item: str(item["solution_id"]))
    validate_v3(result)
    return result


def capture_event_v3(
    registry: dict[str, Any],
    *,
    component: str,
    symptom: str,
    structured: dict[str, Any] | None = None,
    environment: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_v3(registry)
    result = copy.deepcopy(registry)
    environment = copy.deepcopy(environment or {})
    family_catalog = merged_family_catalog(registry)
    classification = classify_problem(
        component, symptom, structured or {}, environment, family_catalog
    )
    family_id = classification.family_id or _unclassified_id(component, symptom)
    if classification.family_id:
        catalog_family = next(
            (item for item in family_catalog if item.get("family_id") == family_id),
            None,
        )
        if catalog_family is None:
            raise ValueError(f"classified family is missing from authority catalog: {family_id}")
        if not any(item.get("family_id") == family_id for item in result["problem_families"]):
            result["problem_families"].append(copy.deepcopy(catalog_family))
            result["problem_families"].sort(key=lambda item: str(item["family_id"]))
        catalog_solutions = {
            str(item["solution_id"]): item for item in load_solution_catalog()
        }
        for catalog_solution_id in catalog_family.get("solution_ids", []):
            catalog_solution = catalog_solutions.get(str(catalog_solution_id))
            if catalog_solution is None or catalog_solution.get("status") != "verified":
                continue
            if not any(
                item.get("solution_id") == catalog_solution_id
                for item in result["solutions"]
            ):
                result["solutions"].append(
                    _builtin_solution_reference(catalog_solution)
                )
                result["solutions"].sort(key=lambda item: str(item["solution_id"]))
    environment_key = json.dumps(environment, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    event_id = f"event.{_short_hash(canonical_component(component), normalize_signature(symptom), environment_key)}"
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    normalized_symptom = normalize_signature(symptom)
    canonical = canonical_component(component)
    existing = next(
        (
            item
            for item in result["events"]
            if item.get("event_id") == event_id
            or (
                item.get("component") == canonical
                and normalize_signature(str(item.get("symptom_signature") or ""))
                == normalized_symptom
                and (item.get("environment") or {}) == environment
            )
        ),
        None,
    )
    solution_id = None
    if classification.family_id:
        verified = [
            item
            for item in result["solutions"]
            if item.get("family_id") == family_id and item.get("status") == "verified"
        ]
        if len(verified) == 1:
            solution_id = verified[0]["solution_id"]
    if existing is None:
        event = {
            "event_id": event_id,
            "legacy_id": f"native-v3:{event_id}",
            "component": canonical,
            "symptom_signature": normalized_symptom,
            "family_id": family_id,
            "classification_confidence": classification.confidence,
            "candidate_family_ids": list(classification.candidate_family_ids),
            "solution_id": solution_id,
            "root_cause": "unconfirmed",
            "diagnosis_evidence": "",
            "verification": "not-yet-verified",
            "environment": environment,
            "first_seen": now,
            "last_seen": now,
            "occurrences": 1,
            "status": "observed",
            "source_scope": "current-task",
            "owner_skill": "collect-bug-update-accelerate",
            "legacy_reuse_success_count": 0,
            "legacy_reuse_failure_count": 0,
            "legacy_fields": {},
        }
        result["events"].append(event)
    else:
        event = existing
        previous_family_id = str(event.get("family_id") or "")
        event["last_seen"] = now
        event["occurrences"] = int(event.get("occurrences", 0)) + 1
        if classification.family_id is not None:
            event["family_id"] = classification.family_id
            event["classification_confidence"] = classification.confidence
            event["candidate_family_ids"] = list(classification.candidate_family_ids)
            if event.get("solution_id") is None or previous_family_id != classification.family_id:
                event["solution_id"] = solution_id
        elif str(event.get("family_id", "")).startswith("unclassified."):
            event["classification_confidence"] = classification.confidence
            event["candidate_family_ids"] = list(classification.candidate_family_ids)
    result["updated_at"] = now
    validate_v3(result)
    return result, event
