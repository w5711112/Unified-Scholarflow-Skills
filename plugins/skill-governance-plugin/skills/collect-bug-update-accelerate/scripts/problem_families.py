from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from incident_registry import canonical_component, normalize_signature


Confidence = Literal[
    "explicit", "structured-exact", "rule-exact", "candidate", "unclassified"
]


@dataclass(frozen=True)
class ClassificationResult:
    family_id: str | None
    confidence: Confidence
    matched_features: tuple[str, ...]
    candidate_family_ids: tuple[str, ...]


CATALOG_PATH = Path(__file__).resolve().parents[1] / "references" / "problem-family-catalog.json"


def load_family_catalog(path: Path = CATALOG_PATH) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    families = data.get("problem_families")
    if not isinstance(families, list):
        raise ValueError("problem-family catalog must contain problem_families[]")
    return families


def _required_structured_match(family: dict[str, Any], structured: dict[str, Any]) -> bool:
    keys = ("operation", "failure_phase", "error_class")
    return all(structured.get(key) and structured.get(key) == family.get(key) for key in keys)


def _rule_features(family: dict[str, Any], normalized: str) -> tuple[str, ...] | None:
    if family.get("rule_match_enabled") is False:
        return None
    required_groups = family.get("required_feature_groups")
    if required_groups:
        chosen: list[str] = []
        for group in required_groups:
            hit = next((feature for feature in group if feature in normalized), None)
            if not hit:
                return None
            chosen.append(hit)
    else:
        required = [str(item) for item in family.get("required_features", [])]
        if not all(feature in normalized for feature in required):
            return None
        chosen = required
    any_features = [str(item) for item in family.get("any_features", [])]
    if any_features:
        hit = next((feature for feature in any_features if feature in normalized), None)
        if not hit:
            return None
        chosen.append(hit)
    return tuple(dict.fromkeys(chosen))


def classify_problem(
    component: str,
    symptom: str,
    structured: dict[str, Any] | None,
    environment: dict[str, Any] | None,
    catalog: list[dict[str, Any]] | None = None,
) -> ClassificationResult:
    del environment  # applicability guard only; never part of family identity
    families = catalog or load_family_catalog()
    structured = structured or {}
    canonical = canonical_component(component)
    normalized = normalize_signature(symptom)

    explicit = str(structured.get("family_id") or "").strip()
    if explicit:
        family = next((item for item in families if item.get("family_id") == explicit), None)
        if family is None:
            raise ValueError(f"unknown family_id: {explicit}")
        if family.get("component") != canonical:
            raise ValueError(f"family_id {explicit} does not belong to component {canonical}")
        return ClassificationResult(explicit, "explicit", (), ())

    exact = [
        item
        for item in families
        if item.get("component") == canonical and _required_structured_match(item, structured)
    ]
    if len(exact) == 1:
        return ClassificationResult(str(exact[0]["family_id"]), "structured-exact", (), ())

    matches: list[tuple[dict[str, Any], tuple[str, ...]]] = []
    for family in families:
        if family.get("component") != canonical:
            continue
        features = _rule_features(family, normalized)
        if features is not None:
            matches.append((family, features))
    if len(matches) == 1:
        family, features = matches[0]
        return ClassificationResult(str(family["family_id"]), "rule-exact", features, ())
    candidates = tuple(sorted(str(item[0]["family_id"]) for item in matches))
    return ClassificationResult(
        None,
        "candidate" if candidates else "unclassified",
        (),
        candidates,
    )
