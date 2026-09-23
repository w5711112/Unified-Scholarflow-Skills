from __future__ import annotations

import json
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
MANIFEST = PLUGIN_ROOT / "architecture-manifest.json"


def discover_skill_names() -> set[str]:
    return {
        path.name
        for path in (PLUGIN_ROOT / "skills").iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    }


def load_manifest_skills() -> dict[str, dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["skills"]


class CanonicalSkillTests(unittest.TestCase):
    def test_manifest_ids_match_canonical_skill_directories(self):
        registered = set(load_manifest_skills())
        discovered = discover_skill_names()

        self.assertEqual(registered, discovered)
        self.assertIn("searching-at-scale", discovered)
        self.assertEqual(len(discovered), 6)
        self.assertNotIn("obsidian-" + "research-voice", discovered)

    def test_skills_are_siblings_inside_one_plugin(self):
        for name in discover_skill_names():
            self.assertTrue(
                (PLUGIN_ROOT / "skills" / name / "SKILL.md").is_file(), name
            )
        self.assertFalse(
            (WORKSPACE_ROOT / "skill-with-plugin" / "zotero-obsidian-paper-import").exists()
        )

    def test_each_discovered_skill_has_one_registered_canonical_entrypoint(self):
        registered = load_manifest_skills()
        for name in discover_skill_names():
            canonical = PLUGIN_ROOT / "skills" / name / "SKILL.md"
            self.assertTrue(canonical.is_file(), name)
            self.assertEqual(registered[name]["entrypoint"], f"skills/{name}/SKILL.md")
            self.assertNotIn("mirror", registered[name])

    def test_manifest_has_no_surface_mirror_contract(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        discovered = discover_skill_names()

        self.assertEqual(set(data["skills"]), discovered)
        self.assertNotIn("mirrors", data)
        self.assertNotIn("sync_manifest_version", data)
        self.assertFalse(
            (WORKSPACE_ROOT / "drone-literature-scout-全量移植与跨Agent重建规范.md").exists()
        )


if __name__ == "__main__":
    unittest.main()
