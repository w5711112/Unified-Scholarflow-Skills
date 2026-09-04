from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import authority_contract as core


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def minimal_contract(root: Path) -> dict:
    skill = root / "SKILL.md"
    artifact = root / "paper.docx"
    record = root / "inspection.json"
    skill.write_text(
        "# Rules\n\n- Keep original Skill authoritative.\n",
        encoding="utf-8",
    )
    artifact.write_bytes(b"paper")
    record.write_text('{"result":"pass"}', encoding="utf-8")
    source_text = skill.read_text(encoding="utf-8").splitlines()[2]
    return {
        "schema_version": 3,
        "contract_authority": "record_only",
        "task": {"task_root": str(root.resolve())},
        "scope": {
            "authorized_roots": [
                {"path": str(root.resolve()), "kind": "directory"}
            ],
            "exclusions": [],
        },
        "sources": [
            {
                "id": "SRC-001",
                "path": str(skill.resolve()),
                "sha256": digest(skill),
                "read_complete": True,
                "mandatory_reference_ids": [],
            }
        ],
        "requirements": [
            {
                "id": "REQ-001",
                "source_id": "SRC-001",
                "anchor": {
                    "start_line": 3,
                    "end_line": 3,
                    "source_text": source_text,
                    "sha256": text_digest(source_text),
                },
                "stage": "writing",
                "applicability": "applicable",
                "dependencies": [],
                "evidence_ids": ["EV-001"],
            }
        ],
        "evidence": [
            {
                "id": "EV-001",
                "requirement_id": "REQ-001",
                "kind": "artifact_inspection",
                "source_sha256": digest(skill),
                "target_path": str(artifact.resolve()),
                "target_sha256": digest(artifact),
                "record_path": str(record.resolve()),
                "record_sha256": digest(record),
                "result": "pass",
            }
        ],
        "gates": [
            {"id": "G0", "requirement_ids": ["REQ-001"]},
            {"id": "G1", "requirement_ids": []},
            {"id": "G2", "requirement_ids": []},
            {"id": "G3", "requirement_ids": []},
            {"id": "G4", "requirement_ids": []},
            {"id": "G5", "requirement_ids": []},
        ],
        "observed_paths": [
            str(skill.resolve()),
            str(artifact.resolve()),
            str(record.resolve()),
        ],
        "forward_audit": None,
    }


class ThinAuthorityContractTests(unittest.TestCase):
    def evaluate(self, data: dict, root: Path, phase: str = "work"):
        contract_path = root / ".skill-contract" / "contract.json"
        contract_path.parent.mkdir(exist_ok=True)
        rendered_contract = str(contract_path.resolve())
        if rendered_contract not in data["observed_paths"]:
            data["observed_paths"].append(rendered_contract)
        contract_path.write_text(
            json.dumps(data, ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            return core.validate_contract(data, contract_path, phase)
        except (AttributeError, TypeError) as exc:
            self.fail(f"thin contract API is unavailable: {exc}")

    @staticmethod
    def codes(errors) -> set[str]:
        return {
            item.code if hasattr(item, "code") else str(item).split(":", 1)[0]
            for item in errors
        }

    def test_valid_current_contract_passes_work(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.assertEqual([], self.evaluate(minimal_contract(root), root))

    def test_unread_source_fails(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            data["sources"][0]["read_complete"] = False
            self.assertIn("SOURCE_UNREAD", self.codes(self.evaluate(data, root)))

    def test_changed_source_hash_invalidates_evidence(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            Path(data["sources"][0]["path"]).write_text(
                "changed",
                encoding="utf-8",
            )
            self.assertIn(
                "SOURCE_HASH_MISMATCH",
                self.codes(self.evaluate(data, root)),
            )

    def test_changed_anchor_text_fails(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            source = Path(data["sources"][0]["path"])
            source.write_text("# Rules\n\n- Changed rule.\n", encoding="utf-8")
            new_sha = digest(source)
            data["sources"][0]["sha256"] = new_sha
            data["evidence"][0]["source_sha256"] = new_sha
            self.assertIn(
                "REQUIREMENT_ANCHOR_INVALID",
                self.codes(self.evaluate(data, root)),
            )

    def test_requirement_without_real_anchor_fails(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            data["requirements"][0]["anchor"]["start_line"] = 99
            data["requirements"][0]["anchor"]["end_line"] = 99
            self.assertIn(
                "REQUIREMENT_ANCHOR_INVALID",
                self.codes(self.evaluate(data, root)),
            )

    def test_moved_contract_cannot_reuse_old_task_root(self):
        with (
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            data = minimal_contract(Path(first))
            moved = Path(second) / ".skill-contract" / "contract.json"
            moved.parent.mkdir()
            moved.write_text(json.dumps(data), encoding="utf-8")
            try:
                errors = core.validate_contract(data, moved, "work")
            except (AttributeError, TypeError) as exc:
                self.fail(f"thin contract API is unavailable: {exc}")
            self.assertIn("TASK_ROOT_MISMATCH", self.codes(errors))

    def test_pending_requirement_blocks_due_gate(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            data["requirements"][0]["applicability"] = "pending"
            self.assertIn(
                "GATE_PENDING",
                self.codes(self.evaluate(data, root, "pre_artifact")),
            )

    def test_verified_receipt_cannot_bypass_pending_dependency(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            upstream = json.loads(json.dumps(data["requirements"][0]))
            upstream["id"] = "REQ-UPSTREAM"
            upstream["applicability"] = "pending"
            upstream["evidence_ids"] = []
            data["requirements"][0]["dependencies"] = ["REQ-UPSTREAM"]
            data["requirements"].append(upstream)
            data["gates"][4]["requirement_ids"] = ["REQ-UPSTREAM"]
            errors = self.evaluate(data, root, "pre_artifact")
            self.assertIn("GATE_PENDING", self.codes(errors))

    def test_old_target_hash_blocks_gate(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            Path(data["evidence"][0]["target_path"]).write_bytes(b"new paper")
            self.assertIn(
                "EVIDENCE_TARGET_STALE",
                self.codes(self.evaluate(data, root, "pre_artifact")),
            )

    def test_not_applicable_requires_negative_branch_receipt(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            data["requirements"][0]["applicability"] = "not_applicable"
            data["requirements"][0]["evidence_ids"] = []
            data["evidence"] = []
            self.assertIn(
                "NEGATIVE_BRANCH_EVIDENCE_REQUIRED",
                self.codes(self.evaluate(data, root, "pre_artifact")),
            )

    def test_applicable_requirement_rejects_negative_branch_receipt(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            data["evidence"][0]["kind"] = "negative_branch"
            data["evidence"][0]["fact_record_path"] = data["evidence"][0]["record_path"]
            data["evidence"][0]["fact_record_sha256"] = data["evidence"][0]["record_sha256"]
            data["evidence"][0]["inspection_record_path"] = data["evidence"][0]["record_path"]
            data["evidence"][0]["inspection_record_sha256"] = data["evidence"][0]["record_sha256"]
            errors = self.evaluate(data, root, "pre_artifact")
            self.assertIn("GATE_PENDING", self.codes(errors))

    def test_user_decision_change_invalidates_dependents(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            child = json.loads(json.dumps(data["requirements"][0]))
            child["id"] = "REQ-002"
            child["dependencies"] = ["REQ-001"]
            child["evidence_ids"] = []
            data["requirements"].append(child)
            data["gates"][0]["requirement_ids"].append("REQ-002")
            changed = {
                str(Path(data["evidence"][0]["record_path"]).resolve())
            }
            try:
                updated, affected = core.invalidate_contract(data, changed)
            except (AttributeError, TypeError) as exc:
                self.fail(f"thin invalidation API is unavailable: {exc}")
            self.assertEqual({"REQ-001", "REQ-002"}, affected)
            self.assertEqual([], updated["evidence"])

    def test_derived_note_cannot_create_requirement(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            data["requirements"][0]["non_authoritative_note"] = (
                "Invented extra rule"
            )
            self.assertEqual([], self.evaluate(data, root))

    def test_delivery_requires_current_forward_audit(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            self.assertIn(
                "FORWARD_AUDIT_REQUIRED",
                self.codes(self.evaluate(data, root, "delivery")),
            )

    def test_delivery_resolves_relative_artifact_paths_from_task_root(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            target = Path(data["evidence"][0]["target_path"])
            record = Path(data["evidence"][0]["record_path"])
            data["evidence"][0]["target_path"] = target.name
            data["evidence"][0]["record_path"] = record.name
            audit_record = root / "forward-audit.json"
            audit_record.write_text('{"result":"pass"}', encoding="utf-8")
            data["observed_paths"].append(str(audit_record.resolve()))
            data["forward_audit"] = {
                "result": "pass",
                "record_path": audit_record.name,
                "record_sha256": digest(audit_record),
                "source_sha256": {"SRC-001": data["sources"][0]["sha256"]},
                "artifact_sha256": {str(target.resolve()): digest(target)},
            }
            self.assertEqual([], self.evaluate(data, root, "delivery"))

    def test_relative_source_path_invalidation_uses_task_root(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            source = Path(data["sources"][0]["path"])
            data["sources"][0]["path"] = source.name
            updated, affected = core.invalidate_contract(
                data,
                {str(source.resolve())},
            )
            self.assertEqual({"REQ-001"}, affected)
            self.assertEqual([], updated["evidence"])

    def test_invalidation_cli_updates_contract_atomically(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            contract_path = root / ".skill-contract" / "contract.json"
            contract_path.parent.mkdir()
            data["observed_paths"].append(str(contract_path.resolve()))
            data["forward_audit"] = {"result": "pass"}
            contract_path.write_text(
                json.dumps(data, ensure_ascii=False),
                encoding="utf-8",
            )
            changed = data["evidence"][0]["record_path"]
            command = [
                sys.executable,
                "-X",
                "utf8",
                str(Path(__file__).with_name("invalidate_contract.py")),
                str(contract_path),
                "--changed",
                changed,
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(["REQ-001"], json.loads(completed.stdout))
            updated = json.loads(contract_path.read_text(encoding="utf-8"))
            self.assertEqual([], updated["requirements"][0]["evidence_ids"])
            self.assertEqual([], updated["evidence"])
            self.assertIsNone(updated["forward_audit"])
            self.assertFalse(contract_path.with_suffix(".json.tmp").exists())

    def test_source_change_persists_invalidation_while_contract_stays_failed(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            contract_path = root / ".skill-contract" / "contract.json"
            contract_path.parent.mkdir()
            data["observed_paths"].append(str(contract_path.resolve()))
            contract_path.write_text(
                json.dumps(data, ensure_ascii=False),
                encoding="utf-8",
            )
            source_path = Path(data["sources"][0]["path"])
            source_path.write_text("# changed source\n", encoding="utf-8")
            command = [
                sys.executable,
                "-X",
                "utf8",
                str(Path(__file__).with_name("invalidate_contract.py")),
                str(contract_path),
                "--changed",
                str(source_path),
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(1, completed.returncode)
            updated = json.loads(contract_path.read_text(encoding="utf-8"))
            self.assertEqual([], updated["requirements"][0]["evidence_ids"])
            self.assertEqual([], updated["evidence"])
            self.assertIsNone(updated["forward_audit"])

    def test_invalidation_cli_resolves_relative_changed_path_from_task_root(self):
        with tempfile.TemporaryDirectory() as name, tempfile.TemporaryDirectory() as other:
            root = Path(name)
            data = minimal_contract(root)
            contract_path = root / ".skill-contract" / "contract.json"
            contract_path.parent.mkdir()
            data["sources"][0]["path"] = "SKILL.md"
            data["observed_paths"].append(str(contract_path.resolve()))
            contract_path.write_text(
                json.dumps(data, ensure_ascii=False),
                encoding="utf-8",
            )
            (root / "SKILL.md").write_text("# changed source\n", encoding="utf-8")
            command = [
                sys.executable,
                "-X",
                "utf8",
                str(Path(__file__).with_name("invalidate_contract.py")),
                str(contract_path),
                "--changed",
                "SKILL.md",
            ]
            completed = subprocess.run(
                command,
                cwd=other,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(1, completed.returncode)
            updated = json.loads(contract_path.read_text(encoding="utf-8"))
            self.assertEqual([], updated["requirements"][0]["evidence_ids"])
            self.assertEqual([], updated["evidence"])

    def test_validation_cli_reports_structured_result(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = minimal_contract(root)
            contract_path = root / ".skill-contract" / "contract.json"
            contract_path.parent.mkdir()
            data["observed_paths"].append(str(contract_path.resolve()))
            contract_path.write_text(
                json.dumps(data, ensure_ascii=False),
                encoding="utf-8",
            )
            command = [
                sys.executable,
                "-X",
                "utf8",
                str(Path(__file__).with_name("validate_contract.py")),
                str(contract_path),
                "--phase",
                "work",
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertEqual(
                {"ok": True, "errors": []},
                json.loads(completed.stdout),
            )


if __name__ == "__main__":
    unittest.main()
