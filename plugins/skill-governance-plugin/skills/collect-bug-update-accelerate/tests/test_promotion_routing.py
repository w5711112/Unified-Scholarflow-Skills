import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "skills" / "collect-bug-update-accelerate"


def load_audit():
    spec = importlib.util.spec_from_file_location("promotion_audit", SKILL / "scripts" / "promotion_audit.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def candidate(component: str) -> dict:
    return {"component": component, "status": "verified", "effect_contract": {"expected_effect": "ok"}, "regression_test": "test", "reuse_failure_count": 0, "promotion": "none"}


def test_provider_routing_resolves_global_fallback_and_research_owner():
    audit = load_audit()
    routing = audit.load_routing(SKILL / "references" / "improvement-routing.json")
    registry = ROOT / "ecosystem-registry.json"
    fallback = audit.audit_candidate(candidate("unknown-component"), routing, registry)
    research = audit.audit_candidate(candidate("paper-highlight-semantics"), routing, registry)
    assert fallback["owner_component"] == "global.collect-bug-update-accelerate"
    assert research["owner_component"] == "research.read-paper-analysis-highlight"
    assert "canonical Skill missing" not in fallback["reasons"] + research["reasons"]
    assert "mirror_path" not in fallback
    assert "mirror_path" not in research


def test_provider_routing_resolves_migration_to_its_active_global_owner():
    audit = load_audit()
    routing = audit.load_routing(SKILL / "references" / "improvement-routing.json")
    result = audit.audit_candidate(candidate("migration"), routing, ROOT / "ecosystem-registry.json")
    assert result["owner_component"] == "global.migration-skill"
    assert "unknown registry owner" not in result["reasons"]


def test_promotion_audit_documentation_matches_registry_parser_route():
    documentation = (SKILL / "references" / "incident-schema.md").read_text(encoding="utf-8")
    parser_source = (SKILL / "scripts" / "promotion_audit.py").read_text(encoding="utf-8")
    assert "--ecosystem-registry <ecosystem-registry.json>" in documentation
    assert "--plugin-root" not in documentation
    assert 'add_argument("--ecosystem-registry"' in parser_source
