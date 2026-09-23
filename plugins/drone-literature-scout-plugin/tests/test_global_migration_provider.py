from __future__ import annotations

import json
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PLUGIN_ROOT.parents[1]


def test_research_consumers_resolve_migration_through_the_global_provider() -> None:
    """A retired local migration source must not remain a research provider."""
    manifest = json.loads(
        (PLUGIN_ROOT / "architecture-manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["shared_contracts"]["global_migration_provider"] == "global.migration-skill"
    assert "migration-skill" not in manifest["skills"]
    assert "governance.migration-skill" not in manifest["skills"]
    for consumer in ("drone-literature-scout", "searching-at-scale"):
        calls = manifest["skills"][consumer]["calls"]["conditional"]
        assert "global.migration-skill" in calls
        assert "migration-skill" not in calls
        assert "governance.migration-skill" not in calls

    assert not (PLUGIN_ROOT / "skills" / "migration-skill").exists()
    assert not (PROJECT_ROOT / "migration-skill-完整指南.md").exists()
