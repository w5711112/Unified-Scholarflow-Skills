from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "release_tool.py"


def run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )


class ReleaseToolTests(unittest.TestCase):
    def make_source(self, root: Path) -> Path:
        source = root / "domain-scout"
        (source / "references").mkdir(parents=True)
        (source / "__pycache__").mkdir()
        (source / "SKILL.md").write_text(
            "---\nname: domain-scout\ndescription: Use when finding research.\n---\n"
            "# Domain scout\n\nRead [rules](references/rules.md).\n",
            encoding="utf-8",
        )
        (source / "references" / "rules.md").write_text(
            "Keep at least 20 approved sources.\n", encoding="utf-8"
        )
        (source / "old-draft.md").write_text("superseded draft\n", encoding="utf-8")
        (source / "__pycache__" / "x.pyc").write_bytes(b"cache")
        return source

    def write_profile(self, root: Path, *, drop: list[str] | None = None) -> Path:
        profile = root / "profile.json"
        profile.write_text(
            json.dumps(
                {
                    "package_name": "research-scout",
                    "confirmed_redundant": drop or [],
                    "keep_unreferenced": [],
                    "generalization": {
                        "topic": "user-configured research topic",
                        "whitelist_policy": "user supplies entries without lowering source-count constraints",
                    },
                }
            ),
            encoding="utf-8",
        )
        return profile

    def test_build_isolated_copy_excludes_generated_files_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = self.make_source(root)
            profile = self.write_profile(root, drop=["old-draft.md"])
            before = hashlib.sha256((source / "SKILL.md").read_bytes()).hexdigest()
            destination = root / "release"

            result = run_tool("build", "--source", str(source), "--profile", str(profile), "--output", str(destination))

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((destination / "research-scout" / "SKILL.md").exists())
            self.assertFalse((destination / "research-scout" / "__pycache__").exists())
            self.assertFalse((destination / "research-scout" / "old-draft.md").exists())
            self.assertEqual(before, hashlib.sha256((source / "SKILL.md").read_bytes()).hexdigest())
            self.assertTrue((destination / "release-manifest.json").exists())

    def test_audit_blocks_secret_and_machine_specific_path(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            package = root / "package"
            package.mkdir()
            secret = "ghp_" + "FAKE_TEST_TOKEN_NOT_A_REAL_KEY_01"
            private_path = "C:" + "\\Users\\private-user\\Documents\\Vault"
            (package / "SKILL.md").write_text(
                f"token={secret}\n"
                f"vault={private_path}\n",
                encoding="utf-8",
            )
            report = root / "audit.json"

            result = run_tool("audit", "--package", str(package), "--report", str(report))

            self.assertEqual(2, result.returncode)
            self.assertTrue(report.exists(), "audit command must create a machine-readable report")
            data = json.loads(report.read_text(encoding="utf-8"))
            kinds = {item["kind"] for item in data["blockers"]}
            self.assertIn("possible_secret", kinds)
            self.assertIn("machine_specific_path", kinds)

    def test_build_refuses_unresolved_semantic_orphan(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = self.make_source(root)
            profile = self.write_profile(root)

            result = run_tool("build", "--source", str(source), "--profile", str(profile), "--output", str(root / "release"))

            self.assertEqual(3, result.returncode)
            self.assertIn("old-draft.md", result.stderr)

    def test_validate_never_marks_remote_ready_without_explicit_confirmation_file(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = self.make_source(root)
            profile = self.write_profile(root, drop=["old-draft.md"])
            release = root / "release"
            self.assertEqual(0, run_tool("build", "--source", str(source), "--profile", str(profile), "--output", str(release)).returncode)

            result = run_tool("validate", "--release", str(release))

            self.assertEqual(4, result.returncode)
            self.assertIn("remote publication confirmation", result.stderr)

    def test_prepare_creates_lightweight_sanitized_package_and_public_docs(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "drone-helper"
            (source / "scripts").mkdir(parents=True)
            private_path = "C:" + "\\Users\\private-user\\Documents\\Private Vault\\notes"
            secret = "ghp_" + "FAKE_TEST_TOKEN_NOT_A_REAL_KEY_01"
            (source / "SKILL.md").write_text(
                "---\nname: drone-helper\ndescription: Helps with drone literature.\n---\n"
                f"# Drone helper\n\nKeep the drone preference. Topic: private-topic.\n"
                f"vault: {private_path}\nemail: person@private.test\ntoken={secret}\n",
                encoding="utf-8",
            )
            (source / "scripts" / "collect.py").write_text(
                "import os\nimport requests\n", encoding="utf-8"
            )
            (source / "notes.log").write_text("private runtime log", encoding="utf-8")
            profile = root / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "package_name": "drone-helper",
                        "redactions": [
                            {"find": "private-topic", "replace": "<YOUR_TOPIC>"}
                        ],
                        "required_integrations": [
                            {"name": "Browser", "requirement": "supported browser and required extension"},
                            {"name": "Zotero", "requirement": "Zotero plus the workflow connector plugin"},
                            {"name": "Codex", "requirement": "Codex with this Skill installed"},
                            {"name": "Obsidian", "requirement": "Obsidian with the required vault plugin"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            release = root / "release"

            result = run_tool(
                "prepare",
                "--source", str(source),
                "--profile", str(profile),
                "--output", str(release),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            package = release / "drone-helper"
            skill_text = (package / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("drone preference", skill_text)
            self.assertIn("<YOUR_TOPIC>", skill_text)
            self.assertNotIn("private-user", skill_text)
            self.assertNotIn("person@private.test", skill_text)
            self.assertNotIn(secret, skill_text)
            self.assertFalse((package / "notes.log").exists())
            self.assertTrue((package / "README.md").is_file())
            requirements = (package / "REQUIREMENTS.md").read_text(encoding="utf-8")
            self.assertIn("Python source files", requirements)
            self.assertIn("requests", requirements)
            self.assertIn("import name", requirements)
            for integration in ("Browser", "Zotero", "Codex", "Obsidian"):
                self.assertIn(integration, requirements)
            readme = (package / "README.md").read_text(encoding="utf-8")
            self.assertIn("Integration prerequisites", readme)
            audit = json.loads((release / "audit-report.json").read_text(encoding="utf-8"))
            self.assertTrue(audit["ok"])
            manifest = json.loads((release / "release-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("lightweight", manifest["mode"])
            self.assertGreaterEqual(manifest["redaction_counts"]["machine_specific_path"], 1)
            self.assertNotIn(str(source), json.dumps(manifest))
            self.assertFalse(manifest["remote_mutation_performed"])
            self.assertTrue((package / "scripts" / "collect.py").is_file())

    def test_prepare_needs_no_profile_and_preserves_existing_readme(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "simple-skill"
            source.mkdir()
            (source / "SKILL.md").write_text(
                "---\nname: simple-skill\ndescription: A small reusable skill.\n---\n# Simple\n",
                encoding="utf-8",
            )
            (source / "README.md").write_text("# Handwritten README\n", encoding="utf-8")
            release = root / "release"

            result = run_tool("prepare", "--source", str(source), "--output", str(release))

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                "# Handwritten README\n",
                (release / "simple-skill" / "README.md").read_text(encoding="utf-8"),
            )
            self.assertTrue((release / "simple-skill" / "REQUIREMENTS.md").is_file())

    def test_prepare_manifest_is_not_local_prepared_when_audit_fails(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "simple-skill"
            source.mkdir()
            (source / "SKILL.md").write_text(
                "---\nname: simple-skill\ndescription: A small reusable skill.\n---\n# Simple\nprivate-marker\n",
                encoding="utf-8",
            )
            profile = root / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "redactions": [
                            {"find": "private-marker", "replace": "person@private.test"}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            release = root / "release"

            result = run_tool(
                "prepare", "--source", str(source), "--profile", str(profile), "--output", str(release)
            )

            self.assertEqual(2, result.returncode)
            manifest = json.loads((release / "release-manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["local_prepared"])

    def test_prepare_rejects_unsafe_package_name(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "simple-skill"
            source.mkdir()
            (source / "SKILL.md").write_text(
                "---\nname: simple-skill\ndescription: A small reusable skill.\n---\n# Simple\n",
                encoding="utf-8",
            )
            profile = root / "profile.json"
            profile.write_text(json.dumps({"package_name": "../escaped"}), encoding="utf-8")

            result = run_tool(
                "prepare", "--source", str(source), "--profile", str(profile), "--output", str(root / "release")
            )

            self.assertEqual(3, result.returncode)
            self.assertIn("package_name", result.stderr)
            self.assertFalse((root / "escaped").exists())

    def test_validate_rejects_lightweight_package_even_with_confirmation(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "simple-skill"
            source.mkdir()
            (source / "SKILL.md").write_text(
                "---\nname: simple-skill\ndescription: A small reusable skill.\n---\n# Simple\n",
                encoding="utf-8",
            )
            release = root / "release"
            self.assertEqual(0, run_tool("prepare", "--source", str(source), "--output", str(release)).returncode)
            (release / "publication-confirmation.json").write_text(
                json.dumps(
                    {
                        "repository": "owner/repo",
                        "visibility": "public",
                        "branch": "main",
                        "target_path": ".",
                        "license": "MIT",
                        "approved": True,
                    }
                ),
                encoding="utf-8",
            )

            result = run_tool("validate", "--release", str(release))

            self.assertEqual(4, result.returncode)
            self.assertIn("lightweight", result.stderr)

    def test_prepare_path_redaction_preserves_surrounding_prose(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "simple-skill"
            source.mkdir()
            (source / "SKILL.md").write_text(
                "---\nname: simple-skill\ndescription: Small skill.\n---\n"
                "Use C:\\Users\\alice\\Vault\\notes for local storage.\n",
                encoding="utf-8",
            )
            release = root / "release"

            self.assertEqual(0, run_tool("prepare", "--source", str(source), "--output", str(release)).returncode)

            text = (release / "simple-skill" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("<USER_HOME>\\Vault\\notes for local storage.", text)

    def test_prepare_sanitizes_generated_readme_metadata(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "topic-skill"
            source.mkdir()
            (source / "SKILL.md").write_text(
                "---\nname: topic-skill\ndescription: Research private-topic efficiently.\n---\n# Topic\n",
                encoding="utf-8",
            )
            profile = root / "profile.json"
            profile.write_text(
                json.dumps({"redactions": [{"find": "private-topic", "replace": "<YOUR_TOPIC>"}]}),
                encoding="utf-8",
            )
            release = root / "release"

            self.assertEqual(
                0,
                run_tool("prepare", "--source", str(source), "--profile", str(profile), "--output", str(release)).returncode,
            )

            readme = (release / "topic-skill" / "README.md").read_text(encoding="utf-8")
            self.assertNotIn("private-topic", readme)
            self.assertIn("<YOUR_TOPIC>", readme)

    def test_prepare_rejects_output_inside_source(self):
        with tempfile.TemporaryDirectory() as name:
            source = Path(name) / "simple-skill"
            source.mkdir()
            (source / "SKILL.md").write_text(
                "---\nname: simple-skill\ndescription: Small skill.\n---\n# Simple\n",
                encoding="utf-8",
            )

            result = run_tool("prepare", "--source", str(source), "--output", str(source / "release"))

            self.assertEqual(3, result.returncode)
            self.assertIn("outside source", result.stderr)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_prepare_rejects_symbolic_links(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "simple-skill"
            source.mkdir()
            outside = root / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            (source / "SKILL.md").write_text(
                "---\nname: simple-skill\ndescription: Small skill.\n---\n# Simple\n",
                encoding="utf-8",
            )
            link = source / "linked.txt"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symbolic link creation unavailable: {exc}")

            result = run_tool("prepare", "--source", str(source), "--output", str(root / "release"))

            self.assertEqual(3, result.returncode)
            self.assertIn("symbolic link", result.stderr)


if __name__ == "__main__":
    unittest.main()
