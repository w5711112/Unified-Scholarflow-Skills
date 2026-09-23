from __future__ import annotations

import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE_ROOT = Path.home() / ".agents" / "plugins" / "sources" / "skill-governance-plugin"
SKILL = GOVERNANCE_ROOT / "skills" / "migration-skill" / "SKILL.md"


class MigrationSkillContractTests(unittest.TestCase):
    def test_research_declares_a_resolvable_global_migration_provider(self):
        import json

        manifest = json.loads(
            (PLUGIN_ROOT / "architecture-manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["shared_contracts"]["global_migration_provider"],
            "global.migration-skill",
        )
        self.assertIn("global.migration-skill", manifest["provider_edges"])
        for consumer in ("drone-literature-scout", "searching-at-scale"):
            self.assertIn(
                "global.migration-skill",
                manifest["skills"][consumer]["calls"]["conditional"],
            )

    def test_global_provider_exposes_a_skill_interface_without_local_archive(self):
        self.assertTrue(SKILL.is_file(), SKILL)
        frontmatter = SKILL.read_text(encoding="utf-8").split("---", 2)[1]
        self.assertIn("name: migration-skill", frontmatter)
        self.assertIn("description: Use when", frontmatter)
        self.assertFalse((PLUGIN_ROOT / "skills" / "migration-skill").exists())


if __name__ == "__main__":
    unittest.main()
