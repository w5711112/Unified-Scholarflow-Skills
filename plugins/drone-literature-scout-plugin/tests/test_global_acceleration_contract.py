from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = PLUGIN_ROOT / "skills"
GOVERNANCE_ROOT = Path.home() / ".agents" / "plugins" / "sources" / "skill-governance-plugin"
COLLECT_ROOT = GOVERNANCE_ROOT / "skills" / "collect-bug-update-accelerate"
ECOSYSTEM_REGISTRY = GOVERNANCE_ROOT / "ecosystem-registry.json"
ROUTING = COLLECT_ROOT / "references" / "improvement-routing.json"
SCRIPT_ROOT = COLLECT_ROOT / "scripts"

sys.path.insert(0, str(SCRIPT_ROOT))

from incident_registry import (  # noqa: E402
    empty_registry,
    promotion_candidates,
    record_reuse_result,
    select_route,
    upsert_incident,
)


def current_skills() -> dict[str, Path]:
    return {
        path.name: path / "SKILL.md"
        for path in SKILLS_ROOT.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    }


def lazy_contract(text: str) -> str:
    match = re.search(
        r"^## 插件级轻量故障协作\n(?P<body>.*?)(?=^## |\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group("body") if match else ""


class GlobalAccelerationContractTests(unittest.TestCase):
    def test_every_skill_declares_one_lightweight_fast_and_slow_path(self):
        required = (
            "正常成功路径不写故障库",
            "preflight",
            "任意异常、非零退出、权限拒绝、结果缺失或验证失败",
            "capture-event",
            "本地事故库",
            "公共事故库只读",
            "最终回答前",
            "只有本轮事件发生变化",
            "promotion_audit.py",
            "本 Skill 的效果验证",
        )
        for name, skill_file in current_skills().items():
            section = lazy_contract(skill_file.read_text(encoding="utf-8"))
            self.assertTrue(section, f"{name} has no lightweight contract")
            for phrase in required:
                with self.subTest(skill=name, phrase=phrase):
                    self.assertIn(phrase, section)
            self.assertEqual(section.count("正常成功路径不写故障库"), 1)

    def test_manifest_and_global_collect_metadata_expose_six_skill_boundary(self):
        manifest = json.loads(
            (PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        architecture=json.loads((PLUGIN_ROOT / "architecture-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], architecture["release_version"])
        self.assertEqual(manifest["version"].split("+")[0], "2.1.0")
        self.assertIn("six", manifest["interface"]["longDescription"].lower())
        self.assertIn("global.collect-bug-update-accelerate", (PLUGIN_ROOT / "architecture-manifest.json").read_text(encoding="utf-8"))
        metadata = (COLLECT_ROOT / "agents" / "openai.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("$collect-bug-update-accelerate", metadata)
        self.assertIn("96-character Chinese notice limit", metadata)
        self.assertIn("capture before changing route", metadata)

    def test_global_collect_skill_rejects_heavy_runtime_architecture(self):
        text = (COLLECT_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "正常成功路径不写故障库",
            "不为普通工具调用预检",
            "不为普通工具调用预检、候选审计或创建成功流水账",
            "一次真实成功并经效果验证即可复用",
            "候选非空才运行只读 `promotion_audit.py`",
            "领域语义",
            "失败即恢复并登记",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_routing_owners_use_resolvable_component_ids(self):
        routing = json.loads(ROUTING.read_text(encoding="utf-8"))
        entries = [routing["fallback"], *routing["routes"]]
        registry = json.loads(ECOSYSTEM_REGISTRY.read_text(encoding="utf-8"))
        active = {item["id"] for item in registry["components"] if item["status"] == "active"}
        for entry in entries:
            with self.subTest(owner=entry["owner_component"]):
                self.assertIn(entry["owner_component"], active)

    def test_pressure_scenario_prefers_equivalent_background_solution(self):
        incident = {
            "component": "windows-input",
            "symptom_signature": "input permission denied",
            "root_cause": "foreground input is denied",
            "known_good_solution": "use the background API",
            "verification": "background API produced the required result",
            "forbidden_retries": [
                {"route": "foreground-computer-use", "parameters": {}}
            ],
            "preferred_route": "app-internal-api",
            "environment": {"os": "windows"},
            "status": "verified",
            "source_scope": "current-task",
            "effect_contract": {
                "expected_effect": "produce the same application state",
                "forbidden_side_effects": ["foreground-mouse-input"],
                "domain_semantics": False,
            },
        }
        registry = upsert_incident(empty_registry(), incident)
        stored = registry["incidents"][0]
        self.assertEqual(
            select_route(["foreground-computer-use", "app-internal-api"]),
            "app-internal-api",
        )
        with self.assertRaises(ValueError):
            record_reuse_result(
                registry,
                incident_id=stored["id"],
                success=True,
                effect_verified=True,
                verification="shortcut returned zero",
                side_effects=["foreground-mouse-input"],
                cleanup_complete=True,
            )
        self.assertEqual(promotion_candidates(empty_registry()), [])


if __name__ == "__main__":
    unittest.main()
