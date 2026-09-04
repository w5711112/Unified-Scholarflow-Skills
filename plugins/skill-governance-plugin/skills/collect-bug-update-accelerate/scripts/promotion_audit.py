from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_routing(path: Path) -> dict[str, Any]:
    routing = json.loads(path.read_text(encoding="utf-8"))
    if routing.get("schema_version") != 2:
        raise ValueError("unsupported improvement routing schema")
    fallback = routing.get("fallback")
    routes = routing.get("routes")
    if not isinstance(fallback, dict) or not isinstance(routes, list):
        raise ValueError("routing requires fallback and routes")
    for entry in [fallback, *routes]:
        for key in (
            "owner_component",
            "allow_auto_apply",
            "recommended_surface",
            "external_evidence",
        ):
            if key not in entry:
                raise ValueError(f"routing entry missing {key}")
        policy = entry.get("promotion_policy", "full")
        if policy not in {"lightweight", "full"}:
            raise ValueError(f"invalid promotion policy: {policy}")
    return routing


def _select_route(component: str, routing: dict[str, Any]) -> dict[str, Any]:
    matches = [
        route
        for route in routing["routes"]
        if any(component.startswith(prefix) for prefix in route["component_prefixes"])
    ]
    owners = {route["owner_component"] for route in matches}
    if len(owners) > 1:
        raise ValueError(f"component {component!r} has multiple Skill owners")
    return matches[0] if matches else routing["fallback"]


def audit_candidate(
    incident: dict[str, Any],
    routing: dict[str, Any],
    ecosystem_registry: Path,
) -> dict[str, Any]:
    route = _select_route(str(incident.get("component", "")), routing)
    registry = json.loads(ecosystem_registry.read_text(encoding="utf-8"))
    roots = registry["roots"]
    component = next((item for item in registry["components"] if item["id"] == route["owner_component"]), None)
    if component is None:
        raise ValueError(f"unknown owner component: {route['owner_component']}")
    root = Path(roots[component["root"]]["path"])
    component_root = (root / component["relative_path"]).resolve()
    canonical = component_root / "SKILL.md"
    reasons: list[str] = []

    status = incident.get("status")
    if status not in {"verified", "promoted"}:
        reasons.append("verified incident required")
    effect_contract = incident.get("effect_contract")
    regression_test = incident.get("regression_test")
    domain_semantics = bool(
        isinstance(effect_contract, dict)
        and effect_contract.get("domain_semantics")
    )
    promotion_policy = str(route.get("promotion_policy", "full"))
    if domain_semantics:
        promotion_policy = "full"
    if promotion_policy == "full":
        if (
            not isinstance(effect_contract, dict)
            or not effect_contract.get("expected_effect")
        ):
            reasons.append("effect contract required")
        if (
            not isinstance(regression_test, str)
            or not regression_test.strip()
        ):
            reasons.append("regression test required")
    if incident.get("reuse_failure_count", 0) > 0:
        reasons.append("reuse regression must be resolved")
    if incident.get("promotion") not in {None, "none", "eligible"}:
        reasons.append("candidate was already applied or rolled back")
    if not canonical.is_file():
        reasons.append("canonical Skill missing")

    if domain_semantics or not route["allow_auto_apply"]:
        reasons.append("owner evidence contract required")
    blocking_reasons = [
        reason for reason in reasons
        if reason != "owner evidence contract required"
    ]
    eligible = not blocking_reasons
    allow_auto_apply = eligible and bool(route["allow_auto_apply"])
    if domain_semantics or not route["allow_auto_apply"]:
        allow_auto_apply = False

    if promotion_policy == "lightweight":
        evidence_route = (
            "official-upstream-plus-local-check"
            if route["external_evidence"]
            else "local-effect-recheck"
        )
    else:
        evidence_route = (
            "official-upstream-plus-local-test"
            if route["external_evidence"]
            else "local-regression-test"
        )
    required_test = (
        regression_test.strip()
        if isinstance(regression_test, str) and regression_test.strip()
        else "lightweight-effect-recheck"
        if promotion_policy == "lightweight"
        else None
    )
    candidate_stage = (
        "ready-for-lightweight-permanent-fix"
        if eligible and promotion_policy == "lightweight"
        else "ready-for-permanent-fix"
        if eligible
        else "temporary"
    )
    return {
        "eligible": eligible,
        "reusable_now": status in {"verified", "promoted"},
        "promotion_policy": promotion_policy,
        "candidate_stage": candidate_stage,
        "owner_component": route["owner_component"],
        "canonical_path": canonical.as_posix(),
        "recommended_surface": route["recommended_surface"],
        "evidence_route": evidence_route,
        "required_test": required_test,
        "reasons": reasons,
        "allow_auto_apply": allow_auto_apply,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    from incident_registry import load_registry, promotion_candidates

    parser = argparse.ArgumentParser(
        description="Read-only audit of verified promotion candidates."
    )
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--routing", type=Path, required=True)
    parser.add_argument("--ecosystem-registry", type=Path, required=True)
    args = parser.parse_args(argv)

    routing = load_routing(args.routing)
    reports = [
        audit_candidate(incident, routing, args.ecosystem_registry)
        for incident in promotion_candidates(load_registry(args.registry))
    ]
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
