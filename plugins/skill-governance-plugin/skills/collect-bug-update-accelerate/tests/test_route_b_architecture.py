import hashlib
import json
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = Path(__file__).resolve().parents[3]


class CollectRouteBArchitectureTests(unittest.TestCase):
    def test_legacy_fixture_is_compact_and_exact(self):
        fixture = SKILL_ROOT / "tests" / "fixtures" / "SKILL.before-route-b.md"
        authority = json.loads((SKILL_ROOT / "references" / "authority-map.json").read_text(encoding="utf-8"))
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), authority["compact_fixture_sha256"])
        self.assertLessEqual(fixture.stat().st_size, 4096)
        self.assertTrue(fixture.read_text(encoding="utf-8").startswith("---\nname:"))

    def test_governance_manifest_and_hygiene_boundary(self):
        manifest = json.loads((PLUGIN_ROOT / "architecture-manifest.json").read_text(encoding="utf-8"))
        self.assertIn("collect-bug-update-accelerate", manifest["skills"])
        entry = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("HYGIENE_REQUEST", entry)
        self.assertIn("HYGIENE_RESULT", entry)
        self.assertNotIn("vault-maintenance-contract.md", entry)

    def test_removed_cleanup_authority_has_global_provider_owner(self):
        authority = json.loads((SKILL_ROOT / "references" / "authority-map.json").read_text(encoding="utf-8"))
        targets = [target for mapping in authority["mappings"] for target in mapping["authoritative_targets"]]
        self.assertIn("provider:global.workspace-hygiene", targets)
        self.assertNotIn("vault-maintenance-contract.md", targets)
        self.assertEqual(authority["unmapped_removed_blocks"], [])

    def test_scope_uses_component_identity(self):
        scope = json.loads((SKILL_ROOT / "references" / "project-scope.json").read_text(encoding="utf-8"))
        self.assertEqual(scope["incident_provider"], {"component_id": "global.collect-bug-update-accelerate", "script_name": "incident_registry.py"})
