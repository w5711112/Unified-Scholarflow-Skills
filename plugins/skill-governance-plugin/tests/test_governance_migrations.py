import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_REGISTRY = ROOT / "ecosystem-registry.json"


def _production_components() -> dict[str, dict]:
    registry = json.loads(PRODUCTION_REGISTRY.read_text(encoding="utf-8"))
    return {component["id"]: component for component in registry["components"]}


def test_migration_and_publish_are_distinct_components() -> None:
    """A host migration and a GitHub release must never become one workflow."""
    migration = (ROOT / "skills/migration-skill/SKILL.md").read_text(encoding="utf-8")
    publish = (ROOT / "skills/github-upload/SKILL.md").read_text(encoding="utf-8")
    assert "三层验收" in migration
    assert "GitHub" not in migration.split("不负责")[0]
    assert "隐私" in publish and "发布" in publish
    assert "跨宿主能力等价" not in publish.split("不负责")[0]


def test_governance_skills_use_only_registered_canonical_sources() -> None:
    registry = json.loads(PRODUCTION_REGISTRY.read_text(encoding="utf-8"))
    components = _production_components()
    for component_id in (
        "global.collect-bug-update-accelerate",
        "global.migration-skill",
        "global.workspace-hygiene",
        "global.github-upload",
    ):
        component = components[component_id]
        canonical = Path(registry["roots"][component["root"]]["path"]) / component["relative_path"]
        assert component["mirrors"] == []
        assert (canonical / "SKILL.md").is_file()


def test_migration_and_github_upload_keep_independent_global_boundaries() -> None:
    """Production registry consumers must not revive the retired migration owner."""
    components = _production_components()
    migration = components["global.migration-skill"]
    github_upload = components["global.github-upload"]

    assert migration["owner"] == github_upload["owner"] == "global"
    assert migration["relative_path"] != github_upload["relative_path"]
    assert "global.github-upload" not in migration["requires"]
    assert "global.migration-skill" not in github_upload["requires"]
    assert "governance.migration-skill" not in components

    research_plugin = components["research.drone-literature-scout-plugin"]
    assert "global.migration-skill" in research_plugin["requires"]
    assert "governance.migration-skill" not in research_plugin["requires"]

    routing = json.loads(
        (
            ROOT
            / "skills/collect-bug-update-accelerate/references/improvement-routing.json"
        ).read_text(encoding="utf-8")
    )
    migration_route = next(
        route for route in routing["routes"] if route["component_prefixes"] == ["migration"]
    )
    assert migration_route["owner_component"] == "global.migration-skill"

    migration_text = (ROOT / "skills/migration-skill/SKILL.md").read_text(encoding="utf-8")
    github_upload_text = (ROOT / "skills/github-upload/SKILL.md").read_text(encoding="utf-8")
    assert "global.github-upload" not in migration_text
    assert "global.migration-skill" not in github_upload_text
    assert not any(
        "github-upload" in source.read_text(encoding="utf-8")
        for source in (ROOT / "skills/migration-skill").rglob("*.py")
    )
    assert not any(
        "migration-skill" in source.read_text(encoding="utf-8")
        for source in (ROOT / "skills/github-upload").rglob("*.py")
    )
