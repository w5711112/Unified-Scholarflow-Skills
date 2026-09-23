from __future__ import annotations

import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from problem_families import classify_problem  # noqa: E402


@pytest.mark.parametrize(
    "symptom",
    [
        "foreach statement piped directly to Format-Table: empty pipe element",
        "pipeline after foreach block caused ParserError empty pipe element",
        "foreach output piped to ConvertTo-Json produced an empty pipe element",
        "foreach statement piped directly to Format-List",
        "PowerShell rejected direct foreach output pipeline",
        "a foreach block cannot be followed directly by a pipe",
    ],
)
def test_foreach_pipeline_variants_share_family(symptom: str) -> None:
    result = classify_problem("powershell", symptom, {}, {"os": "windows"})
    assert result.family_id == "powershell.pipeline.foreach-direct"
    assert result.confidence == "rule-exact"


def test_powershell_directory_access_is_not_foreach_family() -> None:
    result = classify_problem(
        "powershell",
        "Get-ChildItem recursive scan denied access before exclusion",
        {},
        {"os": "windows"},
    )
    assert result.family_id != "powershell.pipeline.foreach-direct"


def test_environment_does_not_fragment_family() -> None:
    symptom = "pipeline after foreach block caused empty pipe element"
    a = classify_problem("powershell", symptom, {}, {"os": "windows"})
    b = classify_problem(
        "powershell",
        symptom,
        {},
        {"shell": "pwsh-7", "os": "windows", "task": "q3"},
    )
    assert a.family_id == b.family_id


def test_structured_signature_has_priority() -> None:
    result = classify_problem(
        "powershell",
        "localized parser failure",
        {
            "operation": "pipeline",
            "failure_phase": "parse",
            "error_class": "empty-pipe-element",
        },
        {"os": "windows"},
    )
    assert result.family_id == "powershell.pipeline.foreach-direct"
    assert result.confidence == "structured-exact"


def test_unknown_failure_is_unclassified() -> None:
    result = classify_problem("powershell", "an unrelated failure", {}, {})
    assert result.family_id is None
    assert result.confidence == "unclassified"
