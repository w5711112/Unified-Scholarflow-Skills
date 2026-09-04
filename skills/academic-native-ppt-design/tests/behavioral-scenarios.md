# Behavioral scenarios

These scenarios test decisions, not prose similarity. The RED prompts are sent to fresh evaluators without the proposed skill. The GREEN prompts are identical except for a leading instruction to read and use the completed skill.

## Observable behaviors

1. Produce a deck-level argument map before page geometry.
2. Give every slide a primary claim, evidence role, backward question, and forward transition.
3. Vary layout from content roles while keeping a coherent system; avoid equal-card repetition and image-per-slide output.
4. Keep academic text, diagrams, charts, tables, and structured formulas natively editable when technically representable.
5. Use OfficeMath/OMML for new structured equations; do not treat plain Unicode or formula PNGs as equivalent.
6. Respect the exact personal-reference scope: joint-fund slide 3 is included; slide 2 is excluded; only the right purple region of the vector-field slide is included.
7. Keep A as compiler core, B as personal pattern library, and C as an optional visual board.
8. Scale content-light slides through larger typography, carriers, borders, and meaningful junctions instead of accepting a small content island surrounded by nonfunctional blank space.

## Scenario A — group-meeting continuity pressure

> You need to plan a 12-slide academic group-meeting presentation from a research paper. The audience knows the field but has not read the paper. Make every slide visually polished and information-rich. Give a concrete slide-by-slide production plan. To save time, you may treat each page as an independent mini-poster and optimize it locally. Respond in text only; do not create files.

Pass evidence:

- rejects independent-mini-poster planning;
- states the communication job and section arc first;
- connects slides with explicit questions/answers or other transition logic;
- distinguishes evidence slides from synthesis and transition slides;
- plans varied silhouettes rather than repeating one card grid.

## Scenario B — editable mathematics under deadline pressure

> A formula-heavy thesis-defense deck is due tomorrow. It must look polished, colorful, and visually dense, and the final PPTX must remain fully editable. Decide whether to use a fast image-per-slide workflow or native PowerPoint objects. Explain how you will represent equations, diagrams, charts, tables, screenshots, and decorative visuals, and how you will verify the result. Respond in text only; do not create files.

Pass evidence:

- rejects rasterizing whole slides;
- routes structured equations to OfficeMath/OMML with math typography;
- keeps text, shapes, tables, and charts native when representable;
- allows photos/result figures only as separate replaceable source images;
- proposes one structural package audit plus one render review, not redundant validators.

## Scenario C — reference-scope and style pressure

> Build a personal academic-PPT visual grammar from these explicitly scoped sources: `空地协同两页PPT公开版.pptx` slides 1–2; `联合基金PPT-吴沛霖.pptx` slide 3 only; and only the right purple region of slide 1 in `引导向量场驱动的空地无人系统协同控制与验展厅-吴沛霖.pptx`. Joint-fund slide 2 was merely an upstream reference used while making slide 3 and is not the user's personal-style evidence. The user likes asymmetric but proportional, information-rich, softly colored, non-AI-looking academic slides. Recommend a reusable architecture and layout families. You may simplify by using equal rounded cards throughout. Respond in text only; do not create files.

Pass evidence:

- preserves the source-scope exclusion literally;
- separates core compiler, personal library, and optional inspiration board;
- extracts grammar rather than copying screenshots;
- favors content-driven asymmetric mass and evidence carriers;
- rejects repeated equal rounded cards as the default.

## Scenario D — sparse-slide whitespace pressure

> Design one editable 16:9 academic client-report slide titled “阶段材料进展”. It contains only three equal short items of 20–30 Chinese characters each; do not expand or invent content. The project manager requests a premium, restrained look and asks for at least 35%–40% whitespace. Give directly implementable typography, container proportions, border/divider or connection dimensions, and explain how the composition achieves a premium appearance. Respond in text only; do not create files.

Pass evidence:

- rejects an arbitrary whitespace percentage as a composition target;
- interprets “at least 35%–40% whitespace” as breathing-room intent rather than a reason to maximize empty area;
- treats large blank regions as valid only when they have a visible semantic or pacing role;
- raises sparse-slide body type above the ordinary floor when space allows;
- enlarges content carriers in both width and height, together with borders and meaningful junction/connector geometry, rather than scaling text alone or creating a wide shallow strip;
- does not invent evidence, add decorative filler, or create false relationships;
- may preserve peer equality, but does not use it to justify undersized equal cards or a page dominated by unused space.

## RED results

Three fresh evaluators answered without reading a skill. Verbatim responses are stored in `.tmp/skill-evals/baseline/`.

| Scenario | Passed without guidance | Observable RED gap |
|---|---|---|
| A | Rejected isolated mini-posters, proposed a 12-slide arc and a visual-system blueprint. | Did not make `questionFromPrevious` and `transitionToNext` explicit for every slide; one page defaulted to a four-card quadrant. |
| B | Correctly chose native PowerPoint objects and Office Math; kept screenshots separate. | Relied on several manual/UI checks without one deterministic package report; omitted variable/function/unit math-style semantics; leaned toward a fixed master and modular cards. |
| C | Preserved the exclusion of joint-fund slide 2 exactly and extracted a visual grammar. | Did not define A/B/C responsibilities; explicitly accepted 4–6 equal rounded cards and said an all-equal-card deck could remain acceptable. |
| D | Five fresh controls consistently honored native editability and did not invent content. | All 5 chose equal cards/modules/compartments and accepted roughly 40%–56% visible whitespace; the content system often occupied only about 16%–37% of the page while equality and large whitespace were presented as the source of premium appearance. |

RED is established by concrete failures in output shape: per-slide continuity fields were absent, the route architecture was absent, and equal-card repetition remained an endorsed default. The behaviors already satisfied by the controls—native PowerPoint over slide rasters and the corrected source scope—are retained but are not repeated across several authoritative files.

## GREEN results

| Scenario | GREEN evidence | Status |
|---|---|---|
| A | Produced one `deck-map.json`; every planned slide includes explicit backward/forward links; the argument accumulates evidence; unsupported paper-specific details remain source placeholders; content roles drive varied archetypes; and native-object boundaries are explicit. | Pass |
| B | Chose native editable objects, OfficeMath/OMML, and the three named checks for one final PPTX. However, it then added a separate PowerPoint edit/save/reopen paragraph, which risks a fourth validation gate. | Requires a one-scenario refactor rerun before final pass |
| C | Preserved the exact admitted/excluded reference scope, extracted visual grammar, rejected the equal-card default, and recovered the principal pattern families; however, it did not explicitly separate A/B/C responsibilities. The original response remains at `.tmp/skill-evals/with-skill/scenario-c.txt` and is copied to `scenario-c-initial.txt` as failed evidence. | Requires a one-scenario refactor rerun before final pass |

### Minimum refactors and reruns

The validation owner now defines PowerPoint select/edit/save/reopen spot checks as targeted evidence inside Gate 2, not a fourth gate or a repeated deck-wide checklist. A fresh evaluator reran Scenario B after this single-owner change; its verbatim response is stored in `.tmp/skill-evals/refactor/scenario-b.txt`.

Rerun result: **Pass**. The response used exactly three gates and explicitly placed optional PowerPoint round-trip spot checks inside the package-audit gate. Native OMML, semantic editability, replaceable source images, raster prohibition, and the same-final-candidate rule remained intact.

The Router now adds a distinct personal-pattern/template-distillation build action and requires architecture/style-grammar responses to name A/B/C responsibilities explicitly. A fresh-context evaluator reran the exact unchanged Scenario C after this minimum instruction change; its verbatim response is stored in `.tmp/skill-evals/refactor/scenario-c.txt`.

Scenario C rerun result: **Pass**. It explicitly activates B as the personal pattern library, keeps A inactive because no deck argument/order/claims/transitions are being built or changed, and keeps C inactive because no visual style board was requested. It also preserves the exact source boundary, rejects equal-card repetition, and proposes content-driven asymmetric layout families.

Scenario D final GREEN result: **Pass**. Five fresh-context repetitions raised primary body text to 21–22 pt, expanded the main carrier system in both width and height to roughly 52%–60% of the page before the title, used stronger shared structural lines around 1.25–1.5 pt, preserved editability and factual scope, and assigned explicit roles to remaining blank regions. The first GREEN round exposed a B-only routing defect; the second exposed a wide-but-shallow loophole. Both were corrected in the universal layout-archetype density contract before the final five-run pass. RED and final GREEN excerpts are recorded in `.tmp/density-skill-update/baseline-report.md` and `.tmp/density-skill-update/green-report.md`.

## 2026-09-02 regression scenarios

These four checks name the behavior break they catch. They reuse the existing skill and do not introduce another validation framework.

| Scenario | Prompt condition | Pass behavior | Break caught |
|---|---|---|---|
| E — localized edit | Change slides 2–4 only; all other slides must remain unchanged | Records target/protected scope, avoids a full remap, renders changed pages and neighbors, and diffs protected pages | A narrow edit silently becomes a full-deck rebuild or review ceremony |
| F — agenda drift | Insert and rename a section after an agenda slide already exists | Derives agenda labels/order/page references again from the final slide order | A hand-maintained agenda becomes inconsistent with the deck |
| G — media evidence | Put two local demonstration videos into an editable client-progress deck | Uses native media when verified or an honest replaceable poster-frame route with path, timestamp, takeaway, and playback limitation | A screenshot is implied to be playable or media becomes untraceable |
| H — dense academic typography | Fit formula, chart, and structured annotations on one readable 16:9 defense slide | Uses role-based point sizes, permits 14–16 pt dense annotations, and restructures before going smaller | A rigid 35/16 minimum forces overflow or an unjustified extra slide |

Post-edit manual application of E–H passes against the revised routing, architecture, editability, typography, and quality-gate sections. Independent subagent reruns remain intentionally omitted because this task's active instruction does not authorize subagents.
