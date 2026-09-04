"""全库指标和动态研究方向评分。"""

from __future__ import annotations

from collections import Counter
from typing import Iterable


WEIGHTS = {
    "recommendation": 0.05,
    "prospect": 0.15,
    "feasibility": 0.25,
    "venue_fit": 0.10,
    "uniqueness": 0.25,
    "evidence": 0.05,
    "learning_fit": 0.15,
}


_REJECT_TRAINING = {"over_budget", "multi_gpu_only", "unbounded"}
_REJECT_DEPLOYMENT = {"above_jetson", "special_hardware", "large_memory_model"}
_UNKNOWN = {"", "unknown", "not_measured", "unverified"}


def direction_hard_gate(candidate: dict) -> tuple[bool, list[str]]:
    """应用方案 A 硬门槛，不补造缺失证据。"""

    reasons: list[str] = []
    if not candidate.get("hard_gate", False):
        reasons.append("已有主题硬门槛未通过")
    training_status = str(candidate.get("training_budget_status", "unknown")).strip().casefold()
    if training_status in _REJECT_TRAINING:
        reasons.append("训练预算超过项目上限")
    elif training_status in _UNKNOWN:
        reasons.append("训练预算待核验")
    deployment_status = str(candidate.get("deployment_status", "unknown")).strip().casefold()
    if deployment_status in _REJECT_DEPLOYMENT:
        reasons.append("部署要求超过 Jetson 级别")
    elif deployment_status in _UNKNOWN:
        reasons.append("Jetson 级部署状态待核验")
    if bool(candidate.get("generic_topic", False)):
        reasons.append("传统低新颖性主题只作为基线")
    rejected = any(
        reason in {
            "已有主题硬门槛未通过",
            "训练预算超过项目上限",
            "部署要求超过 Jetson 级别",
            "传统低新颖性主题只作为基线",
        }
        for reason in reasons
    )
    return not rejected, reasons


def score_direction(dimensions: dict[str, float]) -> float:
    score = sum(float(dimensions.get(name, 0)) * weight for name, weight in WEIGHTS.items())
    return round(score, 2)


def rank_directions(candidates: Iterable[dict], limit: int = 15) -> list[dict]:
    ranked = []
    for candidate in candidates:
        accepted, reasons = direction_hard_gate(candidate)
        if not accepted:
            continue
        item = dict(candidate)
        item["score"] = score_direction(item.get("dimensions", {}))
        item["preference_gate_reasons"] = reasons
        item["preference_status"] = "待核验" if reasons else "通过"
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["score"], str(item.get("name", ""))))
    return ranked[: max(0, min(limit, 15))]


def compute_global_metrics(rows: Iterable[dict[str, str]]) -> dict[str, object]:
    rows = list(rows)
    venues = Counter((row.get("source") or "").strip() for row in rows)
    years = Counter((row.get("venue_time") or "").split("-")[0].strip() for row in rows)
    labs = Counter(
        (row.get("lab_group") or "").strip()
        for row in rows
        if (row.get("lab_group") or "").strip()
    )
    return {
        "total": len(rows),
        "venues": dict(venues),
        "years": dict(years),
        "labs": dict(labs),
    }
