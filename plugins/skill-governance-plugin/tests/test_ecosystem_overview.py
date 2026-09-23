import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_overview():
    path = ROOT / "scripts" / "ecosystem_overview.py"
    spec = importlib.util.spec_from_file_location("ecosystem_overview", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_skillctl():
    path = ROOT / "scripts" / "skillctl.py"
    spec = importlib.util.spec_from_file_location("skillctl_overview_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_registry(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    project = vault / "project"
    agents = tmp_path / "agents"
    (vault / ".obsidian").mkdir(parents=True)
    (vault / "Skill完整指南").mkdir()
    (project / "skills" / "one").mkdir(parents=True)
    (agents / "skills" / "two" / "references").mkdir(parents=True)
    (project / "skills" / "one" / "SKILL.md").write_text("# One\n", encoding="utf-8")
    (agents / "skills" / "two" / "SKILL.md").write_text("# Two\n", encoding="utf-8")
    (agents / "skills" / "two" / "references" / "rules.md").write_text(
        "# Rules\n\n[Skill source](../SKILL.md)\n[Missing source](missing.md)\n",
        encoding="utf-8",
    )
    registry = tmp_path / "ecosystem-registry.json"
    registry.write_text(json.dumps({
        "schema_version": 1,
        "ecosystem_release": "1.0.0",
        "overview": {
            "enabled": True,
            "anchor_root": "research-project",
            "vault_marker": ".obsidian",
            "relative_path": "Skill完整指南/Skill与Plugin的总体系说明.md",
        },
        "guides": {
            "enabled": True,
            "anchor_root": "research-project",
            "vault_marker": ".obsidian",
            "relative_path": "Skill完整指南",
            "owner_directories": {
                "global": "global",
                "research": "research",
                "math-modeling": "modeling",
            },
        },
        "roots": {
            "research-project": {"kind": "authority", "path": str(project)},
            "agents-home": {"kind": "authority", "path": str(agents)},
        },
        "components": [
            {
                "id": "research.one", "kind": "skill", "owner": "research",
                "root": "research-project", "relative_path": "skills/one",
                "version": "1.0.0", "interface_version": "1.0.0",
                "status": "active", "requires": [], "runtime": [],
                "model_policy": "model-agnostic", "mirrors": [], "tests": [],
            },
            {
                "id": "global.two", "kind": "skill", "owner": "global",
                "root": "agents-home", "relative_path": "skills/two",
                "version": "1.1.0", "interface_version": "1.0.0",
                "status": "active", "requires": ["research.one"], "runtime": [],
                "model_policy": "model-agnostic", "mirrors": [], "tests": [],
            },
        ],
    }, ensure_ascii=False), encoding="utf-8")
    return registry, vault / "Skill完整指南" / "Skill与Plugin的总体系说明.md"


def marker(module, registry: Path, component_id: str, digest: str | None = None) -> str:
    data = module.load_registry(registry)
    component = next(item for item in data["components"] if item["id"] == component_id)
    source_hash = digest or module.source_tree_sha256(component, data)
    return f"<!-- ECOSYSTEM:SKILL id={component_id} source_sha256={source_hash} -->"


def test_sync_overview_changes_only_generated_block(tmp_path: Path) -> None:
    overview = load_overview()
    registry, note = make_registry(tmp_path)
    note.write_text(
        "# 标题\n\n人工说明\n\n"
        f"{marker(overview, registry, 'research.one')}\n\n"
        f"{marker(overview, registry, 'global.two')}\n\n"
        "<!-- ECOSYSTEM:AUTO:BEGIN -->\n旧\n<!-- ECOSYSTEM:AUTO:END -->\n",
        encoding="utf-8",
    )

    report = overview.sync_overview(registry)

    updated = note.read_text(encoding="utf-8")
    assert "人工说明" in updated
    assert "\n旧\n" not in updated
    assert "research.one" in updated
    assert "research.one --> global.two" in updated
    assert report["component_count"] == 2


def test_audit_rejects_missing_duplicate_and_stale_skill_markers(tmp_path: Path) -> None:
    overview = load_overview()
    registry, note = make_registry(tmp_path)
    stale = "0" * 64
    note.write_text(
        "# 标题\n\n"
        f"{marker(overview, registry, 'research.one', stale)}\n"
        f"{marker(overview, registry, 'research.one', stale)}\n"
        "<!-- ECOSYSTEM:AUTO:BEGIN -->\n旧\n<!-- ECOSYSTEM:AUTO:END -->\n",
        encoding="utf-8",
    )

    findings = overview.audit_overview(registry)

    assert {item.code for item in findings} == {
        "OVERVIEW_AUTO_DRIFT",
        "OVERVIEW_COMPONENT_DUPLICATE",
        "OVERVIEW_COMPONENT_MISSING",
        "OVERVIEW_SOURCE_STALE",
    }


def test_source_hash_tracks_skill_and_reference_but_ignores_tests(tmp_path: Path) -> None:
    overview = load_overview()
    registry, _ = make_registry(tmp_path)
    data = overview.load_registry(registry)
    component = next(item for item in data["components"] if item["id"] == "global.two")
    source = Path(data["roots"]["agents-home"]["path"]) / "skills" / "two"
    original = overview.source_tree_sha256(component, data)
    tests = source / "tests"
    tests.mkdir()
    (tests / "test_two.py").write_text("assert True\n", encoding="utf-8")
    assert overview.source_tree_sha256(component, data) == original
    (source / "references" / "rules.md").write_text("# Changed rules\n", encoding="utf-8")
    assert overview.source_tree_sha256(component, data) != original


def test_skillctl_sync_and_audit_commands_use_overview_config(tmp_path: Path) -> None:
    overview = load_overview()
    skillctl = load_skillctl()
    registry, note = make_registry(tmp_path)
    note.write_text(
        "# 标题\n\n"
        f"{marker(overview, registry, 'research.one')}\n"
        f"{marker(overview, registry, 'global.two')}\n"
        "<!-- ECOSYSTEM:AUTO:BEGIN -->\n旧\n<!-- ECOSYSTEM:AUTO:END -->\n",
        encoding="utf-8",
    )

    assert skillctl.main(["--registry", str(registry), "sync-overview"]) == 0
    assert skillctl.main(["--registry", str(registry), "sync-guides"]) == 0
    assert skillctl.main(["--registry", str(registry), "audit"]) == 0


def test_component_audit_blocks_stale_guide_and_overview(tmp_path: Path, capsys) -> None:
    overview = load_overview()
    skillctl = load_skillctl()
    registry, note = make_registry(tmp_path)
    note.write_text(
        "# 标题\n\n"
        f"{marker(overview, registry, 'research.one')}\n"
        f"{marker(overview, registry, 'global.two')}\n"
        "<!-- ECOSYSTEM:AUTO:BEGIN -->\n旧\n<!-- ECOSYSTEM:AUTO:END -->\n",
        encoding="utf-8",
    )
    overview.sync_overview(registry)
    overview.sync_guides(registry)
    data = overview.load_registry(registry)
    component = next(item for item in data["components"] if item["id"] == "global.two")
    source = Path(data["roots"][component["root"]]["path"]) / component["relative_path"]
    (source / "SKILL.md").write_text("# Two changed\n", encoding="utf-8")

    result = skillctl.main([
        "--registry", str(registry), "audit", "--json", "--components", "global.two"
    ])
    findings = json.loads(capsys.readouterr().out)

    assert result == 2
    assert {(item["code"], item["component_id"]) for item in findings} == {
        ("GUIDE_SOURCE_STALE", "global.two"),
        ("GUIDE_RENDER_DRIFT", "global.two"),
        ("OVERVIEW_SOURCE_STALE", "global.two"),
    }


def test_overview_config_is_part_of_release_fingerprint(tmp_path: Path) -> None:
    skillctl = load_skillctl()
    registry, _ = make_registry(tmp_path)
    first = skillctl.build_lock(registry)["registry_sha256"]
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["overview"]["relative_path"] = "另一份说明.md"
    registry.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    second = skillctl.build_lock(registry)["registry_sha256"]
    assert first != second


def test_guides_config_is_part_of_release_fingerprint(tmp_path: Path) -> None:
    skillctl = load_skillctl()
    registry, _ = make_registry(tmp_path)
    first = skillctl.build_lock(registry)["registry_sha256"]
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["guides"]["relative_path"] = "另一组指南"
    registry.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    second = skillctl.build_lock(registry)["registry_sha256"]
    assert first != second


def test_sync_guides_renders_skill_and_reference_content(tmp_path: Path) -> None:
    overview = load_overview()
    registry, _ = make_registry(tmp_path)

    report = overview.sync_guides(registry)

    global_guide = tmp_path / "vault" / "Skill完整指南" / "global" / "two-完整指南.md"
    research_guide = tmp_path / "vault" / "Skill完整指南" / "research" / "one-完整指南.md"
    assert report["component_count"] == 2
    assert global_guide.is_file()
    assert research_guide.is_file()
    rendered = global_guide.read_text(encoding="utf-8")
    assert "<!-- ECOSYSTEM:GUIDE id=global.two source_sha256=" in rendered
    assert "# two 完整指南" in rendered
    assert "## SKILL.md" in rendered
    assert "## references/rules.md" in rendered
    assert "# Two" in rendered
    assert "# Rules" in rendered
    import re
    target = re.search(r"\[Skill source\]\(#\^(source-[a-f0-9]+)\)", rendered).group(1)
    assert f"\n^{target}\n" in rendered
    assert "[Missing source](missing.md)" not in rendered
    assert "Missing source（源路径：`missing.md`）" in rendered


def test_sync_guides_updates_only_selected_component(tmp_path: Path) -> None:
    overview = load_overview()
    registry, _ = make_registry(tmp_path)
    overview.sync_guides(registry)
    global_guide = tmp_path / "vault" / "Skill完整指南" / "global" / "two-完整指南.md"
    research_guide = tmp_path / "vault" / "Skill完整指南" / "research" / "one-完整指南.md"
    global_before = global_guide.read_bytes()
    research_before = research_guide.read_bytes()
    data = overview.load_registry(registry)
    research_component = next(item for item in data["components"] if item["id"] == "research.one")
    research_source = Path(data["roots"][research_component["root"]]["path"]) / research_component["relative_path"]
    (research_source / "SKILL.md").write_text("# One changed\n", encoding="utf-8")

    report = overview.sync_guides(registry, ["research.one"])

    assert report["changed"] == ["research.one"]
    assert global_guide.read_bytes() == global_before
    assert research_guide.read_bytes() != research_before


def test_audit_guides_reports_missing_and_stale_guides(tmp_path: Path) -> None:
    overview = load_overview()
    registry, _ = make_registry(tmp_path)
    overview.sync_guides(registry)
    data = overview.load_registry(registry)
    global_component = next(item for item in data["components"] if item["id"] == "global.two")
    global_source = Path(data["roots"][global_component["root"]]["path"]) / global_component["relative_path"]
    (global_source / "references" / "rules.md").write_text("# Changed rules\n", encoding="utf-8")
    research_guide = tmp_path / "vault" / "Skill完整指南" / "research" / "one-完整指南.md"
    research_guide.unlink()

    findings = overview.audit_guides(registry)

    assert {(item.code, item.component_id) for item in findings} == {
        ("GUIDE_MISSING", "research.one"),
        ("GUIDE_RENDER_DRIFT", "global.two"),
        ("GUIDE_SOURCE_STALE", "global.two"),
    }
