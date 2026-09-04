import hashlib
import json
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
ENTRY = SKILL_ROOT / "SKILL.md"
FIXTURE = SKILL_ROOT / "tests" / "fixtures" / "SKILL.before-route-b.md"
AUTHORITY_MAP = SKILL_ROOT / "references" / "authority-map.json"
ENTRY_REFS = [
    "references/inventory-and-capability-matrix.md",
    "references/host-adapters-and-secrets.md",
    "references/validation-and-reporting.md",
]
MANIFEST_REFS = [f"skills/migration-skill/{ref}" for ref in ENTRY_REFS]
GOVERNANCE_CONTRACT = PLUGIN_ROOT / "references" / "governance-contract.md"
GOVERNANCE_CLI = PLUGIN_ROOT / "scripts" / "skillctl.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MigrationRouteBArchitectureTests(unittest.TestCase):
    def test_legacy_fixture_is_compact_and_exact(self):
        authority = json.loads(AUTHORITY_MAP.read_text(encoding="utf-8"))
        self.assertEqual(sha256(FIXTURE), authority["compact_fixture_sha256"])
        self.assertLessEqual(FIXTURE.stat().st_size, 4096)
        self.assertTrue(FIXTURE.read_text(encoding="utf-8").startswith("---\nname:"))

    def test_manifest_declares_modular_runtime_contract(self):
        manifest = json.loads((PLUGIN_ROOT / "architecture-manifest.json").read_text(encoding="utf-8"))
        self.assertIn("migration-skill", manifest["skills"])
        registry = json.loads((PLUGIN_ROOT / "ecosystem-registry.json").read_text(encoding="utf-8"))
        item = next(component for component in registry["components"] if component["id"] == "global.migration-skill")
        self.assertEqual(item["interface_version"], "1.0.0")
        self.assertEqual(item["relative_path"], "plugins/sources/skill-governance-plugin/skills/migration-skill")
        self.assertEqual(item["requires"], ["global.collect-bug-update-accelerate"])
        self.assertEqual(item["tests"], ["plugins/sources/skill-governance-plugin/skills/migration-skill/tests/test_route_b_architecture.py"])

    def test_entry_routes_once_and_declares_single_evidence_spine(self):
        text = ENTRY.read_text(encoding="utf-8")
        for ref in ENTRY_REFS:
            self.assertEqual(text.count(ref), 1, ref)
            self.assertTrue((SKILL_ROOT / ref).is_file(), ref)
        for evidence_id in ("MIGRATION_BASELINE", "CAPABILITY_MAP", "MIGRATION_ACCEPTANCE"):
            self.assertIn(evidence_id, text)
        self.assertIn("同一证据边界", text)
        self.assertIn("只完整读取一次", text)

    def test_declared_governance_dependencies_are_readable(self):
        """A moved Skill must name only dependency paths resolvable in this plugin."""
        text = ENTRY.read_text(encoding="utf-8")
        self.assertIn("../../references/governance-contract.md", text)
        self.assertTrue(GOVERNANCE_CONTRACT.is_file())
        self.assertIn("../../scripts/skillctl.py audit --json", text)
        self.assertTrue(GOVERNANCE_CLI.is_file())
        self.assertNotIn("../../references/skill-collaboration-contract.md", text)
        self.assertNotIn("scripts/check_sync.py", text)

    def test_lossless_authority_map_and_critical_contract(self):
        authority = json.loads(AUTHORITY_MAP.read_text(encoding="utf-8"))
        self.assertEqual(authority["compact_fixture_sha256"], sha256(FIXTURE))
        self.assertEqual(authority["unmapped_removed_blocks"], [])
        combined = ENTRY.read_text(encoding="utf-8") + "\n" + "\n".join(
            (SKILL_ROOT / ref).read_text(encoding="utf-8") for ref in ENTRY_REFS
        )
        required = [
            "不得宣称无损兼容",
            "scripts、references、assets、fixtures 和 tests",
            "只复制 `SKILL.md`",
            "API key、token、cookie、浏览器登录态、OAuth 凭据",
            "文件级验收",
            "能力级验收",
            "行为级验收",
            "一个正常场景、一个边界场景和一个失败场景",
            "互为字节级镜像",
            "必须调用** `obsidian-note-style`",
        ]
        for phrase in required:
            self.assertIn(phrase, combined, phrase)


if __name__ == "__main__":
    unittest.main()
