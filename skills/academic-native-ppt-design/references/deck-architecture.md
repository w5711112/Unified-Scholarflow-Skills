# Deck Architecture

This file owns the deck-level narrative contract. Use it for new decks and major redesigns before deciding page geometry.

## Navigation

- [Required deck map](#required-artifact-deck-mapjson)
- [Argument spine](#build-the-argument-spine)
- [Transitions](#transition-vocabulary)
- [Evidence and rhythm](#evidence-accumulation-and-rhythm)
- [Continuity inspection](#continuity-inspection)

## Required artifact: `deck-map.json`

Create exactly one deck map for the presentation. It is the working contract between context, sources, argument, slides, and layout. It must contain:

- deck: `communicationJob`, `presentationMode`, `secondaryMode`, `audience`, `decisionGoal`, `posture`, `pageBudget`, `timeBudget`, `contentLoad`, `densityStrategy`, and `styleProfile`;
- each section: `purpose`;
- each slide: `role`, `questionFromPrevious`, `claim`, `evidence`, `transitionToNext`, `layoutFamily`, `density`, `spokenPurpose`, `timeSeconds`, and `sources`.

`presentationMode` is one primary mode from [context-aware style routing](context-style-routing.md). `secondaryMode` is either one compatible overlay or `null`. `pageBudget` and `timeBudget` record fixed limits or a reasoned range; `contentLoad` summarizes the mandatory claims/evidence; `densityStrategy` explains how that load is distributed across the budget without using the mode as a proxy. `styleProfile` contains `selectedComponents`, `suppressedComponents`, and `rationale`; the component arrays may be empty when route B is inactive, but the rationale must say what visual authority is used instead. Do not create a separate style-plan artifact.

`questionFromPrevious` may be `null` only for a true opening slide. `transitionToNext` may be `null` only when the slide resolves the deck; a generic “Thank you” does not count as resolution. `evidence` and `sources` are arrays even when they have one item.

`spokenPurpose` is the one sentence the presenter must make the audience understand on that slide. `timeSeconds` is a practical allocation, not a narration script; the slide allocations should fit the deck time budget and expose pages that are too dense to explain.

When the deck contains an agenda or index, derive its section labels, order, and page references from the current section/slide order after that order is final. Re-derive it whenever slides are inserted, removed, renamed, or reordered; never maintain an independent hand-written outline that can drift from the deck.

### Complete example

```json
{
  "communicationJob": "By the end, a controls research audience should accept that the coupled guidance law improves air-ground rendezvous robustness because the mechanism, prediction, and two-layer experiment agree.",
  "presentationMode": "thesis-defense",
  "secondaryMode": "technical-review",
  "audience": "controls researchers evaluating novelty and experimental rigor",
  "decisionGoal": "accept the contribution and the evidence chain while identifying its limits",
  "posture": "evaluative",
  "pageBudget": {"target": 4, "basis": "four required claim/evidence steps in an eight-minute slot"},
  "timeBudget": {"minutes": 8},
  "contentLoad": "four mandatory claims, two structured formulas, one simulation/physical comparison, and one limitations statement",
  "densityStrategy": "Give one slide to each mandatory claim; allow the mechanism and comparison slides to be dense because their evidence must be inspected together, while keeping the opening and resolution lighter. The distribution follows the four-slide budget, not the defense mode.",
  "styleProfile": {
    "selectedComponents": ["stable-academic-scaffold", "asymmetric-evidence-zones", "dense-mixed-evidence", "bottom-synthesis"],
    "suppressedComponents": ["system-purple-field", "hero-evidence"],
    "rationale": "The audience must inspect the mechanism and matched simulation/physical evidence; proposal-style promotion and unrelated source-deck identity are excluded."
  },
  "sections": [
    {
      "id": "problem",
      "purpose": "establish the operational failure and the unresolved research gap",
      "slides": [
        {
          "number": 1,
          "role": "opening-promise",
          "questionFromPrevious": null,
          "claim": "Reliable autonomous rendezvous is the limiting step in persistent air-ground operation.",
          "evidence": ["mission sequence", "measured endurance constraint"],
          "transitionToNext": "Which part of the current rendezvous pipeline causes the reliability loss?",
          "layoutFamily": "hero-evidence-with-reasoning-rail",
          "density": "medium",
          "spokenPurpose": "Make the audience see why rendezvous reliability limits the whole mission.",
          "timeSeconds": 70,
          "sources": ["project-report.pdf#page=2", "flight-log.csv#endurance"]
        },
        {
          "number": 2,
          "role": "gap-diagnosis",
          "questionFromPrevious": "Which part of the current rendezvous pipeline causes the reliability loss?",
          "claim": "Uncoupled guidance updates amplify terminal error under platform motion.",
          "evidence": ["baseline block diagram", "terminal-error trace"],
          "transitionToNext": "How can the two update loops be coupled without losing feasibility?",
          "layoutFamily": "causal-explanation-chain",
          "density": "high",
          "spokenPurpose": "Locate the failure in the uncoupled update mechanism.",
          "timeSeconds": 110,
          "sources": ["paper.pdf#page=4", "baseline-results.xlsx#terminal-error"]
        }
      ]
    },
    {
      "id": "method-and-evidence",
      "purpose": "answer the gap with a mechanism, derive its prediction, and test that prediction",
      "slides": [
        {
          "number": 3,
          "role": "mechanism",
          "questionFromPrevious": "How can the two update loops be coupled without losing feasibility?",
          "claim": "A coupled vector-field update coordinates vehicle motion while preserving the feasible set.",
          "evidence": ["OfficeMath update law", "editable mechanism diagram", "assumption callout"],
          "transitionToNext": "If this mechanism is correct, what measurable behavior should change?",
          "layoutFamily": "method-core-with-insets",
          "density": "high",
          "spokenPurpose": "Explain how the coupled update preserves feasibility.",
          "timeSeconds": 130,
          "sources": ["paper.pdf#page=7", "paper.pdf#page=8"]
        },
        {
          "number": 4,
          "role": "prediction-and-result",
          "questionFromPrevious": "If this mechanism is correct, what measurable behavior should change?",
          "claim": "The coupled update reduces terminal error in simulation and physical trials without increasing constraint violations.",
          "evidence": ["native comparison chart", "simulation capture", "physical experiment capture", "sample-size note"],
          "transitionToNext": null,
          "layoutFamily": "simulation-physical-experiment-comparison",
          "density": "medium",
          "spokenPurpose": "Close the argument with matched simulation and physical evidence.",
          "timeSeconds": 170,
          "sources": ["results.xlsx#summary", "sim-run-14.mp4#00:31", "trial-08.mp4#00:42"]
        }
      ]
    }
  ]
}
```

## Build the argument spine

1. Write the audience-specific `communicationJob` as a change in understanding or acceptance, not a topic label.
2. Select and declare the presentation context under [context-aware style routing](context-style-routing.md), then record the primary/secondary modes and component-level `styleProfile`. Do not select an entire reference deck as the profile.
3. Inventory mandatory claims/evidence, resolve the page/time budget, and write `densityStrategy` before assigning slide geometry. Mode names are not density evidence.
4. Form sections that successively create and resolve needs: context → gap → mechanism → prediction → evidence → implication is common, not mandatory.
5. Give every slide one narrative role and one primary claim. Split a slide when two claims require separate evidence or separate transitions and the budget permits; otherwise restructure the evidence while preserving legibility.
6. Bind each evidence carrier to a source. A source-free claim is either removed, marked as interpretation, or stopped for clarification.
7. Choose `layoutFamily` only after the claim/evidence shape is known; consult [layout archetypes](layout-archetypes.md).

The table below adapts the argument spine. Visual posture and component selection remain owned by [context-aware style routing](context-style-routing.md).

Academic adaptations:

| Setting | Typical communication job | Common section progression |
|---|---|---|
| Group meeting | enable peers to critique the current inference or next experiment | status → unresolved question → evidence → interpretation → decision |
| Thesis defense | establish novelty, rigor, and contribution | problem → gap → method → validation → contribution → limitations |
| Grant presentation | make the need, feasibility, and payoff credible | need → opportunity → aims → approach → preliminary evidence → risk/impact |
| Project report | show accountable progress and next action | objective → work packages → evidence → variance → risk → next milestone |
| Research talk | move a field-aware audience from question to implication | motivation → gap → mechanism → tests → synthesis → broader implication |

## Transition vocabulary

Use a specific transition relationship rather than “next”:

- question → answer;
- claim → mechanism;
- mechanism → prediction;
- prediction → experiment;
- experiment → result;
- result → comparison;
- comparison → implication;
- local evidence → section synthesis;
- limitation → next research question.

The transition sentence should state the intellectual need the following slide satisfies. At section boundaries, the final slide of the current section must make the next section's `purpose` necessary.

## Evidence accumulation and rhythm

Track what the audience can now believe after each slide. A later claim may depend only on evidence already introduced or introduced on that slide. Use synthesis slides to combine evidence; do not repeat miniature summaries after every result.

Plan rhythm as a sequence:

- vary silhouette and primary evidence carrier across adjacent slides while retaining the same tokens and outer scaffold;
- do not repeat the same page skeleton more than twice, except for an intentional small-multiple sequence;
- interrupt runs of dense mechanism/evidence pages with a synthesis, hero-evidence, or transition page when the argument permits;
- use each slide's derived `density` (`low`, `medium`, or `high`) to see pacing; it must follow the recorded content/page/time distribution and never justify unreadable type;
- make the closing resolve the opening promise and expose the implication or next research question.

## Continuity inspection

Inspect the completed map once, in order:

1. **Context and density fit:** the declared primary mode, optional secondary mode, audience, decision goal, posture, page/time budget, content load, `densityStrategy`, and `styleProfile` agree; density is derived from the current deck constraints rather than a mode stereotype, selected components are justified, and suppressed components do not leak in from reference decks.
2. **Opening promise:** the communication job and first claim specify what will change for this audience.
3. **Backward link:** for every slide after the opener, `questionFromPrevious` is answerable by the current `claim` and arises from a prior `transitionToNext`.
4. **Forward link:** every non-closing slide creates a concrete need that a later slide satisfies.
5. **Section necessity:** each section's last transition makes the next section purpose necessary.
6. **Evidence chain:** claims have cited evidence; comparisons use shared conditions; syntheses depend on evidence already shown.
7. **Coverage:** every source-critical claim appears once in the map, and no unsupported fact was invented to fill space.
8. **Rhythm:** layout families, evidence carriers, and density vary deliberately under [layout archetypes](layout-archetypes.md); when B is active, apply only the `styleProfile.selectedComponents` from [personal visual system](personal-visual-system.md).
9. **Agenda consistency:** any agenda/index matches the final section names, order, and page references.
10. **Oral fit:** `timeSeconds` allocations fit the total budget and each `spokenPurpose` is explainable with the visible evidence.
11. **Resolution:** the final claim answers the opening promise rather than stopping at a courtesy slide.

If a continuity failure appears, revise `deck-map.json` before changing slide geometry.

## Localized edits

Do not require a full `deck-map.json` for a bounded edit that preserves deck-wide argument, order, claims, and transitions. Record only the target slides/regions, protected slides, intended change, and any affected predecessor/successor transition. If the edit changes slide order, section names, or the agenda, update the affected map entries and re-derive the agenda; do not remap unrelated slides.
