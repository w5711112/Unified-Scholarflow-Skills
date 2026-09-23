from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from test_registry_v3 import _v2_registry
from problem_families import load_family_catalog
from registry_v3 import apply_v3_plan, capture_event_v3, plan_v3_migration


SKILL_ROOT = Path(__file__).resolve().parents[1]
MIGRATE = SKILL_ROOT / "scripts" / "migrate_registry_v3.py"
REGISTRY_CLI = SKILL_ROOT / "scripts" / "incident_registry.py"
PYTHON = [sys.executable, "-X", "utf8"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_dry_run_keeps_source_bytes_and_writes_valid_preview(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    report = tmp_path / "report.json"
    preview = tmp_path / "preview.json"
    registry.write_text(json.dumps(_v2_registry(), ensure_ascii=False, indent=2), encoding="utf-8")
    before = _sha(registry)
    run = subprocess.run(
        [
            *PYTHON,
            str(MIGRATE),
            "--registry",
            str(registry),
            "--dry-run",
            "--report",
            str(report),
            "--preview",
            str(preview),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert _sha(registry) == before
    assert json.loads(preview.read_text(encoding="utf-8"))["schema_version"] == 3
    assert json.loads(report.read_text(encoding="utf-8"))["conservation"]["ok"] is True


def test_apply_creates_byte_backup_and_schema_v3(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    report = tmp_path / "report.json"
    registry.write_text(json.dumps(_v2_registry(), ensure_ascii=False, indent=2), encoding="utf-8")
    original = registry.read_bytes()
    run = subprocess.run(
        [*PYTHON, str(MIGRATE), "--registry", str(registry), "--apply", "--report", str(report)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(registry.read_text(encoding="utf-8"))["schema_version"] == 3
    backups = list(tmp_path.glob("registry.json.v2-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original


def test_dry_run_rejects_report_or_preview_path_equal_to_registry(tmp_path: Path) -> None:
    for option in ("--report", "--preview"):
        registry = tmp_path / f"registry-{option[2:]}.json"
        registry.write_text(json.dumps(_v2_registry(), ensure_ascii=False), encoding="utf-8")
        original = registry.read_bytes()
        run = subprocess.run(
            [
                *PYTHON,
                str(MIGRATE),
                "--registry",
                str(registry),
                "--dry-run",
                option,
                str(registry),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert run.returncode != 0
        assert registry.read_bytes() == original


def test_preflight_cli_returns_42_only_for_unique_guarded_solution(tmp_path: Path) -> None:
    v2 = _v2_registry()
    v3 = apply_v3_plan(v2, plan_v3_migration(v2, load_family_catalog()))
    registry = tmp_path / "registry-v3.json"
    registry.write_text(json.dumps(v3, ensure_ascii=False, indent=2), encoding="utf-8")
    base = [*PYTHON, str(REGISTRY_CLI), "preflight", "--registry", str(registry), "--component", "powershell"]

    component_only = subprocess.run(base, capture_output=True, text=True, encoding="utf-8", check=False)
    assert component_only.returncode == 0
    assert json.loads(component_only.stdout)["action"] == "candidate-families"

    exact = subprocess.run(
        base
        + [
            "--family-id",
            "powershell.pipeline.foreach-direct",
            "--environment",
            "os=windows",
            "--environment",
            "shell=pwsh-7",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert exact.returncode == 42
    assert json.loads(exact.stdout)["solution_id"] == "powershell.foreach-buffer-then-pipe"

    structured = subprocess.run(
        base
        + [
            "--operation",
            "pipeline",
            "--failure-phase",
            "parse",
            "--error-class",
            "empty-pipe-element",
            "--environment",
            "os=windows",
            "--environment",
            "shell=pwsh-7",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert structured.returncode == 42


def test_v2_reuse_result_requires_migration_and_preserves_source(tmp_path: Path) -> None:
    registry = tmp_path / "registry-v2.json"
    registry.write_text(json.dumps(_v2_registry(), ensure_ascii=False, indent=2), encoding="utf-8")
    before = registry.read_bytes()
    run = subprocess.run(
        [
            *PYTHON,
            str(REGISTRY_CLI),
            "reuse-result",
            "--registry",
            str(registry),
            "--incident-id",
            "legacy-1",
            "--outcome",
            "failure",
            "--verification",
            "still fails",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert run.returncode == 3
    assert json.loads(run.stdout)["action"] == "migration-required"
    assert registry.read_bytes() == before


def test_v3_resolve_cli_persists_reusable_family_and_solution(tmp_path: Path) -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    v3 = apply_v3_plan(empty_v2, plan_v3_migration(empty_v2, load_family_catalog()))
    v3, event = capture_event_v3(
        v3,
        component="custom-tool",
        symptom="invalid token",
        environment={"os": "windows"},
    )
    registry = tmp_path / "registry-v3.json"
    registry.write_text(json.dumps(v3, ensure_ascii=False, indent=2), encoding="utf-8")
    run = subprocess.run(
        [
            *PYTHON,
            str(REGISTRY_CLI),
            "resolve",
            "--registry",
            str(registry),
            "--incident-id",
            event["event_id"],
            "--family-id",
            "custom-tool.parse.invalid-token",
            "--solution-id",
            "custom-tool.escape-token",
            "--family-title",
            "自定义工具令牌解析失败",
            "--operation",
            "parse-config",
            "--failure-phase",
            "parse",
            "--error-class",
            "invalid-token",
            "--root-cause",
            "令牌未转义",
            "--diagnosis-evidence",
            "稳定复现并验证转义后通过",
            "--solution",
            "转义保留令牌",
            "--solution-title",
            "按语法转义令牌",
            "--verification-contract",
            "退出码为0且输出保留令牌",
            "--applicability-guard",
            json.dumps({"os": ["windows"]}),
            "--effect-contract",
            json.dumps(
                {
                    "expected_effect": "配置解析成功",
                    "forbidden_side_effects": ["drop-token"],
                    "domain_semantics": False,
                }
            ),
            "--verification",
            "实际解析和输出核对通过",
            "--preferred-route",
            "escape-token",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert run.returncode == 0, run.stderr
    saved = json.loads(registry.read_text(encoding="utf-8"))
    assert saved["events"][0]["solution_id"] == "custom-tool.escape-token"
    assert saved["solutions"][0]["catalog_source"] == "local"

    matched = subprocess.run(
        [
            *PYTHON,
            str(REGISTRY_CLI),
            "match",
            "--registry",
            str(registry),
            "--component",
            "custom-tool",
            "--symptom",
            "",
            "--family-id",
            "custom-tool.parse.invalid-token",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert matched.returncode == 0, matched.stderr
    match_output = json.loads(matched.stdout)
    assert len(match_output) == 1
    assert match_output[0]["family_id"] == "custom-tool.parse.invalid-token"

    preflighted = subprocess.run(
        [
            *PYTHON,
            str(REGISTRY_CLI),
            "preflight",
            "--registry",
            str(registry),
            "--component",
            "custom-tool",
            "--operation",
            "parse-config",
            "--failure-phase",
            "parse",
            "--error-class",
            "invalid-token",
            "--environment",
            "os=windows",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert preflighted.returncode == 42, preflighted.stderr
    assert json.loads(preflighted.stdout)["solution_id"] == "custom-tool.escape-token"


def test_legacy_migrate_command_is_noop_for_v3(tmp_path: Path) -> None:
    v2 = _v2_registry()
    v3 = apply_v3_plan(v2, plan_v3_migration(v2, load_family_catalog()))
    registry = tmp_path / "registry-v3.json"
    registry.write_text(json.dumps(v3, ensure_ascii=False, indent=2), encoding="utf-8")
    before = registry.read_bytes()
    run = subprocess.run(
        [*PYTHON, str(REGISTRY_CLI), "migrate", "--registry", str(registry)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["action"] == "already-current"
    assert registry.read_bytes() == before


def test_migrate_v3_rejects_invalid_v2_before_writing(tmp_path: Path) -> None:
    for name, mutate in (
        ("missing-field", lambda value: value["incidents"][0].pop("environment")),
        ("invalid-status", lambda value: value["incidents"][0].__setitem__("status", "unknown")),
    ):
        source = _v2_registry()
        mutate(source)
        registry = tmp_path / f"{name}.json"
        registry.write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
        before = registry.read_bytes()
        run = subprocess.run(
            [*PYTHON, str(MIGRATE), "--registry", str(registry), "--apply"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert run.returncode != 0
        assert registry.read_bytes() == before
        assert not list(tmp_path.glob(f"{name}.json.v2-*.bak"))


def test_refresh_catalog_cli_upgrades_old_family_id_with_byte_backup(tmp_path: Path) -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry_value = apply_v3_plan(
        empty_v2, plan_v3_migration(empty_v2, load_family_catalog())
    )
    registry_value, _ = capture_event_v3(
        registry_value,
        component="ripgrep",
        symptom="regex parse error: invalid escape",
        environment={"os": "windows"},
    )
    registry_value["problem_families"][0]["family_id"] = "ripgrep.pattern.shell-quoting"
    registry_value["problem_families"][0]["error_class"] = "invalid-pattern-quoting"
    registry_value["problem_families"][0]["cause_class"] = "shell-quoting"
    registry_value["events"][0]["family_id"] = "ripgrep.pattern.shell-quoting"
    registry = tmp_path / "registry-v3.json"
    registry.write_text(
        json.dumps(registry_value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    original = registry.read_bytes()
    run = subprocess.run(
        [*PYTHON, str(REGISTRY_CLI), "refresh-catalog", "--registry", str(registry)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["events"] == 1
    assert Path(report["backup"]).read_bytes() == original
    saved = json.loads(registry.read_text(encoding="utf-8"))
    assert saved["events"][0]["family_id"] == "ripgrep.pattern.regex-parse"


def test_capture_event_requires_resolution_and_closure_check_blocks_open_event(
    tmp_path: Path,
) -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry_value = apply_v3_plan(
        empty_v2, plan_v3_migration(empty_v2, load_family_catalog())
    )
    registry = tmp_path / "registry-v3.json"
    registry.write_text(
        json.dumps(registry_value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    captured = subprocess.run(
        [
            *PYTHON,
            str(REGISTRY_CLI),
            "capture-event",
            "--registry",
            str(registry),
            "--component",
            "custom-tool",
            "--symptom",
            "deterministic parse failure",
            "--environment",
            "os=windows",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert captured.returncode == 43
    captured_output = json.loads(captured.stdout)
    assert captured_output["advice"]["resolve_required"] is True
    event_id = captured_output["incident"]["event_id"]

    closure = subprocess.run(
        [
            *PYTHON,
            str(REGISTRY_CLI),
            "closure-check",
            "--registry",
            str(registry),
            "--incident-id",
            event_id,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert closure.returncode == 43
    report = json.loads(closure.stdout)
    assert report["closed"] is False
    assert "unclassified-family" in report["reasons"]
    assert "missing-solution" in report["reasons"]


def test_resolve_makes_event_pass_closure_check(tmp_path: Path) -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry_value = apply_v3_plan(
        empty_v2, plan_v3_migration(empty_v2, load_family_catalog())
    )
    registry_value, event = capture_event_v3(
        registry_value,
        component="custom-tool",
        symptom="deterministic parse failure",
        environment={"os": "windows"},
    )
    registry = tmp_path / "registry-v3.json"
    registry.write_text(
        json.dumps(registry_value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    resolved = subprocess.run(
        [
            *PYTHON,
            str(REGISTRY_CLI),
            "resolve",
            "--registry",
            str(registry),
            "--incident-id",
            event["event_id"],
            "--family-id",
            "custom-tool.parse.invalid-token",
            "--solution-id",
            "custom-tool.escape-token",
            "--family-title",
            "自定义工具令牌解析失败",
            "--operation",
            "parse-config",
            "--failure-phase",
            "parse",
            "--error-class",
            "invalid-token",
            "--root-cause",
            "令牌未按工具语法转义",
            "--diagnosis-evidence",
            "同一输入稳定复现，转义后解析通过",
            "--solution",
            "转义保留令牌",
            "--solution-title",
            "按语法转义令牌",
            "--applicability-guard",
            json.dumps({"os": ["windows"]}),
            "--verification-contract",
            "退出码为0且输出保留令牌",
            "--effect-contract",
            json.dumps(
                {
                    "expected_effect": "配置解析成功",
                    "forbidden_side_effects": [],
                    "domain_semantics": False,
                }
            ),
            "--verification",
            "实际解析和输出核对通过",
            "--preferred-route",
            "escape-token",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert resolved.returncode == 0, resolved.stderr

    closure = subprocess.run(
        [
            *PYTHON,
            str(REGISTRY_CLI),
            "closure-check",
            "--registry",
            str(registry),
            "--incident-id",
            event["event_id"],
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert closure.returncode == 0, closure.stderr
    report = json.loads(closure.stdout)
    assert report["closed"] is True
    assert report["family_id"] == "custom-tool.parse.invalid-token"
    assert report["solution_id"] == "custom-tool.escape-token"


def test_successful_reuse_closes_the_current_event(tmp_path: Path) -> None:
    empty_v2 = {"schema_version": 2, "updated_at": "2026-01-01T00:00:00+08:00", "incidents": []}
    registry_value = apply_v3_plan(
        empty_v2, plan_v3_migration(empty_v2, load_family_catalog())
    )
    registry_value, event = capture_event_v3(
        registry_value,
        component="powershell",
        symptom="foreach statement piped directly to Format-Table: empty pipe element",
        environment={"os": "windows", "shell": "pwsh-7"},
    )
    registry = tmp_path / "registry-v3.json"
    registry.write_text(
        json.dumps(registry_value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    reused = subprocess.run(
        [
            *PYTHON,
            str(REGISTRY_CLI),
            "reuse-result",
            "--registry",
            str(registry),
            "--incident-id",
            event["event_id"],
            "--outcome",
            "success",
            "--effect-verified",
            "--cleanup-complete",
            "--environment",
            "os=windows",
            "--environment",
            "shell=pwsh-7",
            "--verification",
            "解析通过且输出完整",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert reused.returncode == 0, reused.stderr
    saved = json.loads(registry.read_text(encoding="utf-8"))
    assert saved["events"][0]["status"] == "verified"
    assert saved["events"][0]["verification"] == "解析通过且输出完整"

    closure = subprocess.run(
        [
            *PYTHON,
            str(REGISTRY_CLI),
            "closure-check",
            "--registry",
            str(registry),
            "--incident-id",
            event["event_id"],
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert closure.returncode == 0, closure.stderr
    assert json.loads(closure.stdout)["closed"] is True
