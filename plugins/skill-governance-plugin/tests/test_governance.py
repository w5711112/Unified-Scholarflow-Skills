import json
import importlib.util
import os
import shutil
import sys
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def registry_path() -> Path:
    return Path(os.environ.get("SKILLCTL_REGISTRY", ROOT / "ecosystem-registry.json"))


def load_skillctl():
    path = ROOT / "scripts" / "skillctl.py"
    spec = importlib.util.spec_from_file_location("skillctl", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_registry_resolves_root_plus_relative_path(tmp_path: Path) -> None:
    skillctl = load_skillctl()
    source_root = tmp_path / "authority"
    source_root.mkdir()
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "schema_version": 1,
        "roots": {"authority": {"kind": "authority", "path": str(source_root)}},
        "components": [{"id": "fixture.skill", "root": "authority", "relative_path": "skills/example", "status": "active"}],
    }), encoding="utf-8")
    resolved = skillctl.resolve_component(registry, "fixture.skill")
    assert resolved == source_root / "skills" / "example"


def test_registry_rejects_duplicate_active_component() -> None:
    skillctl = load_skillctl()
    data = skillctl.load_registry(registry_path())
    duplicate = dict(data["components"][0])
    data["components"].append(duplicate)
    assert "DUPLICATE_COMPONENT_ID" in {item.code for item in skillctl.validate_registry(data)}


def test_registry_reports_generated_cache_in_active_source(tmp_path: Path) -> None:
    skillctl = load_skillctl()
    source = tmp_path / "skill"
    cache = source / "scripts" / "__pycache__" / "helper.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"cache")
    data = {
        "schema_version": 1,
        "roots": {"authority": {"kind": "authority", "path": str(tmp_path)}},
        "components": [{
            "id": "fixture.skill", "kind": "skill", "owner": "fixture",
            "root": "authority", "relative_path": "skill", "version": "1.0.0",
            "interface_version": "1.0.0", "status": "active", "requires": [],
            "runtime": [], "model_policy": "model-agnostic", "mirrors": [], "tests": [],
        }],
    }
    assert "SOURCE_CACHE_PRESENT" in {item.code for item in skillctl.validate_registry(data)}


def test_provider_graph_is_closed_and_acyclic() -> None:
    skillctl = load_skillctl()
    data = skillctl.load_registry(registry_path())
    assert skillctl.validate_registry(data) == []
    ordered = skillctl.dependency_order(data, ["research.drone-literature-scout-plugin"])
    assert ordered[-1] == "research.drone-literature-scout-plugin"


def test_shipped_governance_skills_are_active_and_resolvable() -> None:
    skillctl = load_skillctl()
    data = skillctl.load_registry(registry_path())
    for component_id in (
        "global.workspace-hygiene",
        "global.collect-bug-update-accelerate",
        "global.migration-skill",
        "global.github-upload",
    ):
        component = next(row for row in data["components"] if row["id"] == component_id)
        assert component["status"] == "active"
        assert skillctl.resolve_component(registry_path(), component_id).is_dir()


def test_generated_lock_records_lowercase_content_hashes() -> None:
    skillctl = load_skillctl()
    lock = skillctl.build_lock(registry_path())
    assert len(lock["registry_sha256"]) == 64
    assert lock["registry_sha256"].islower()
    for component in lock["components"].values():
        assert len(component["content_sha256"]) == 64
        assert component["content_sha256"].islower()


def test_staging_changes_do_not_invalidate_active_release_lock(tmp_path: Path) -> None:
    skillctl = load_skillctl()
    data = skillctl.load_registry(registry_path())
    staging = dict(data["components"][0])
    staging.update({
        "id": "fixture.staging",
        "relative_path": "staging/candidate-one",
        "status": "staging",
    })
    data["components"].append(staging)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    first = skillctl.build_lock(registry)
    staging["relative_path"] = "staging/candidate-two"
    staging["version"] = "9.9.9"
    registry.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    second = skillctl.build_lock(registry)

    assert "fixture.staging" not in first["components"]
    assert first["registry_sha256"] == second["registry_sha256"]


def test_specific_model_requirements_exist_only_in_math_skills() -> None:
    data = load_skillctl().load_registry(registry_path())
    model_pattern = re.compile(r"\b(?:gpt|claude|gemini)-[a-z0-9.-]+", re.IGNORECASE)
    for item in data["components"]:
        if item["status"] != "active" or item["kind"] != "skill":
            continue
        root = Path(data["roots"][item["root"]]["path"])
        canonical = root / item["relative_path"]
        matches = []
        for path in canonical.rglob("*.md"):
            relative = path.relative_to(canonical).as_posix()
            if relative.startswith(("tests/", ".codex/", "quarantine/")):
                continue
            matches.extend(model_pattern.findall(path.read_text(encoding="utf-8")))
        if item["id"].startswith("modeling."):
            assert item["model_policy"] == "explicit:gpt-5.6-sol:xhigh"
            assert matches
        else:
            assert item["model_policy"] == "model-agnostic"
            assert matches == [], f"{item['id']} contains specific model requirements: {matches}"


def test_validate_registry_rejects_active_path_outside_declared_root() -> None:
    skillctl = load_skillctl()
    data = skillctl.load_registry(registry_path())
    component = next(item for item in data["components"] if item["id"] == "global.github-upload")
    component["relative_path"] = "../escape"
    assert "PATH_OUTSIDE_ROOT" in {item.code for item in skillctl.validate_registry(data)}


def test_incremental_audit_reports_missing_provider_without_crashing() -> None:
    skillctl = load_skillctl()
    data = skillctl.load_registry(registry_path())
    component = next(item for item in data["components"] if item["id"] == "global.github-upload")
    component["requires"] = ["missing.provider"]
    findings = skillctl.audit_components(data, ["global.github-upload"])
    assert "PROVIDER_MISSING" in {item.code for item in findings}
    assert "PROVIDER_CYCLE" not in {item.code for item in findings}


def test_incremental_audit_attributes_nested_cache_to_changed_skill(tmp_path: Path) -> None:
    skillctl = load_skillctl()
    plugin = tmp_path / "plugin"
    skill = plugin / "skills" / "child"
    cache = skill / "scripts" / "__pycache__" / "helper.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"cache")
    data = {
        "schema_version": 1,
        "roots": {"authority": {"kind": "authority", "path": str(tmp_path)}},
        "components": [
            {"id": "fixture.plugin", "kind": "plugin", "root": "authority", "relative_path": "plugin", "status": "active", "requires": []},
            {"id": "fixture.child", "kind": "skill", "root": "authority", "relative_path": "plugin/skills/child", "status": "active", "requires": []},
        ],
    }

    findings = skillctl.audit_components(data, ["fixture.child"])

    assert any(item.code == "SOURCE_CACHE_PRESENT" and item.component_id == "fixture.child" for item in findings)


def test_incremental_audit_reports_duplicate_path_for_either_changed_component(tmp_path: Path) -> None:
    skillctl = load_skillctl()
    shared = tmp_path / "shared"
    shared.mkdir()
    data = {
        "schema_version": 1,
        "roots": {"authority": {"kind": "authority", "path": str(tmp_path)}},
        "components": [
            {"id": "fixture.first", "kind": "skill", "root": "authority", "relative_path": "shared", "status": "active", "requires": []},
            {"id": "fixture.second", "kind": "skill", "root": "authority", "relative_path": "shared", "status": "active", "requires": []},
        ],
    }

    for changed in ("fixture.first", "fixture.second"):
        assert "DUPLICATE_ACTIVE_PATH" in {
            item.code for item in skillctl.audit_components(data, [changed])
        }


def test_failed_lifecycle_audit_restores_registry_atomically(tmp_path: Path, monkeypatch, capsys) -> None:
    skillctl = load_skillctl()
    registry = tmp_path / "registry.json"
    previous = b'{"previous":true}\n'
    registry.write_text(json.dumps({"schema_version": 1, "roots": {}, "components": []}), encoding="utf-8")
    monkeypatch.setattr(
        skillctl,
        "audit_components",
        lambda _data, _changed: [skillctl.Finding("DRIFT", "fixture.skill", "changed")],
    )
    replacements = []
    real_replace = skillctl.os.replace

    def recording_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        return real_replace(source, destination)

    monkeypatch.setattr(skillctl.os, "replace", recording_replace)

    result = skillctl.after_lifecycle_event(registry, ["fixture.skill"], previous)

    assert result == 2
    assert registry.read_bytes() == previous
    assert not registry.with_suffix(".json.rollback").exists()
    assert any(destination == registry for _source, destination in replacements)
    assert '"code": "DRIFT"' in capsys.readouterr().out


def test_lifecycle_audit_exception_restores_registry(tmp_path: Path, monkeypatch) -> None:
    skillctl = load_skillctl()
    registry = tmp_path / "registry.json"
    previous = b'{"previous":true}\n'
    registry.write_text(json.dumps({"schema_version": 1, "roots": {}, "components": []}), encoding="utf-8")
    monkeypatch.setattr(
        skillctl,
        "audit_components",
        lambda _data, _changed: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        skillctl.after_lifecycle_event(registry, ["fixture.skill"], previous)

    assert registry.read_bytes() == previous
    assert not registry.with_suffix(".json.rollback").exists()


def test_atomic_registry_write_cleans_temporary_file_on_replace_failure(
    tmp_path: Path, monkeypatch
) -> None:
    skillctl = load_skillctl()
    registry = tmp_path / "registry.json"
    previous = b'{"previous":true}\n'
    registry.write_bytes(previous)
    monkeypatch.setattr(
        skillctl.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
    )

    with pytest.raises(OSError, match="replace failed"):
        skillctl._write_registry(
            registry,
            {"schema_version": 1, "roots": {}, "components": []},
        )

    assert registry.read_bytes() == previous
    assert list(tmp_path.glob("*.next")) == []


def test_build_lock_cli_preserves_existing_lock_on_replace_failure(
    tmp_path: Path, monkeypatch
) -> None:
    skillctl = load_skillctl()
    output = tmp_path / "ecosystem-lock.json"
    previous = b'{"stable":true}\n'
    output.write_bytes(previous)
    monkeypatch.setattr(skillctl, "build_lock", lambda _registry: {"next": True})
    monkeypatch.setattr(
        skillctl.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
    )

    with pytest.raises(OSError, match="replace failed"):
        skillctl.main([
            "--registry", str(tmp_path / "unused-registry.json"),
            "build-lock", "--output", str(output),
        ])

    assert output.read_bytes() == previous
    assert list(tmp_path.glob("*.next")) == []


def test_plan_migration_cli_removes_plan_when_incremental_audit_fails(
    tmp_path: Path, monkeypatch
) -> None:
    skillctl = load_skillctl()
    registry, plan, authority, candidate = _migration_fixture(skillctl, tmp_path)
    before = registry.read_bytes()
    output = tmp_path / "plan.json"
    monkeypatch.setattr(
        skillctl,
        "audit_components",
        lambda _data, _changed: [skillctl.Finding("DRIFT", "fixture.skill", "changed")],
    )

    result = skillctl.main([
        "--registry", str(registry),
        "plan-migration",
        "--component", "fixture.skill",
        "--candidate", str(candidate),
        "--target", str(authority / "target"),
        "--sha256", plan.expected_sha256,
        "--output", str(output),
    ])

    assert result == 2
    assert registry.read_bytes() == before
    assert not output.exists()


def test_plan_migration_output_failure_restores_registry(tmp_path: Path, monkeypatch) -> None:
    skillctl = load_skillctl()
    registry, plan, authority, candidate = _migration_fixture(skillctl, tmp_path)
    before = registry.read_bytes()
    output = tmp_path / "plan.json"
    monkeypatch.setattr(
        skillctl,
        "_write_new_file_atomic",
        lambda _path, _payload: (_ for _ in ()).throw(OSError("plan write failed")),
        raising=False,
    )

    with pytest.raises(OSError, match="plan write failed"):
        skillctl.main([
            "--registry", str(registry),
            "plan-migration",
            "--component", "fixture.skill",
            "--candidate", str(candidate),
            "--target", str(authority / "target"),
            "--sha256", plan.expected_sha256,
            "--output", str(output),
        ])

    assert registry.read_bytes() == before
    assert not output.exists()


def test_activate_cli_audit_exception_restores_registry(tmp_path: Path, monkeypatch) -> None:
    skillctl = load_skillctl()
    registry, plan, _authority, _candidate = _migration_fixture(skillctl, tmp_path)
    before = registry.read_bytes()
    plan_path = tmp_path / "activate.json"
    plan_path.write_text(json.dumps(skillctl.asdict(plan)), encoding="utf-8")
    monkeypatch.setattr(
        skillctl,
        "audit_components",
        lambda _data, _changed: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        skillctl.main(["--registry", str(registry), "activate-migration", "--plan", str(plan_path)])

    assert registry.read_bytes() == before


@pytest.mark.parametrize(
    ("event", "provider_id", "directory", "script_name", "command"),
    [
        (
            "incident-promotion",
            "global.collect-bug-update-accelerate",
            "collect",
            "incident_registry.py",
            "promotion-result",
        ),
        (
            "release-packaging",
            "global.github-upload",
            "github",
            "release_tool.py",
            "build",
        ),
    ],
)
def test_run_lifecycle_uses_bound_route_and_audits_actual_registry_changes(
    tmp_path: Path,
    event: str,
    provider_id: str,
    directory: str,
    script_name: str,
    command: str,
) -> None:
    skillctl = load_skillctl()
    authority = tmp_path / "authority"
    scripts = authority / directory / "scripts"
    scripts.mkdir(parents=True)
    target = authority / "target"
    target.mkdir()
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "schema_version": 1,
        "ecosystem_release": "1.0.0",
        "roots": {"authority": {"kind": "authority", "path": str(authority)}},
        "components": [
            {
                "id": provider_id, "kind": "skill", "root": "authority",
                "relative_path": directory, "status": "active", "requires": [],
            },
            {
                "id": "fixture.changed", "kind": "skill", "root": "authority",
                "relative_path": "target", "status": "active", "requires": [],
            },
        ],
    }), encoding="utf-8")
    before = registry.read_bytes()
    (scripts / script_name).write_text(
        "import json, pathlib, sys\n"
        "path = pathlib.Path(sys.argv[2])\n"
        "data = json.loads(path.read_text(encoding='utf-8'))\n"
        "data['components'][1]['requires'] = ['missing.provider']\n"
        "path.write_text(json.dumps(data), encoding='utf-8')\n",
        encoding="utf-8",
    )

    result = skillctl.main([
        "--registry", str(registry),
        "run-lifecycle",
        "--event", event,
        command, str(registry),
    ])

    assert result == 2
    assert registry.read_bytes() == before


def test_lifecycle_events_are_bound_to_real_owner_commands() -> None:
    skillctl = load_skillctl()
    expected = {
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

    assert skillctl.LIFECYCLE_EVENT_ROUTES == expected
    for component_id, script_name, _command in expected.values():
        script = skillctl.resolve_component(registry_path(), component_id) / "scripts" / script_name
        assert script.is_file()


def test_lifecycle_event_rejects_a_command_outside_its_bound_route(tmp_path: Path) -> None:
    skillctl = load_skillctl()

    with pytest.raises(ValueError, match="LIFECYCLE_EVENT_ROUTE_MISMATCH"):
        skillctl.run_lifecycle_script(
            tmp_path / "unused-registry.json",
            "incident-promotion",
            ["capture-event"],
            [],
        )


def test_register_component_rolls_back_invalid_provider(tmp_path: Path) -> None:
    skillctl = load_skillctl()
    authority = tmp_path / "authority"
    authority.mkdir()
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "schema_version": 1,
        "ecosystem_release": "1.0.0",
        "roots": {"authority": {"kind": "authority", "path": str(authority)}},
        "components": [],
    }), encoding="utf-8")
    before = registry.read_bytes()
    record = tmp_path / "record.json"
    record.write_text(json.dumps({
        "id": "fixture.new", "kind": "skill", "root": "authority",
        "relative_path": "new", "status": "active", "requires": ["missing.provider"],
    }), encoding="utf-8")

    result = skillctl.main([
        "--registry", str(registry),
        "register-component", "--record", str(record),
    ])

    assert result == 2
    assert registry.read_bytes() == before


def _migration_fixture(skillctl, tmp_path: Path) -> tuple[Path, object, Path, Path]:
    authority = tmp_path / "authority"
    derived = tmp_path / "derived"
    source = authority / "source"
    candidate = derived / "candidate"
    for directory in (source, candidate):
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text("content", encoding="utf-8")
    registry = tmp_path / "registry.json"
    digest = skillctl._tree_sha256(candidate)
    registry.write_text(json.dumps({
        "schema_version": 1,
        "ecosystem_release": "1.0.0",
        "roots": {"authority": {"kind": "authority", "path": str(authority)}, "derived": {"kind": "derived", "path": str(derived)}},
        "components": [{"id": "fixture.skill", "kind": "skill", "owner": "fixture", "root": "authority", "relative_path": "source", "version": "1.0.0", "interface_version": "1.0.0", "status": "active", "requires": [], "runtime": [], "model_policy": "model-agnostic", "mirrors": [], "tests": [], "staging_paths": [{"root": "derived", "relative_path": "candidate", "sha256": digest}]}],
    }), encoding="utf-8")
    plan = skillctl.MigrationPlan("fixture.skill", "derived", "candidate", "authority", "target", [], digest, "authority", "source")
    return registry, plan, authority, candidate


def test_activate_migration_rejects_tampered_mirrors_before_copy(tmp_path: Path, monkeypatch) -> None:
    skillctl = load_skillctl()
    registry, plan, authority, _ = _migration_fixture(skillctl, tmp_path)
    tampered = skillctl.MigrationPlan(
        plan.component_id, plan.candidate_root, plan.candidate_relative_path,
        plan.target_root, plan.target_relative_path, ["../escape.md"],
        plan.expected_sha256, plan.previous_root, plan.previous_relative_path,
    )
    monkeypatch.setattr(skillctl.shutil, "copytree", lambda *_: pytest.fail("copytree must not run"))
    with pytest.raises(ValueError, match="MIGRATION_PLAN_INVALID"):
        skillctl.activate_migration(registry, tampered)
    assert not (authority / "target").exists()


def test_activate_migration_removes_partial_copytree_target(tmp_path: Path, monkeypatch) -> None:
    skillctl = load_skillctl()
    registry, plan, authority, _ = _migration_fixture(skillctl, tmp_path)
    before = registry.read_text(encoding="utf-8")

    def partial_copy(_source: Path, target: Path) -> None:
        target.mkdir()
        (target / "partial").write_text("partial", encoding="utf-8")
        raise OSError("copy failed")

    monkeypatch.setattr(skillctl.shutil, "copytree", partial_copy)
    with pytest.raises(OSError, match="copy failed"):
        skillctl.activate_migration(registry, plan)
    assert not (authority / "target").exists()
    assert registry.read_text(encoding="utf-8") == before


def test_activate_migration_rejects_corrupt_previous_path_before_copy(tmp_path: Path, monkeypatch) -> None:
    skillctl = load_skillctl()
    registry, plan, authority, _ = _migration_fixture(skillctl, tmp_path)
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["components"][0]["relative_path"] = "../source"
    registry.write_text(json.dumps(data), encoding="utf-8")
    corrupt = skillctl.MigrationPlan(
        plan.component_id, plan.candidate_root, plan.candidate_relative_path,
        plan.target_root, plan.target_relative_path, plan.target_mirrors,
        plan.expected_sha256, "authority", "../source",
    )
    monkeypatch.setattr(skillctl.shutil, "copytree", lambda *_: pytest.fail("copytree must not run"))
    with pytest.raises(ValueError, match="MIGRATION_PLAN_INVALID"):
        skillctl.activate_migration(registry, corrupt)
    assert not (authority / "target").exists()


def test_activate_migration_preserves_foreign_target_created_during_copy(tmp_path: Path, monkeypatch) -> None:
    skillctl = load_skillctl()
    registry, plan, authority, _ = _migration_fixture(skillctl, tmp_path)
    target = authority / "target"
    original_copytree = skillctl.shutil.copytree

    def race_copy(source: Path, staging: Path) -> Path:
        original_copytree(source, staging)
        if staging == target:
            shutil.rmtree(staging)
        target.mkdir()
        (target / "owner").write_text("foreign", encoding="utf-8")
        return staging

    monkeypatch.setattr(skillctl.shutil, "copytree", race_copy)
    with pytest.raises(FileExistsError):
        skillctl.activate_migration(registry, plan)
    assert (target / "owner").read_text(encoding="utf-8") == "foreign"


def test_activate_migration_uses_atomic_landing_and_preserves_target_after_write_failure(tmp_path: Path, monkeypatch) -> None:
    skillctl = load_skillctl()
    registry, plan, authority, _ = _migration_fixture(skillctl, tmp_path)
    before = registry.read_text(encoding="utf-8")
    original_rename = skillctl.os.rename
    landed: list[tuple[Path, Path]] = []

    def record_rename(source: Path, target: Path) -> None:
        landed.append((source, target))
        original_rename(source, target)

    monkeypatch.setattr(skillctl.os, "rename", record_rename)
    monkeypatch.setattr(skillctl, "_write_registry", lambda *_: (_ for _ in ()).throw(OSError("write failed")))
    with pytest.raises(OSError, match="write failed"):
        skillctl.activate_migration(registry, plan)
    assert landed and landed[0][1] == authority / "target"
    assert (authority / "target" / "SKILL.md").read_text(encoding="utf-8") == "content"
    assert registry.read_text(encoding="utf-8") == before


def test_activate_migration_preserves_foreign_replacement_after_atomic_landing_failure(tmp_path: Path, monkeypatch) -> None:
    skillctl = load_skillctl()
    registry, plan, authority, _ = _migration_fixture(skillctl, tmp_path)
    target = authority / "target"
    previous = authority / "source" / "SKILL.md"
    before = registry.read_text(encoding="utf-8")
    original_rename = skillctl.os.rename

    def replace_landed_target(source: Path, destination: Path) -> None:
        original_rename(source, destination)
        shutil.rmtree(destination)
        destination.mkdir()
        (destination / "owner").write_text("foreign", encoding="utf-8")

    monkeypatch.setattr(skillctl.os, "rename", replace_landed_target)
    with pytest.raises(ValueError, match="TARGET_HASH_DRIFT"):
        skillctl.activate_migration(registry, plan)
    assert (target / "owner").read_text(encoding="utf-8") == "foreign"
    assert registry.read_text(encoding="utf-8") == before
    assert previous.read_text(encoding="utf-8") == "content"


def test_activate_migration_rejects_tampered_plan_target_outside_root(tmp_path: Path) -> None:
    skillctl = load_skillctl()
    authority = tmp_path / "authority"
    derived = tmp_path / "derived"
    source = authority / "source"
    candidate = derived / "candidate"
    for directory in (source, candidate):
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text("content", encoding="utf-8")
    registry = tmp_path / "registry.json"
    digest = skillctl._tree_sha256(candidate)
    registry.write_text(json.dumps({
        "schema_version": 1,
        "ecosystem_release": "1.0.0",
        "roots": {"authority": {"kind": "authority", "path": str(authority)}, "derived": {"kind": "derived", "path": str(derived)}},
        "components": [{"id": "fixture.skill", "kind": "skill", "owner": "fixture", "root": "authority", "relative_path": "source", "version": "1.0.0", "interface_version": "1.0.0", "status": "active", "requires": [], "runtime": [], "model_policy": "model-agnostic", "mirrors": [], "tests": [], "staging_paths": [{"root": "derived", "relative_path": "candidate", "sha256": digest}]}],
    }), encoding="utf-8")
    plan = skillctl.MigrationPlan("fixture.skill", "derived", "candidate", "authority", "../escape", [], digest, "authority", "source")
    with pytest.raises(ValueError, match="MIGRATION_PLAN_INVALID"):
        skillctl.activate_migration(registry, plan)
    assert not (tmp_path / "escape").exists()


def test_governance_plugin_has_exactly_five_skills() -> None:
    expected = {
        "skill-ecosystem-governor",
        "collect-bug-update-accelerate",
        "workspace-hygiene",
        "migration-skill",
        "github-upload",
    }
    actual = {path.name for path in (ROOT / "skills").iterdir() if (path / "SKILL.md").is_file()}
    architecture = json.loads((ROOT / "architecture-manifest.json").read_text(encoding="utf-8"))
    assert actual == expected
    assert set(architecture["skills"]) == expected


def test_governor_skill_is_thin_and_bounded() -> None:
    skill = ROOT / "skills" / "skill-ecosystem-governor" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert skill.stat().st_size <= 2400
    for required in (
        "reverse consumers",
        "one staging proposal",
        "owner tests",
        "atomically switch",
        "regenerate the ecosystem lock",
        "workspace-hygiene",
        "professional semantic judgment",
        "direct deletion",
        "background watcher",
        "second registry",
        "running Skill",
    ):
        assert required in text


def test_marketplace_has_one_entry_per_personal_plugin() -> None:
    marketplace = Path(r"C:/path/to/home/.agents\plugins\marketplace.json")
    data = json.loads(marketplace.read_text(encoding="utf-8"))
    names = [item["name"] for item in data["plugins"]]
    assert names.count("skill-governance-plugin") == 1
    assert names.count("drone-literature-scout-plugin") == 1


@pytest.mark.skipif(os.name != "nt", reason="Windows Junction contract")
def test_governance_marketplace_entry_uses_one_canonical_junction() -> None:
    marketplace = Path(r"C:/path/to/home/.agents\plugins\marketplace.json")
    data = json.loads(marketplace.read_text(encoding="utf-8"))
    entry = next(item for item in data["plugins"] if item["name"] == "skill-governance-plugin")
    assert entry == {
        "name": "skill-governance-plugin",
        "source": {"source": "local", "path": "./plugins/skill-governance-plugin"},
        "policy": {"installation": "INSTALLED_BY_DEFAULT", "authentication": "ON_INSTALL"},
        "category": "Productivity",
    }
    installed = marketplace.parent / "plugins" / "skill-governance-plugin"
    canonical = Path(r"C:/path/to/home/.agents\plugins\sources\skill-governance-plugin")
    assert installed.is_junction()
    assert installed.lstat().st_file_attributes & 0x400
    assert os.path.samefile(installed, canonical)


def test_release_lock_matches_registry_and_manifests() -> None:
    registry = json.loads((ROOT / "ecosystem-registry.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "ecosystem-lock.json").read_text(encoding="utf-8"))
    assert lock["ecosystem_release"] == "1.1.0"
    assert set(lock["components"]) == {
        item["id"] for item in registry["components"] if item["status"] == "active"
    }
    for item in registry["components"]:
        if item["status"] != "active" or item["kind"] != "plugin":
            continue
        canonical = Path(registry["roots"][item["root"]]["path"]) / item["relative_path"]
        plugin = json.loads((canonical / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        architecture = json.loads((canonical / "architecture-manifest.json").read_text(encoding="utf-8"))
        changelog = (canonical / "CHANGELOG.md").read_text(encoding="utf-8")
        version = item["version"]
        assert plugin["version"] == architecture["release_version"] == version
        assert f"## {version}" in changelog or f"## [{version}]" in changelog
        assert lock["components"][item["id"]]["version"] == version


def test_release_has_no_previous_paths_or_generated_sources() -> None:
    registry = json.loads((ROOT / "ecosystem-registry.json").read_text(encoding="utf-8"))
    assert all("previous_path" not in item for item in registry["components"])
    assert all(item["status"] != "staging" for item in registry["components"])


def test_minimal_plugin_shell() -> None:
    manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    architecture = json.loads((ROOT / "architecture-manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "name": "skill-governance-plugin",
        "version": architecture["release_version"],
        "description": "Minimal governance, incident-family reuse, workspace hygiene, migration, and release coordination for user-maintained Skills.",
        "author": {"name": "Local developer"},
        "skills": "./skills/",
        "interface": {
            "displayName": "Skill Governance Plugin",
            "shortDescription": "One registry and five governance Skills",
            "longDescription": "Resolves canonical Skills, validates dependency and version invariants, groups technical events into stable problem families, reuses one guarded verified solution, proposes reversible workspace cleanup, validates cross-host migrations, and prepares isolated GitHub releases.",
            "developerName": "Local developer",
            "category": "Productivity",
            "capabilities": [],
            "defaultPrompt": "Audit the registered Skill ecosystem and propose the smallest verified change.",
        },
    }
    assert architecture == {
        "schema_version": 1,
        "release_version": manifest["version"],
        "plugin": "skill-governance-plugin",
        "skills": ["workspace-hygiene", "collect-bug-update-accelerate", "migration-skill", "github-upload", "skill-ecosystem-governor"],
    }
    assert "hooks" not in manifest
    assert "apps" not in manifest
    assert "mcpServers" not in manifest
    assert (ROOT / "references" / "governance-contract.md").is_file()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.startswith(f"# Changelog\n\n## {manifest['version']} - ")
    contract = (ROOT / "references" / "governance-contract.md").read_text(encoding="utf-8").lower()
    for invariant in (
        "agents-home",
        "research-project",
        "domain-workspace-2026",
        "every component id is unique",
        "exactly one canonical path",
        "roots[root_id].path / relative_path",
        "component records do not store absolute paths",
        "relative_path",
        "requires",
        "reversing `requires`",
        "persisted consumer list is invalid",
        "plugin.json.version",
        "architecture-manifest.release_version",
        "latest changelog release",
        "interface_version",
        "active",
        "staging",
        "quarantine",
        "retired",
        "aggregate obsidian overview",
        "source-tree hash",
        "sha-256",
        "atomically switch active",
        ".codex",
        "second registry",
        "watcher",
        "daemon",
        "success ledger",
        "direct canonical-source deletion",
        "failure-closed",
        "persistent duplicate audit collection",
    ):
        assert invariant in contract
