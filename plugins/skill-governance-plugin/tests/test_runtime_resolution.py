import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "ecosystem-registry.json").read_text(encoding="utf-8"))
RESEARCH_COMPONENT = next(
    row
    for row in REGISTRY["components"]
    if row["id"] == "research.drone-literature-scout-plugin"
)
PROJECT = Path(REGISTRY["roots"][RESEARCH_COMPONENT["root"]]["path"])
RESEARCH = PROJECT / RESEARCH_COMPONENT["relative_path"]


@pytest.fixture
def skillctl():
    path = ROOT / "scripts" / "skillctl.py"
    spec = importlib.util.spec_from_file_location("runtime_skillctl", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_research_python_lock_is_exact_and_has_no_interpreter_path() -> None:
    lock = RESEARCH / "runtime" / "locks" / "research-python.lock"
    assert lock.read_text(encoding="utf-8").splitlines() == [
        "numpy==2.4.1",
        "matplotlib==3.11.1",
        "Pillow==12.1.0",
        "fonttools==4.63.0",
        "contourpy==1.3.3",
        "cycler==0.12.1",
        "kiwisolver==1.5.0",
        "packaging==26.0",
        "pyparsing==3.3.2",
        "python-dateutil==2.9.0.post0",
        "PyYAML==6.0.3",
        "six==1.17.0",
    ]


def test_runtime_path_is_external_and_hash_keyed(skillctl, tmp_path: Path, monkeypatch) -> None:
    lock = tmp_path / "runtime.lock"
    lock.write_text("demo==1.0\n", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    expected = hashlib.sha256(lock.read_bytes()).hexdigest()
    assert skillctl.runtime_path(lock, "python") == tmp_path / "local" / "SkillRuntime" / "python" / expected


def test_runtime_path_requires_localappdata(skillctl, tmp_path: Path, monkeypatch) -> None:
    lock = tmp_path / "runtime.lock"
    lock.write_text("demo==1.0\n", encoding="utf-8")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    with pytest.raises(RuntimeError, match="LOCALAPPDATA"):
        skillctl.runtime_path(lock, "python")


def test_project_python_packages_is_recorded_absent_and_not_recreated() -> None:
    manifest = json.loads((RESEARCH / "runtime-manifest.json").read_text(encoding="utf-8"))
    assert manifest["legacy_runtime"] == {
        "path": ".codex-runtime/python-packages",
        "status": "absent-before-task",
        "cleanup_policy": "do-not-recreate-in-source",
    }
    assert not (PROJECT / ".codex-runtime" / "python-packages").exists()


def test_probe_reports_missing_and_mismatched_versions(skillctl, tmp_path: Path, monkeypatch) -> None:
    lock = tmp_path / "runtime.lock"
    lock.write_text("present==1.0\nmissing==2.0\nwrong==3.0\n", encoding="utf-8")

    class Completed:
        returncode = 0
        stdout = json.dumps({"present": "1.0", "missing": None, "wrong": "2.5"})
        stderr = ""

    monkeypatch.setattr(skillctl.subprocess, "run", lambda *args, **kwargs: Completed())
    probe = skillctl.probe_python_runtime(Path("python"), lock)
    assert probe.satisfied is False
    assert probe.missing == ["missing"]
    assert probe.mismatched == ["wrong: required 3.0, installed 2.5"]


def test_active_research_consumers_reference_declared_runtime() -> None:
    registry = json.loads((ROOT / "ecosystem-registry.json").read_text(encoding="utf-8"))
    manifest = json.loads((RESEARCH / "runtime-manifest.json").read_text(encoding="utf-8"))
    declared = set(manifest["runtimes"])
    research = [row for row in registry["components"] if row["status"] == "active" and row["id"].startswith("research.")]
    assert research
    for row in research:
        assert set(row["runtime"]) <= declared
    assert next(row for row in research if row["id"] == "research.searching-at-scale")["runtime"] == ["searching-node"]
    for row in research:
        if row["id"] != "research.searching-at-scale":
            assert row["runtime"] == ["research-python"]
