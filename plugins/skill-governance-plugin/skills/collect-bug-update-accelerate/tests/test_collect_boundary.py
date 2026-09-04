from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = ROOT / "skills" / "collect-bug-update-accelerate"
SKILL = SKILL_ROOT / "SKILL.md"


def _skillctl_module():
    path = ROOT / "scripts" / "skillctl.py"
    spec = importlib.util.spec_from_file_location("task4_skillctl", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_collect_boundary_routes_hygiene_without_cleanup_ownership() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "vault_maintenance.py" not in text
    assert "apply-safe" not in text
    assert "HYGIENE_REQUEST" in text
    assert "HYGIENE_RESULT" in text
    assert "同一事件不得递归调用 workspace-hygiene" in text
    assert not (SKILL_ROOT / "scripts" / "vault_maintenance.py").exists()
    assert not (SKILL_ROOT / "references" / "vault-maintenance-contract.md").exists()


def test_collect_uses_registered_canonical_source_without_mirror() -> None:
    registry = json.loads((ROOT / "ecosystem-registry.json").read_text(encoding="utf-8"))
    component = next(
        item for item in registry["components"]
        if item["id"] == "global.collect-bug-update-accelerate"
    )
    assert component["relative_path"].endswith("skills/collect-bug-update-accelerate")
    assert component["mirrors"] == []
    assert SKILL.is_file()


def test_runner_rejects_path_escape_and_preserves_child_exit_code(tmp_path: Path) -> None:
    component = tmp_path / "component"
    scripts = component / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "returns_42.py").write_text("raise SystemExit(42)\n", encoding="utf-8")
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ecosystem_release": "1.0.0",
                "roots": {"temporary": {"kind": "authority", "path": str(tmp_path)}},
                "components": [
                    {
                        "id": "temporary.collect",
                        "kind": "skill",
                        "owner": "test",
                        "root": "temporary",
                        "relative_path": "component",
                        "version": "1.0.0",
                        "interface_version": "1.0",
                        "status": "active",
                        "requires": [],
                        "runtime": "test",
                        "model_policy": "model-agnostic",
                        "mirrors": [],
                        "tests": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    module = _skillctl_module()
    assert module.run_component_script(registry, "temporary.collect", "returns_42.py", []) == 42
    with pytest.raises(ValueError, match="unknown component script"):
        module.run_component_script(registry, "temporary.collect", "../returns_42.py", [])
