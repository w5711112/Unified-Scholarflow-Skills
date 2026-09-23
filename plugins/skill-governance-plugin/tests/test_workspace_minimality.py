from pathlib import Path


ACTIVE_ROOTS = [
    Path(r"C:\Users\w5711112\.agents\skills"),
    Path(r"C:\Users\w5711112\.agents\plugins\sources\skill-governance-plugin"),
    Path(r"C:\Users\w5711112\Documents\Obsidian Vault\<YOUR_RESEARCH_PROJECT>\skill-with-plugin\drone-literature-scout-plugin"),
    Path(r"D:\win-linux-share\AIM\研究生数学建模\2026年省赛工作空间\paper-skill-location\math-modeling-workflow-plugin"),
]


def test_active_skill_sources_contain_no_generated_python_cache() -> None:
    generated = []
    for root in ACTIVE_ROOTS:
        generated.extend(root.rglob("*.pyc"))
        generated.extend(path for path in root.rglob("__pycache__") if path.is_dir())
        generated.extend(path for path in root.rglob(".pytest_cache") if path.is_dir())
    assert generated == []


def test_historical_skill_fixtures_are_compact() -> None:
    fixtures = [path for root in ACTIVE_ROOTS for path in root.rglob("*.before-route-b.md")]
    assert fixtures
    assert all(path.stat().st_size <= 4096 for path in fixtures)
    assert all(path.read_text(encoding="utf-8").startswith("---\nname:") for path in fixtures)
