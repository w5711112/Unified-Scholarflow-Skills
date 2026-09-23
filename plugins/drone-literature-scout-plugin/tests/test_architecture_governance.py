from __future__ import annotations

import json
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PLUGIN_ROOT / "architecture-manifest.json"
GUARD = PLUGIN_ROOT / "AGENTS.md"
EXPECTED = {
    "searching-at-scale",
    "drone-literature-scout",
    "zotero-obsidian-paper-import",
    "read-paper-analysis-highlight",
    "obsidian-note-style",
    "draw-style",
}
GLOBAL_PROVIDERS = {
    "global.collect-bug-update-accelerate",
    "global.migration-skill",
    "global.renhua",
}


def discover_skills() -> set[str]:
    return {
        path.name
        for path in (PLUGIN_ROOT / "skills").iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    }


class ArchitectureGovernanceTests(unittest.TestCase):
    def test_research_plugin_has_exactly_six_domain_skills_and_a_coherent_release(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        plugin = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(discover_skills(), EXPECTED)
        self.assertEqual(set(data["skills"]), EXPECTED)
        self.assertEqual(plugin["version"], data["release_version"])
        self.assertEqual(data["architecture_version"], "2.1.0")
        self.assertEqual(data["release_version"].split("+")[0], "2.1.0")

    def test_structure_manifest_registers_canonical_skills_without_mirrors(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertFalse((PLUGIN_ROOT / "sync-manifest.json").exists())
        self.assertNotIn("sync_manifest_version", data)
        self.assertNotIn("mirrors", data)
        self.assertNotIn("mirror_mode", data["policies"])
        for name, skill in data["skills"].items():
            self.assertEqual(skill["entrypoint"], f"skills/{name}/SKILL.md")
            self.assertNotIn("mirror", skill)
        self.assertEqual(set(data["provider_edges"]), GLOBAL_PROVIDERS)
        self.assertIn("pytest", data["test_entrypoints"]["command"])
        self.assertEqual(data["numeric_guards"]["source"], "skills.*.numeric_guards")
        self.assertNotIn("C:/Users/YOURNAME", MANIFEST.read_text(encoding="utf-8"))

    def test_domain_numeric_guards_and_existing_interfaces_are_retained(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        zotero = data["skills"]["zotero-obsidian-paper-import"]
        self.assertEqual(zotero["numeric_guards"]["batch_count"], 91)
        self.assertEqual(zotero["calls"]["failure"], ["global.collect-bug-update-accelerate"])
        search = data["skills"]["searching-at-scale"]
        self.assertEqual(search["numeric_guards"]["marketplace_candidate_minimum"], 6000)
        self.assertIn("global.migration-skill", search["calls"]["conditional"])

    def test_reviewed_domain_contracts_keep_canonical_authority(self):
        zotero = (PLUGIN_ROOT / "skills" / "zotero-obsidian-paper-import" / "SKILL.md").read_text(encoding="utf-8")
        drone = (PLUGIN_ROOT / "skills" / "drone-literature-scout" / "SKILL.md").read_text(encoding="utf-8")
        read_paper = (PLUGIN_ROOT / "skills" / "read-paper-analysis-highlight" / "SKILL.md").read_text(encoding="utf-8")
        obsidian = (PLUGIN_ROOT / "skills" / "obsidian-note-style" / "SKILL.md").read_text(encoding="utf-8")
        for text in (zotero, drone, read_paper, obsidian):
            self.assertNotIn("sync-manifest.json", text)
            self.assertNotIn("双向同步", text)
            self.assertNotIn("互为字节级镜像", text)
            self.assertNotIn("修改任一侧", text)
            self.assertIn("canonical", text)
            self.assertIn("canonical", text)
        self.assertNotIn("八个 skills", drone)
        self.assertIn("六个领域 Skill", drone)

    def test_readme_declares_canonical_and_aggregate_overview(self):
        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        for phrase in (
            "architecture-manifest.json",
            "canonical `SKILL.md`",
            "Skill与Plugin的总体系说明",
            "Skill完整指南/research/",
        ):
            self.assertIn(phrase, readme)
        for retired in ("check_sync.py", "完整指南镜像", "字节级镜像"):
            self.assertNotIn(retired, readme)

    def test_mandatory_references_name_the_global_incident_provider(self):
        references = (
            PLUGIN_ROOT / "skills" / "obsidian-note-style" / "references" / "workflow-and-acceptance.md",
            PLUGIN_ROOT / "skills" / "read-paper-analysis-highlight" / "references" / "identity-state-and-capability-contract.md",
            PLUGIN_ROOT / "skills" / "read-paper-analysis-highlight" / "references" / "pdf-annotation-contract.md",
        )
        for path in references:
            text = path.read_text(encoding="utf-8")
            self.assertIn("global.collect-bug-update-accelerate", text, path.name)
            self.assertNotIn("`collect-bug-update-accelerate`", text, path.name)

    def test_guard_blocks_silent_architecture_and_numeric_drift(self):
        text = GUARD.read_text(encoding="utf-8")
        for phrase in (
            "architecture-manifest.json",
            "用户明确批准",
            "不得静默减少数值护栏",
            "聚合总览",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
