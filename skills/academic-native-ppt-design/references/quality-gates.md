# Quality Gates

Validation is consolidated into exactly three checks. Do not add parallel validator lists, repeat the same package inspection under different names, or re-hash intermediate notes ceremonially. A localized edit uses the same three owners with reduced scope; it does not create a fourth workflow.

## 1. Plan validation — one `deck-map.json`

Inspect the single current map once before production geometry and again only if its narrative, context profile, content load, or page/time budget changes. Apply the schema and continuity inspection in [deck architecture](deck-architecture.md) to the current map, including presentation-mode fit, audience and decision goal, page/time budget, mandatory content load, `densityStrategy`, `styleProfile` selection/suppression, narrative continuity, source coverage, slide-role completeness, and layout repetition. Confirm that slide densities follow the actual content distribution and readability constraints rather than mode stereotypes, and that reference-deck components not selected by the profile have not leaked into the design. This gate does not define a second deck-map, density-plan, or style-profile artifact.

For a localized edit that does not require a deck map, validate the recorded target/protected slide scope and any affected predecessor/successor transition. If slide order or section names changed, confirm that the agenda/index was derived again from the final order.

Failure route: narrative discontinuity, missing source coverage, or repeated slide logic returns to `deck-map.json`. Wrong content shape returns to archetype selection. Do not compensate in page decoration.

## 2. Package audit — one deterministic report

Run the skill's auditor once on the final candidate:

```powershell
python scripts/audit_pptx.py final.pptx --json final-audit.json
```

Add `--require-native-math` when the deck contains new structured formulas and `--forbid-ole` when OLE is not covered by an explicit waiver.

The report is the single package-structure authority. It covers ZIP integrity, slide count, native shapes/text, tables, charts, OfficeMath, OLE objects, empty placeholders, image count, and likely full-slide rasters. Investigate issue codes in the report; do not create a second XML/ZIP validator that recounts the same objects.

When actual PowerPoint object-selection, edit/save/reopen, compatibility, or round-trip spot checks are warranted, collect them as targeted follow-up evidence inside this Gate 2 package audit. They are not a fourth gate or an independent deck-wide checklist; the structural JSON report remains the single object-count authority.

Failure route: repair math/editability problems in the native object source and rebuild. Do not cover a malformed or missing object with a visual overlay.

## 3. Render review — one slide pass plus one montage

For a new deck or major redesign, render every final slide once for the current candidate. Inspect each slide at full size for legibility, overlap, clipping, evidence readability, color meaning, visible conversion errors, and functional use of blank space. On content-light slides, verify that typography, content carriers, borders, and meaningful connectors/junctions were scaled together instead of leaving a small content island or a wide shallow strip. Reject a stated whitespace percentage as sufficient evidence: every large contiguous blank region must have a visible grouping, focus, directional, separation, or pacing role, and it must not visually outweigh the principal content group. Fail a continuous blank band comparable to a major carrier's dimension unless its role is explicit. Then inspect one montage for deck-level pacing, silhouette variation, density rhythm, section transitions, agenda consistency, and visual continuity.

For a localized edit, render the changed slides and any transition-dependent neighbors at full size, then generate one full-deck montage. Compare protected slides to the pre-edit candidate with a deterministic slide-level visual or package diff when available; inspect only pages that differ unexpectedly. Do not rerender and manually re-review every unchanged slide merely to satisfy ceremony.

Failure route: revise geometry or copy and rerender the affected slide; for nonfunctional blank space, enlarge or recompose meaningful objects before inventing content or adding decoration. Regenerate the montage once the final slide set changes. Rendering does not replace package audit, and package audit does not prove visual quality.

## Evidence binding and stopping rules

- Hash source/version records only when reproducibility requires them.
- Bind the final PPTX hash to its current audit report hash at delivery.
- Do not repeatedly hash drafts, notes, renders, or unchanged intermediate artifacts.
- If a claim's source is uncertain, stop that claim rather than inventing evidence.
- Delivery requires all three checks to refer to the same final candidate. A later PPTX change invalidates the package report and affected render evidence.
