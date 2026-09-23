from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from incident_registry import preflight, preflight_with_fallback, record_reuse_result  # noqa: E402
from problem_families import load_family_catalog  # noqa: E402
from registry_v3 import (  # noqa: E402
    apply_v3_plan,
    capture_event_v3,
    event_closure_report,
    family_report,
    materialize_solution_record,
    plan_v3_migration,
    resolve_event_v3,
    validate_v3,
)
from test_registry_v3 import _v2_registry  # noqa: E402


def _registry():
    v2 = _v2_registry()
    return apply_v3_plan(v2, plan_v3_migration(v2, load_family_catalog()))


def test_component_only_preflight_returns_candidates() -> None:
    result = preflight(_registry(), component="powershell", environment={"os": "windows"})
    assert result["action"] == "candidate-families"
    assert result["reuse_required"] is False
    assert result["family_ids"] == ["powershell.pipeline.foreach-direct"]


def test_v2_preflight_never_forces_reuse_before_explicit_migration() -> None:
    result = preflight(
        _v2_registry(),
        component="powershell",
        environment={"os": "windows", "shell": "pwsh-7"},
    )
    assert result["action"] == "migration-required"
    assert result["reuse_required"] is False


def test_exact_family_preflight_requires_verified_solution() -> None:
    result = preflight(
        _registry(),
        component="powershell",
        family_id="powershell.pipeline.foreach-direct",
        environment={"os": "windows", "shell": "pwsh-7"},
    )
    assert result["action"] == "use-verified-solution"
    assert result["solution_id"] == "powershell.foreach-buffer-then-pipe"
    assert result["reuse_required"] is True
    assert result["effect_contract"]["expected_effect"]
    assert result["effect_contract"]["domain_semantics"] is False
    assert result["quality_guard"]["preserve_output_fidelity"]


def test_builtin_solution_is_stored_as_reference_without_body_copy() -> None:
    solution = _registry()["solutions"][0]
    assert solution["catalog_source"] == "builtin"
    assert "steps" not in solution
    assert "applicability_guard" not in solution


def test_guard_failure_never_forces_reuse() -> None:
    result = preflight(
        _registry(),
        component="powershell",
        family_id="powershell.pipeline.foreach-direct",
        environment={"os": "linux", "shell": "bash"},
    )
    assert result["action"] == "guard-not-satisfied"
    assert result["reuse_required"] is False


def test_local_regression_blocks_same_public_solution_fallback() -> None:
    local = _registry()
    local["solutions"][0]["status"] = "regressed"
    public = _registry()
    result = preflight_with_fallback(
        local,
        public,
        component="powershell",
        family_id="powershell.pipeline.foreach-direct",
        environment={"os": "windows", "shell": "pwsh-7"},
    )
    assert result["action"] == "local-solution-blocked"
    assert result["reuse_required"] is False
    assert result["blocked_solution_ids"] == ["powershell.foreach-buffer-then-pipe"]


def test_combined_local_public_multiple_verified_never_forces_reuse() -> None:
    local = _registry()
    second = materialize_solution_record(local["solutions"][0])
    second["solution_id"] = "powershell.foreach-local-variant"
    second["catalog_source"] = "local"
    second["title"] = "经验证的本地替代方案"
    second["source_legacy_ids"] = []
    local["solutions"].append(second)
    local["problem_families"][0]["solution_ids"].append(second["solution_id"])
    result = preflight_with_fallback(
        local,
        _registry(),
        component="powershell",
        family_id="powershell.pipeline.foreach-direct",
        environment={"os": "windows", "shell": "pwsh-7"},
    )
    assert result["action"] == "needs-solution-review"
    assert result["reuse_required"] is False
    assert result["solution_ids"] == [
        "powershell.foreach-buffer-then-pipe",
        "powershell.foreach-local-variant",
    ]


def test_closure_rejects_family_with_two_applicable_verified_solutions() -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry = apply_v3_plan(empty_v2, plan_v3_migration(empty_v2, load_family_catalog()))
    registry, event = capture_event_v3(
        registry,
        component="powershell",
        symptom="foreach statement piped directly to Format-Table: empty pipe element",
        environment={"os": "windows", "shell": "pwsh-7"},
    )
    event["status"] = "verified"
    event["verification"] = "解析通过且输出完整"
    second = materialize_solution_record(registry["solutions"][0])
    second["solution_id"] = "powershell.foreach-local-variant"
    second["catalog_source"] = "local"
    second["title"] = "本地替代方案"
    second["source_legacy_ids"] = []
    registry["solutions"].append(second)
    registry["problem_families"][0]["solution_ids"].append(second["solution_id"])
    report = event_closure_report(registry, event["event_id"])
    assert report["closed"] is False
    assert "ambiguous-applicable-solutions" in report["reasons"]


def test_missing_required_guard_value_never_forces_reuse() -> None:
    result = preflight(
        _registry(),
        component="powershell",
        family_id="powershell.pipeline.foreach-direct",
        environment={"os": "windows"},
    )
    assert result["action"] == "guard-not-satisfied"
    assert result["reuse_required"] is False


def test_reuse_failure_regresses_only_target_solution() -> None:
    registry = _registry()
    before = registry["events"][0]["status"]
    updated = record_reuse_result(
        registry,
        incident_id=registry["events"][0]["event_id"],
        success=False,
        effect_verified=False,
        verification="reproduction still fails",
        side_effects=[],
        cleanup_complete=True,
    )
    solution = updated["solutions"][0]
    assert solution["status"] == "regressed"
    assert solution["reuse_failure_count"] == 2
    assert updated["events"][0]["status"] == before


def test_recapture_preserves_historical_solution_after_regression() -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry = apply_v3_plan(empty_v2, plan_v3_migration(empty_v2, load_family_catalog()))
    symptom = "foreach statement piped directly to Format-Table: empty pipe element"
    environment = {"os": "windows", "shell": "pwsh-7"}
    registry, event = capture_event_v3(
        registry, component="powershell", symptom=symptom, environment=environment
    )
    original_solution = event["solution_id"]
    registry = record_reuse_result(
        registry,
        incident_id=event["event_id"],
        success=False,
        effect_verified=False,
        verification="still fails",
        side_effects=[],
        cleanup_complete=True,
    )
    updated, recaptured = capture_event_v3(
        registry, component="powershell", symptom=symptom, environment=environment
    )
    assert recaptured["event_id"] == event["event_id"]
    assert recaptured["solution_id"] == original_solution
    assert recaptured["occurrences"] == 2
    validate_v3(updated)


def test_recapture_preserves_historical_solution_when_family_has_two_verified_solutions() -> None:
    registry = _registry()
    event = registry["events"][0]
    second = materialize_solution_record(registry["solutions"][0])
    second["solution_id"] = "powershell.foreach-local-variant"
    second["catalog_source"] = "local"
    second["title"] = "本地替代方案"
    second["source_legacy_ids"] = []
    registry["solutions"].append(second)
    registry["problem_families"][0]["solution_ids"].append(second["solution_id"])
    updated, recaptured = capture_event_v3(
        registry,
        component=event["component"],
        symptom=event["symptom_signature"],
        environment=event["environment"],
    )
    assert recaptured["event_id"] == event["event_id"]
    assert recaptured["solution_id"] == event["solution_id"]
    validate_v3(updated)


def test_recapture_deduplicates_migrated_event_by_observed_identity() -> None:
    registry = _registry()
    event = registry["events"][0]
    before = len(registry["events"])
    updated, recaptured = capture_event_v3(
        registry,
        component=event["component"],
        symptom=event["symptom_signature"],
        environment=event["environment"],
    )
    assert len(updated["events"]) == before
    assert recaptured["event_id"] == event["event_id"]
    assert recaptured["occurrences"] == event["occurrences"] + 1


def test_v3_reuse_success_requires_guard_environment() -> None:
    registry = _registry()
    try:
        record_reuse_result(
            registry,
            incident_id=registry["events"][0]["event_id"],
            success=True,
            effect_verified=True,
            verification="parser and downstream output verified",
            side_effects=[],
            cleanup_complete=True,
        )
    except ValueError as exc:
        assert "environment" in str(exc)
    else:
        raise AssertionError("v3 reuse success must revalidate its applicability guard")


def test_v3_reuse_success_rejects_forbidden_side_effect() -> None:
    registry = _registry()
    try:
        record_reuse_result(
            registry,
            incident_id=registry["events"][0]["event_id"],
            success=True,
            effect_verified=True,
            verification="parser and downstream output verified",
            side_effects=["drop-output"],
            cleanup_complete=True,
            actual_environment={"os": "windows", "shell": "pwsh-7"},
        )
    except ValueError as exc:
        assert "forbidden side effects" in str(exc)
    else:
        raise AssertionError("v3 reuse success must reject forbidden side effects")


def test_reuse_failure_does_not_overwrite_last_verified_environment() -> None:
    registry = _registry()
    event_id = registry["events"][0]["event_id"]
    verified_environment = {"os": "windows", "shell": "pwsh-7"}
    registry = record_reuse_result(
        registry,
        incident_id=event_id,
        success=True,
        effect_verified=True,
        verification="verified in pwsh 7",
        side_effects=[],
        cleanup_complete=True,
        actual_environment=verified_environment,
    )
    registry = record_reuse_result(
        registry,
        incident_id=event_id,
        success=False,
        effect_verified=False,
        verification="failed in pwsh preview",
        side_effects=[],
        cleanup_complete=True,
        actual_environment={"os": "windows", "shell": "pwsh-preview"},
    )
    solution = registry["solutions"][0]
    assert solution["last_verified_environment"] == verified_environment
    assert solution["last_attempt_environment"] == {
        "os": "windows",
        "shell": "pwsh-preview",
    }
    assert solution["last_failure_verification"] == "failed in pwsh preview"


def test_first_known_event_populates_empty_registry_catalog_snapshot() -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    empty_v3 = apply_v3_plan(
        empty_v2,
        plan_v3_migration(empty_v2, load_family_catalog()),
    )
    updated, event = capture_event_v3(
        empty_v3,
        component="powershell",
        symptom="foreach statement piped directly to Format-Table: empty pipe element",
        environment={"os": "windows", "shell": "pwsh-7"},
    )
    validate_v3(updated)
    assert event["family_id"] == "powershell.pipeline.foreach-direct"
    assert event["solution_id"] == "powershell.foreach-buffer-then-pipe"
    assert [item["family_id"] for item in updated["problem_families"]] == [
        "powershell.pipeline.foreach-direct"
    ]
    assert [item["solution_id"] for item in updated["solutions"]] == [
        "powershell.foreach-buffer-then-pipe"
    ]


def test_atomic_write_directory_permission_family_reuses_verified_solution() -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry = apply_v3_plan(empty_v2, plan_v3_migration(empty_v2, load_family_catalog()))
    updated, event = capture_event_v3(
        registry,
        component="skillctl",
        symptom="atomic sibling temporary file could not be created in the output directory",
        structured={
            "operation": "atomic-write",
            "failure_phase": "write",
            "error_class": "directory-write-permission-denied",
        },
        environment={"os": "windows"},
    )
    assert event["family_id"] == "skillctl.atomic-write.directory-permission"
    assert event["solution_id"] == "skillctl.grant-output-directory-write"
    advice = preflight(
        updated,
        component="skillctl",
        family_id=event["family_id"],
        environment={"os": "windows"},
    )
    assert advice["action"] == "use-verified-solution"
    assert advice["solution_id"] == "skillctl.grant-output-directory-write"


def test_explicit_classification_updates_existing_unclassified_event() -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry = apply_v3_plan(empty_v2, plan_v3_migration(empty_v2, load_family_catalog()))
    symptom = "foreach statement piped directly to Format-Table: empty pipe element"
    registry, event = capture_event_v3(
        registry,
        component="powershell",
        symptom=symptom,
        structured={"family_id": "powershell.pipeline.foreach-direct"},
        environment={"os": "windows", "shell": "pwsh-7"},
    )
    event["family_id"] = "unclassified.powershell.synthetic"
    event["solution_id"] = None
    event["classification_confidence"] = "unclassified"
    registry["problem_families"] = []
    registry["solutions"] = []
    updated, recaptured = capture_event_v3(
        registry,
        component="powershell",
        symptom=symptom,
        structured={"family_id": "powershell.pipeline.foreach-direct"},
        environment={"os": "windows", "shell": "pwsh-7"},
    )
    validate_v3(updated)
    assert recaptured["family_id"] == "powershell.pipeline.foreach-direct"
    assert recaptured["classification_confidence"] == "explicit"
    assert recaptured["solution_id"] == "powershell.foreach-buffer-then-pipe"


def test_validation_rejects_event_solution_from_another_family() -> None:
    registry = _registry()
    other = {
        "family_id": "powershell.runtime.synthetic-family",
        "title": "测试用其他族",
        "component": "powershell",
        "operation": "execute",
        "failure_phase": "runtime",
        "error_class": "synthetic-error",
        "rule_match_enabled": False,
        "solution_ids": [],
        "owner_skill": "global.collect-bug-update-accelerate",
    }
    registry["events"][0]["family_id"] = other["family_id"]
    registry["problem_families"].append(other)
    try:
        validate_v3(registry)
    except ValueError as exc:
        assert "different family" in str(exc)
    else:
        raise AssertionError("event and solution family mismatch must fail")


def test_resolve_v3_creates_family_solution_and_enables_structured_reuse() -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry = apply_v3_plan(empty_v2, plan_v3_migration(empty_v2, load_family_catalog()))
    registry, event = capture_event_v3(
        registry,
        component="custom-tool",
        symptom="deterministic parse failure",
        environment={"os": "windows"},
    )
    resolved = resolve_event_v3(
        registry,
        event_id=event["event_id"],
        family_id="custom-tool.parse.invalid-token",
        solution_id="custom-tool.escape-token",
        family_title="自定义工具令牌解析失败",
        operation="parse-config",
        failure_phase="parse",
        error_class="invalid-token",
        root_cause="配置令牌未按工具语法转义",
        diagnosis_evidence="同一输入可稳定复现，转义后解析通过",
        solution_title="按工具语法转义令牌",
        steps=["转义配置中的保留令牌。", "重新解析并核对输出。"],
        applicability_guard={"os": ["windows"]},
        forbidden_routes=["drop-required-token"],
        verification_contract="解析退出码为 0，且必需令牌仍出现在输出中。",
        effect_contract={
            "expected_effect": "配置成功解析且保留必需令牌。",
            "forbidden_side_effects": ["drop-required-token"],
            "domain_semantics": False,
        },
        quality_guard=None,
        verification="实际解析与输出核对均通过",
    )
    validate_v3(resolved)
    stored = next(item for item in resolved["events"] if item["event_id"] == event["event_id"])
    assert stored["status"] == "verified"
    assert stored["family_id"] == "custom-tool.parse.invalid-token"
    assert stored["solution_id"] == "custom-tool.escape-token"

    recaptured, learned = capture_event_v3(
        resolved,
        component="custom-tool",
        symptom="another instance",
        structured={
            "operation": "parse-config",
            "failure_phase": "parse",
            "error_class": "invalid-token",
        },
        environment={"os": "windows"},
    )
    assert learned["family_id"] == "custom-tool.parse.invalid-token"
    assert learned["solution_id"] == "custom-tool.escape-token"
    assert preflight(
        recaptured,
        component="custom-tool",
        family_id="custom-tool.parse.invalid-token",
        environment={"os": "windows"},
    )["action"] == "use-verified-solution"


def test_resolve_v3_rejects_duplicate_structured_family_identity() -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry = apply_v3_plan(empty_v2, plan_v3_migration(empty_v2, load_family_catalog()))
    registry, first = capture_event_v3(
        registry,
        component="custom-tool",
        symptom="first invalid token",
        environment={"os": "windows"},
    )
    registry = resolve_event_v3(
        registry,
        event_id=first["event_id"],
        family_id="custom-tool.parse.invalid-token",
        solution_id="custom-tool.escape-token",
        family_title="令牌解析失败",
        operation="parse-config",
        failure_phase="parse",
        error_class="invalid-token",
        root_cause="令牌未转义",
        diagnosis_evidence="稳定复现",
        solution_title="转义令牌",
        steps=["转义令牌"],
        applicability_guard={"os": ["windows"]},
        forbidden_routes=[],
        verification_contract="解析通过",
        effect_contract={"expected_effect": "解析成功", "forbidden_side_effects": [], "domain_semantics": False},
        quality_guard=None,
        verification="通过",
    )
    registry, second = capture_event_v3(
        registry,
        component="custom-tool",
        symptom="second invalid token",
        environment={"os": "windows"},
    )
    try:
        resolve_event_v3(
            registry,
            event_id=second["event_id"],
            family_id="custom-tool.parse.duplicate-name",
            solution_id="custom-tool.second-solution",
            family_title="重复族",
            operation="parse-config",
            failure_phase="parse",
            error_class="invalid-token",
            root_cause="已核实",
            diagnosis_evidence="已核实",
            solution_title="另一方案",
            steps=["处理"],
            applicability_guard={"os": ["windows"]},
            forbidden_routes=[],
            verification_contract="通过",
            effect_contract={"expected_effect": "通过", "forbidden_side_effects": [], "domain_semantics": False},
            quality_guard=None,
            verification="通过",
        )
    except ValueError as exc:
        assert "reuse that family_id" in str(exc)
    else:
        raise AssertionError("duplicate structured family identity must be rejected")


def test_resolve_v3_rejects_local_id_for_authority_family_identity() -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry = apply_v3_plan(empty_v2, plan_v3_migration(empty_v2, load_family_catalog()))
    registry, event = capture_event_v3(
        registry,
        component="powershell",
        symptom="unrelated observed parser error",
        environment={"os": "windows", "shell": "pwsh-7"},
    )
    try:
        resolve_event_v3(
            registry,
            event_id=event["event_id"],
            family_id="powershell.pipeline.duplicate-local-id",
            solution_id="powershell.duplicate-local-solution",
            family_title="重复权威族",
            operation="pipeline",
            failure_phase="parse",
            error_class="empty-pipe-element",
            root_cause="已核实",
            diagnosis_evidence="已核实",
            solution_title="替代方案",
            steps=["处理"],
            applicability_guard={"os": ["windows"]},
            forbidden_routes=[],
            verification_contract="通过",
            effect_contract={"expected_effect": "通过", "forbidden_side_effects": [], "domain_semantics": False},
            quality_guard=None,
            verification="通过",
        )
    except ValueError as exc:
        assert "reuse that family_id" in str(exc)
        assert "powershell.pipeline.foreach-direct" in str(exc)
    else:
        raise AssertionError("authority family identity must reserve its structured identity")


def test_resolve_v3_rejects_authority_family_for_different_component() -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry = apply_v3_plan(empty_v2, plan_v3_migration(empty_v2, load_family_catalog()))
    registry, event = capture_event_v3(
        registry,
        component="custom-tool",
        symptom="observed parser error",
        environment={"os": "windows"},
    )
    try:
        resolve_event_v3(
            registry,
            event_id=event["event_id"],
            family_id="powershell.pipeline.foreach-direct",
            solution_id="custom-tool.invalid-cross-component-solution",
            family_title="跨组件误绑定",
            operation="pipeline",
            failure_phase="parse",
            error_class="empty-pipe-element",
            root_cause="已核实",
            diagnosis_evidence="已核实",
            solution_title="无效方案",
            steps=["处理"],
            applicability_guard={"os": ["windows"]},
            forbidden_routes=[],
            verification_contract="通过",
            effect_contract={"expected_effect": "通过", "forbidden_side_effects": [], "domain_semantics": False},
            quality_guard=None,
            verification="通过",
        )
    except ValueError as exc:
        assert "different component" in str(exc)
    else:
        raise AssertionError("authority family cannot classify an event from another component")


def test_family_report_includes_unattributed_legacy_reuse_counts() -> None:
    registry = _registry()
    registry["events"][0]["legacy_reuse_success_count"] = 7
    registry["events"][0]["legacy_reuse_failure_count"] = 3
    report = family_report(registry)
    assert report["reuse_success_count"] == registry["solutions"][0]["reuse_success_count"] + 7
    assert report["reuse_failure_count"] == registry["solutions"][0]["reuse_failure_count"] + 3
    assert report["legacy_unattributed_reuse_success_count"] == 7
    assert report["legacy_unattributed_reuse_failure_count"] == 3


def test_resolve_v3_rejects_incomplete_domain_semantics_contract() -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry = apply_v3_plan(empty_v2, plan_v3_migration(empty_v2, load_family_catalog()))
    registry, event = capture_event_v3(
        registry,
        component="custom-tool",
        symptom="invalid token",
        environment={"os": "windows"},
    )
    try:
        resolve_event_v3(
            registry,
            event_id=event["event_id"],
            family_id="custom-tool.parse.invalid-token",
            solution_id="custom-tool.escape-token",
            family_title="令牌解析失败",
            operation="parse-config",
            failure_phase="parse",
            error_class="invalid-token",
            root_cause="令牌未转义",
            diagnosis_evidence="稳定复现",
            solution_title="转义令牌",
            steps=["转义令牌"],
            applicability_guard={"os": ["windows"]},
            forbidden_routes=[],
            verification_contract="解析和输出均通过",
            effect_contract={"expected_effect": "解析成功", "forbidden_side_effects": []},
            quality_guard=None,
            verification="实际验证通过",
        )
    except ValueError as exc:
        assert "domain_semantics" in str(exc)
    else:
        raise AssertionError("verified v3 solutions require a boolean domain_semantics flag")


def test_resolve_v3_rejects_domain_semantics_without_regression_test() -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry = apply_v3_plan(empty_v2, plan_v3_migration(empty_v2, load_family_catalog()))
    registry, event = capture_event_v3(
        registry,
        component="planner",
        symptom="trajectory meaning changed",
        environment={"os": "windows"},
    )
    try:
        resolve_event_v3(
            registry,
            event_id=event["event_id"],
            family_id="planner.output.semantic-drift",
            solution_id="planner.restore-semantics",
            family_title="轨迹语义偏移",
            operation="plan",
            failure_phase="verification",
            error_class="semantic-drift",
            root_cause="字段含义被改写",
            diagnosis_evidence="同一输入的含义核对失败",
            solution_title="恢复字段语义",
            steps=["恢复字段语义"],
            applicability_guard={"os": ["windows"]},
            forbidden_routes=[],
            verification_contract="语义核对通过",
            effect_contract={"expected_effect": "语义恢复", "forbidden_side_effects": [], "domain_semantics": True},
            quality_guard=None,
            verification="单次语义核对通过",
        )
    except ValueError as exc:
        assert "regression_test" in str(exc)
    else:
        raise AssertionError("domain semantics solutions require regression evidence")


def test_resolve_v3_cannot_take_over_authority_solution_id() -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry = apply_v3_plan(empty_v2, plan_v3_migration(empty_v2, load_family_catalog()))
    registry, event = capture_event_v3(
        registry,
        component="powershell",
        symptom="unrelated observed parser failure",
        environment={"os": "windows", "shell": "pwsh-7"},
    )
    try:
        resolve_event_v3(
            registry,
            event_id=event["event_id"],
            family_id="powershell.pipeline.foreach-direct",
            solution_id="powershell.foreach-buffer-then-pipe",
            family_title="PowerShell foreach 直接进入管道",
            operation="pipeline",
            failure_phase="parse",
            error_class="empty-pipe-element",
            root_cause="测试抢占",
            diagnosis_evidence="测试",
            solution_title="伪造本地正文",
            steps=["伪造步骤"],
            applicability_guard={"os": ["windows"]},
            forbidden_routes=[],
            verification_contract="伪造",
            effect_contract={
                "expected_effect": "伪造",
                "forbidden_side_effects": [],
                "domain_semantics": False,
            },
            quality_guard=None,
            verification="伪造",
        )
    except ValueError as exc:
        assert "reserved by the authority catalog" in str(exc)
    else:
        raise AssertionError("runtime resolve must not take over an authority solution id")
