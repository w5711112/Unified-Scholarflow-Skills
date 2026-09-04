from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
ENTRY = SKILL_ROOT / "SKILL.md"
LEGACY = Path(__file__).resolve().parent / "fixtures" / "SKILL.before-route-b.md"
AUTHORITY_MAP = SKILL_ROOT / "references" / "authority-map.json"
REFERENCE_NAMES = (
    "identity-and-acquisition-contract.md",
    "zotero-write-safety-contract.md",
    "state-verification-and-reporting-contract.md",
)
REFERENCE_PATHS = tuple(SKILL_ROOT / "references" / name for name in REFERENCE_NAMES)


def normalized_blocks(text: str) -> list[str]:
    text = text.replace("\r\n", "\n")
    if text.startswith("---\n"):
        text = text.split("---\n", 2)[2]
    result: list[str] = []
    for raw in re.split(r"\n\s*\n", text):
        lines = [line.rstrip() for line in raw.strip().splitlines()]
        while lines and lines[0].startswith("#"):
            lines.pop(0)
        if lines:
            result.append("\n".join(lines))
    return result


class InstructionArchitectureTests(unittest.TestCase):
    def test_entrypoint_is_a_small_router_with_three_direct_references(self):
        current = ENTRY.read_bytes()
        self.assertLessEqual(len(current), 22000)
        self.assertLessEqual(LEGACY.stat().st_size, 4096)
        text = current.decode("utf-8")
        for name in REFERENCE_NAMES:
            self.assertEqual(text.count(f"references/{name}"), 1, name)
        self.assertIn("全批任务", text)
        self.assertIn("每个 reference 只加载一次", text)

    def test_references_exist_at_one_level_without_required_reference_chains(self):
        for path in REFERENCE_PATHS:
            self.assertTrue(path.is_file(), path)
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?i)(必须|required).{0,40}references[/\\].+\.md")
        self.assertEqual(
            {path.name for path in (SKILL_ROOT / "references").glob("*.md")},
            set(REFERENCE_NAMES),
        )

    def test_compact_fixture_is_exact_and_full_history_remains_recorded(self):
        mapping = json.loads(AUTHORITY_MAP.read_text(encoding="utf-8"))
        self.assertEqual(mapping["compact_fixture_sha256"], hashlib.sha256(LEGACY.read_bytes()).hexdigest())
        self.assertEqual(mapping["legacy_sha256"], "c0049694400d2369ec38658670c3ddb085aede2e92862916fb37f1f344ba4e8d")
        self.assertTrue(LEGACY.read_text(encoding="utf-8").startswith("---\nname:"))
        self.assertTrue(mapping["rewritten_blocks"])

    def test_numeric_status_and_safety_contracts_remain_exact(self):
        corpus = "\n".join(
            [ENTRY.read_text(encoding="utf-8")]
            + [path.read_text(encoding="utf-8") for path in REFERENCE_PATHS]
        )
        required = (
            "第 12 条到第 102 条，共 91 条",
            "第 1–11 条不得重新创建或重复下载",
            "至少核对标题、第一作者、venue、年份中的三项",
            "每批最多 10 条",
            "application/pdf",
            "duplicate_parent_keys",
            "写前快照",
            "写入后必须再次分页读取",
            "字节级一致",
            "write_rolled_back_duplicate",
        )
        states = (
            "ready",
            "imported_metadata",
            "imported_pdf",
            "duplicate_existing",
            "duplicate_merge_required",
            "doi_candidate_review",
            "no_public_doi_confirmed",
            "pdf_download_failed",
            "metadata_conflict",
            "manual_review",
        )
        for value in required + states:
            self.assertIn(value, corpus, value)

    def test_single_evidence_ids_do_not_cross_refresh_boundaries(self):
        text = ENTRY.read_text(encoding="utf-8")
        for evidence_id in (
            "IDENTITY_EVIDENCE",
            "PREWRITE_LIBRARY_SNAPSHOT",
            "POSTWRITE_RECONCILIATION",
        ):
            self.assertIn(evidence_id, text)
        self.assertIn("达到新的强制取证边界时必须刷新", text)
        self.assertIn("不得跨边界复用旧证据", text)


if __name__ == "__main__":
    unittest.main()
