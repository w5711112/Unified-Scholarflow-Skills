from __future__ import annotations

import importlib.util
import json
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE_ROOT = Path.home() / ".agents" / "plugins" / "sources" / "skill-governance-plugin"
INSTALLER_PATH = PLUGIN_ROOT / "scripts" / "install_project_incident_guards.py"
SCOPE_PATH = GOVERNANCE_ROOT / "skills" / "collect-bug-update-accelerate" / "references" / "project-scope.json"
TEMPLATE_PATH = SCOPE_PATH.with_name("project-incident-guard.md")

import sys
sys.path.insert(0, str(GOVERNANCE_ROOT / "skills" / "collect-bug-update-accelerate" / "scripts"))

spec = importlib.util.spec_from_file_location("install_project_incident_guards", INSTALLER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("guard installer module must be loadable")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

import incident_registry as registry_module


@contextmanager
def writable_project_directory():
    base = Path(__file__).resolve().parent / ".tmp-project-incident-guard"
    base.mkdir(exist_ok=True)
    target = base / uuid.uuid4().hex
    target.mkdir()
    try:
        yield target
    finally:
        shutil.rmtree(target)
        if not any(base.iterdir()):
            base.rmdir()


def make_scope(project_root: Path) -> dict:
    return {
        "schema_version": 1,
        "approved_project_roots": [str(project_root.resolve())],
        "incident_provider": {
            "component_id": "global.collect-bug-update-accelerate",
            "script_name": "incident_registry.py",
        },
        "public_registry_path": str(
            (
                PLUGIN_ROOT.parent
                / "运行数据"
                / "collect-bug-update-accelerate"
                / "incident-registry.json"
            ).resolve()
        ),
        "local_registry_relative_path": ".codex-runtime/collect-bug-update-accelerate/incident-registry.json",
        "exclusions": ["ordinary-chatgpt-chats", "projectless-tasks", "other-projects"],
    }


class ProjectIncidentGuardTests(unittest.TestCase):
    def test_provider_is_resolved_from_bootstrap_registry_by_component_id(self):
        provider = installer.resolve_incident_provider()
        self.assertEqual(provider["component_id"], "global.collect-bug-update-accelerate")
        self.assertEqual(provider["script_name"], "incident_registry.py")
        self.assertTrue(provider["skillctl"].is_file())
        self.assertTrue(provider["script_root"].is_dir())
        self.assertIn("ecosystem-registry.json", str(installer.BOOTSTRAP_REGISTRY))
    def test_scope_matches_current_approved_projects(self):
        scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            scope["approved_project_roots"],
            [
                r"C:/path/to/vault",
                r"D:/path/to/share\AIM\<YOUR_TOPIC>",
                r"C:/path/to/vault/project",
                r"D:/path/to/share\AIM\<YOUR_TOPIC>\kimi调整",
                r"C:/path/to/vault/project",
            ],
        )
        self.assertEqual(len(set(scope["approved_project_roots"])), 5)
        self.assertEqual(
            scope["incident_provider"],
            {"component_id": "global.collect-bug-update-accelerate", "script_name": "incident_registry.py"},
        )
        self.assertTrue(Path(scope["public_registry_path"]).is_absolute())
        self.assertEqual(
            scope["local_registry_relative_path"],
            ".codex-runtime/collect-bug-update-accelerate/incident-registry.json",
        )
        self.assertEqual(
            set(scope["exclusions"]),
            {"ordinary-chatgpt-chats", "projectless-tasks", "other-projects"},
        )

    def test_rendered_guard_contains_the_complete_lightweight_contract(self):
        with writable_project_directory() as project_root:
            scope = make_scope(project_root)
            rendered = installer.render_guard(project_root, scope)
            for required in (
                "Normal success: do not query or write any registry.",
                "Known fragile route: preflight local first, then public read-only.",
                "Real failure: capture-event before changing route.",
                "Missing dependency: when package identity and the active environment are explicit, install and verify it before retrying the original route; do not bypass it.",
                "Successful capture: append conversation_notice once inside the next natural progress commentary; never send a standalone incident message.",
                "Conversation notice stays brief; event id, status, and route remain in the registry only.",
                "Conversation summary: the whole notice including brackets is at most 96 characters, contains Chinese, and is never ellipsis-truncated; legacy calls use the local Chinese classifier.",
                "Repeated failure: reuse the incident id internally and append a fresh brief notice.",
                "Capture failure: append a brief not-recorded note inside natural progress commentary; never claim success.",
                "Never send cross-task messages solely to announce guard or notice changes.",
                "No daemon, file watcher, or per-tool wrapper is authorized.",
                "No network translation, daemon, watcher, or registry field is authorized.",
                "Never repeat the same failed route and parameters unchanged.",
                "Verified resolution: one successful effect-verified solution is an immediate temporary candidate; no occurrence or reuse threshold.",
                "Candidate review: after a new solution, reuse result, or regression, query promotion-candidates; load promotion_audit.py only when nonempty.",
                "Before final answer: backfill every unrecorded failed/declined/nonzero/validation item.",
                "If inherited guards overlap, the deepest approved project root owns the local registry.",
                "ordinary ChatGPT chats, projectless tasks, and other projects are excluded",
                installer.BEGIN_MARKER,
                installer.END_MARKER,
                str(GOVERNANCE_ROOT / "scripts" / "skillctl.py"),
                "global.collect-bug-update-accelerate",
                "incident_registry.py",
                scope["public_registry_path"],
                str(
                    project_root
                    / ".codex-runtime"
                    / "collect-bug-update-accelerate"
                    / "incident-registry.json"
                ),
                '--notice-summary "<brief Chinese problem summary>"',
            ):
                self.assertIn(required, rendered)
            self.assertNotIn(
                str(
                    project_root
                    / ".codex"
                    / "collect-bug-update-accelerate"
                    / "incident-registry.json"
                ),
                rendered,
            )

    def test_merge_is_idempotent_and_preserves_existing_agents_text(self):
        with writable_project_directory() as project_root:
            rendered = installer.render_guard(project_root, make_scope(project_root))
            existing = "# Existing project rules\n\nKeep this text.\n"
            once = installer.merge_managed_block(existing, rendered)
            twice = installer.merge_managed_block(once, rendered)
            self.assertEqual(twice, once)
            self.assertTrue(once.startswith(existing.rstrip()))
            self.assertIn("Keep this text.", once)
            self.assertEqual(once.count(installer.BEGIN_MARKER), 1)
            self.assertEqual(once.count(installer.END_MARKER), 1)

    def test_apply_preserves_agents_and_initializes_valid_empty_local_registry(self):
        with writable_project_directory() as project_root:
            agents_path = project_root / "AGENTS.md"
            agents_path.write_text("# Existing\n\nDo not remove.\n", encoding="utf-8")
            scope = make_scope(project_root)
            first = installer.apply_project_guard(project_root, scope, apply=True)
            second = installer.apply_project_guard(project_root, scope, apply=True)
            self.assertTrue(first["agents_changed"])
            self.assertTrue(first["registry_created"])
            self.assertFalse(second["agents_changed"])
            self.assertFalse(second["registry_created"])
            agents = agents_path.read_text(encoding="utf-8")
            self.assertIn("Do not remove.", agents)
            self.assertEqual(agents.count(installer.BEGIN_MARKER), 1)
            registry_path = (
                project_root
                / ".codex-runtime"
                / "collect-bug-update-accelerate"
                / "incident-registry.json"
            )
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertEqual(registry["schema_version"], 2)
            self.assertEqual(registry["incidents"], [])

    def test_apply_migrates_a_valid_nonempty_legacy_registry(self):
        with writable_project_directory() as project_root:
            legacy_path = (
                project_root
                / ".codex"
                / "collect-bug-update-accelerate"
                / "incident-registry.json"
            )
            legacy, _ = registry_module.capture_incident(
                registry_module.empty_registry(),
                {
                    "component": "legacy-probe",
                    "symptom_signature": "legacy registry contains one incident",
                    "environment": {"os": "windows"},
                },
                now="2026-07-30T00:00:00+08:00",
            )
            registry_module.save_registry_atomic(legacy_path, legacy)

            report = installer.apply_project_guard(
                project_root, make_scope(project_root), apply=True
            )

            migrated = registry_module.load_registry(Path(report["local_registry"]))
            self.assertEqual(migrated["incidents"], legacy["incidents"])
            self.assertTrue(report["legacy_registry_migrated"])

    def test_existing_new_registry_may_be_an_exact_superset_of_legacy(self):
        with writable_project_directory() as project_root:
            legacy_path = (
                project_root
                / ".codex"
                / "collect-bug-update-accelerate"
                / "incident-registry.json"
            )
            new_path = (
                project_root
                / ".codex-runtime"
                / "collect-bug-update-accelerate"
                / "incident-registry.json"
            )
            legacy, _ = registry_module.capture_incident(
                registry_module.empty_registry(),
                {
                    "component": "legacy-probe",
                    "symptom_signature": "legacy incident is preserved",
                    "environment": {"os": "windows"},
                },
                now="2026-07-30T00:00:00+08:00",
            )
            current, _ = registry_module.capture_incident(
                legacy,
                {
                    "component": "new-probe",
                    "symptom_signature": "new registry has one extra incident",
                    "environment": {"os": "windows"},
                },
                now="2026-07-30T00:01:00+08:00",
            )
            registry_module.save_registry_atomic(legacy_path, legacy)
            registry_module.save_registry_atomic(new_path, current)

            report = installer.apply_project_guard(
                project_root, make_scope(project_root), apply=False
            )

            self.assertFalse(report["registry_missing"])
            self.assertFalse(report["legacy_registry_migrated"])

    def test_check_mode_is_read_only_and_outsider_is_refused(self):
        with writable_project_directory() as project_root:
            scope = make_scope(project_root)
            report = installer.apply_project_guard(project_root, scope, apply=False)
            self.assertTrue(report["agents_change_needed"])
            self.assertTrue(report["registry_missing"])
            self.assertFalse((project_root / "AGENTS.md").exists())
            self.assertFalse((project_root / ".codex-runtime").exists())
            outsider = project_root / "not-approved"
            outsider.mkdir()
            with self.assertRaises(ValueError):
                installer.apply_project_guard(outsider, scope, apply=True)


if __name__ == "__main__":
    unittest.main()
