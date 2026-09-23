from __future__ import annotations

import copy
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from problem_families import load_family_catalog  # noqa: E402
from incident_registry import incident_id as canonical_incident_id  # noqa: E402
from registry_v3 import (  # noqa: E402
    apply_v3_plan,
    compact_builtin_solution_references,
    materialize_solution_record,
    plan_v3_migration,
    refresh_authority_catalog,
    validate_v3,
    verify_conservation,
)


def _incident(incident_id: str, symptom: str, occurrences: int, successes: int, failures: int):
    del incident_id
    environment = {"os": "windows"}
    return {
        "id": canonical_incident_id("powershell", symptom, environment),
        "component": "powershell",
        "symptom_signature": symptom,
        "root_cause": "PowerShell grammar does not accept a direct pipe after foreach statement",
        "known_good_solution": "Store foreach output in a variable, then pipe the variable.",
        "verification": "parser and output verified",
        "forbidden_retries": ["do not pipe a foreach statement directly"],
        "preferred_route": "buffer-then-pipe",
        "environment": environment,
        "first_seen": "2026-01-01T00:00:00+08:00",
        "last_seen": "2026-01-02T00:00:00+08:00",
        "occurrences": occurrences,
        "status": "verified",
        "source_scope": "current-task",
        "owner_skill": "collect-bug-update-accelerate",
        "effect_contract": None,
        "diagnosis_evidence": "ParserError reproduced",
        "reuse_success_count": successes,
        "reuse_failure_count": failures,
        "promotion": "none",
        "regression_test": None,
        "last_verified_environment": {"os": "windows"},
    }


def _v2_registry():
    symptoms = [
        "foreach statement piped directly to Format-Table: empty pipe element",
        "pipeline after foreach block caused ParserError empty pipe element",
        "foreach output piped to ConvertTo-Json produced an empty pipe element",
        "foreach statement piped directly to Format-List",
        "PowerShell rejected direct foreach output pipeline",
        "a foreach block cannot be followed directly by a pipe",
    ]
    counts = [(2, 2, 0), (1, 1, 0), (2, 1, 0), (1, 1, 0), (2, 1, 1), (1, 1, 0)]
    return {
        "schema_version": 2,
        "updated_at": "2026-01-02T00:00:00+08:00",
        "incidents": [
            _incident(f"legacy-{index}", symptom, *count)
            for index, (symptom, count) in enumerate(zip(symptoms, counts), start=1)
        ],
    }


def test_v2_migration_preserves_legacy_ids_and_counts() -> None:
    v2 = _v2_registry()
    plan = plan_v3_migration(v2, load_family_catalog())
    migrated = apply_v3_plan(v2, plan)
    validate_v3(migrated)
    report = verify_conservation(v2, migrated, plan)
    assert report.ok
    assert migrated["schema_version"] == 3
    assert set(plan.legacy_id_map) == {item["id"] for item in v2["incidents"]}
    assert sum(event["occurrences"] for event in migrated["events"]) == 9
    assert sum(solution["reuse_success_count"] for solution in migrated["solutions"]) == 7
    assert sum(solution["reuse_failure_count"] for solution in migrated["solutions"]) == 1
    assert {event["family_id"] for event in migrated["events"]} == {
        "powershell.pipeline.foreach-direct"
    }


def test_compaction_replaces_unchanged_catalog_body_with_reference() -> None:
    migrated = apply_v3_plan(
        _v2_registry(), plan_v3_migration(_v2_registry(), load_family_catalog())
    )
    record = migrated["solutions"][0]
    full = materialize_solution_record(record)
    full.update(
        {
            "reuse_success_count": record["reuse_success_count"],
            "reuse_failure_count": record["reuse_failure_count"],
            "source_legacy_ids": record["source_legacy_ids"],
        }
    )
    full.pop("catalog_source", None)
    migrated["solutions"][0] = full
    compacted, changed = compact_builtin_solution_references(migrated)
    assert changed == 1
    assert compacted["solutions"][0]["catalog_source"] == "builtin"
    assert "steps" not in compacted["solutions"][0]
    assert compacted["solutions"][0]["reuse_success_count"] == 7


def test_builtin_reference_cannot_override_authority_body() -> None:
    migrated = apply_v3_plan(
        _v2_registry(), plan_v3_migration(_v2_registry(), load_family_catalog())
    )
    migrated["solutions"][0]["steps"] = ["tampered local step"]
    try:
        validate_v3(migrated)
    except ValueError as exc:
        assert "builtin solution reference contains authority fields" in str(exc)
    else:
        raise AssertionError("builtin references must not override authority solution fields")


def test_builtin_reference_cannot_move_to_another_family() -> None:
    migrated = apply_v3_plan(
        _v2_registry(), plan_v3_migration(_v2_registry(), load_family_catalog())
    )
    other = next(
        item for item in load_family_catalog() if item["family_id"] == "python.import.module-not-found"
    )
    migrated["problem_families"].append(other)
    migrated["solutions"][0]["family_id"] = other["family_id"]
    try:
        validate_v3(migrated)
    except ValueError as exc:
        assert "family mismatch" in str(exc)
    else:
        raise AssertionError("builtin solution references must keep their authority family")


def _registry_with_local_solution() -> dict:
    registry = apply_v3_plan(
        _v2_registry(), plan_v3_migration(_v2_registry(), load_family_catalog())
    )
    local = materialize_solution_record(registry["solutions"][0])
    local["solution_id"] = "powershell.local-buffer-then-pipe"
    local["catalog_source"] = "local"
    registry["solutions"] = [local]
    registry["problem_families"][0]["solution_ids"].append(local["solution_id"])
    for event in registry["events"]:
        event["solution_id"] = local["solution_id"]
    return registry


def test_validation_rejects_string_shell_contains_guard() -> None:
    registry = _registry_with_local_solution()
    registry["solutions"][0]["applicability_guard"]["shell_contains"] = "pwsh"
    try:
        validate_v3(registry)
    except ValueError as exc:
        assert "shell_contains" in str(exc)
    else:
        raise AssertionError("shell_contains must be a string array")


def test_validation_rejects_string_quality_downgrade_routes() -> None:
    registry = _registry_with_local_solution()
    registry["solutions"][0]["quality_guard"]["forbidden_downgrade_routes"] = "ocr"
    try:
        validate_v3(registry)
    except ValueError as exc:
        assert "quality_guard" in str(exc)
    else:
        raise AssertionError("quality downgrade routes must be a string array")


def test_ambiguous_incident_stays_unclassified() -> None:
    v2 = _v2_registry()
    ambiguous = copy.deepcopy(v2["incidents"][0])
    ambiguous.update(
        {
            "id": "legacy-ambiguous",
            "symptom_signature": "ambiguous powershell failure",
            "status": "observed",
            "known_good_solution": "unconfirmed",
            "reuse_success_count": 0,
            "reuse_failure_count": 0,
        }
    )
    v2["incidents"].append(ambiguous)
    migrated = apply_v3_plan(v2, plan_v3_migration(v2, load_family_catalog()))
    event = next(item for item in migrated["events"] if item["legacy_id"] == "legacy-ambiguous")
    assert event["family_id"].startswith("unclassified.powershell.")
    assert event["status"] == "observed"
    assert event["solution_id"] is None


def test_source_change_invalidates_plan() -> None:
    v2 = _v2_registry()
    plan = plan_v3_migration(v2, load_family_catalog())
    v2["incidents"][0]["occurrences"] += 1
    try:
        apply_v3_plan(v2, plan)
    except ValueError as exc:
        assert "source hash changed" in str(exc)
    else:
        raise AssertionError("changed source must invalidate migration plan")


def test_conflicting_legacy_solution_is_not_bound_to_catalog_solution() -> None:
    v2 = _v2_registry()
    v2["incidents"][0]["known_good_solution"] = "Disable formatting and ignore the parser error."
    plan = plan_v3_migration(v2, load_family_catalog())
    migrated = apply_v3_plan(v2, plan)
    event = next(
        item
        for item in migrated["events"]
        if item["legacy_id"] == v2["incidents"][0]["id"]
    )
    assert event["family_id"] == "powershell.pipeline.foreach-direct"
    assert event["solution_id"] is None
    assert event["legacy_reuse_success_count"] == 2


def test_v3_validation_rejects_sensitive_environment_key() -> None:
    registry = apply_v3_plan(
        _v2_registry(), plan_v3_migration(_v2_registry(), load_family_catalog())
    )
    registry["events"][0]["environment"]["token"] = "redacted-value"
    try:
        validate_v3(registry)
    except ValueError as exc:
        assert "sensitive field is forbidden: token" in str(exc)
    else:
        raise AssertionError("v3 registry must reject sensitive environment keys")


def test_v3_validation_rejects_nested_sensitive_legacy_field() -> None:
    registry = apply_v3_plan(
        _v2_registry(), plan_v3_migration(_v2_registry(), load_family_catalog())
    )
    registry["events"][0]["legacy_fields"] = {
        "nested": {"authorization": "redacted-value"}
    }
    try:
        validate_v3(registry)
    except ValueError as exc:
        assert "sensitive field is forbidden: authorization" in str(exc)
    else:
        raise AssertionError("v3 registry must reject nested sensitive keys")


def test_v3_validation_rejects_missing_required_event_field() -> None:
    registry = apply_v3_plan(
        _v2_registry(), plan_v3_migration(_v2_registry(), load_family_catalog())
    )
    del registry["events"][0]["environment"]
    try:
        validate_v3(registry)
    except ValueError as exc:
        assert "event missing fields" in str(exc)
        assert "environment" in str(exc)
    else:
        raise AssertionError("v3 registry must reject incomplete events")


def test_refresh_authority_catalog_reclassifies_declared_family_alias() -> None:
    v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry = apply_v3_plan(v2, plan_v3_migration(v2, load_family_catalog()))
    from registry_v3 import capture_event_v3

    registry, _ = capture_event_v3(
        registry,
        component="ripgrep",
        symptom="regex parse error: invalid escape",
        environment={"os": "windows"},
    )
    family = registry["problem_families"][0]
    family["family_id"] = "ripgrep.pattern.shell-quoting"
    family["error_class"] = "invalid-pattern-quoting"
    family["cause_class"] = "shell-quoting"
    registry["events"][0]["family_id"] = "ripgrep.pattern.shell-quoting"
    registry["events"][0]["candidate_family_ids"] = [
        "ripgrep.pattern.shell-quoting",
        "ripgrep.pattern.shell-quoting",
    ]
    updated, report = refresh_authority_catalog(registry)
    assert report == {"families": 1, "events": 1, "solutions": 0, "total": 2}
    assert updated["events"][0]["family_id"] == "ripgrep.pattern.regex-parse"
    assert updated["events"][0]["candidate_family_ids"] == [
        "ripgrep.pattern.regex-parse"
    ]
    assert updated["problem_families"][0]["cause_class"] == "pattern-parse-failure"
    validate_v3(updated)
