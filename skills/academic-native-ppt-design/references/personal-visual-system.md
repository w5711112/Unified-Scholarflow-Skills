# Personal Visual System

This file owns the reusable personal visual grammar: source scope, composition, color, typography, positive patterns, and anti-patterns. It describes preferences, not factual content and not an instruction to clone a slide.

## Evidence scope

Evidence is admitted at component level. A source can support one or more local patterns without authorizing its complete layout, identity, palette, content density, or defects.

| Source | Admitted evidence | Most relevant contexts and components | Status and limits |
|---|---|---|---|
| `空地协同两页PPT公开版.pptx` | slides 1–2 | `technical-review`, `client-progress`; `stable-academic-scaffold`, `asymmetric-evidence-zones`, `system-evidence-composition` | Primary positive evidence; use only where system relationships or technical evidence justify it |
| `联合基金PPT-吴沛霖.pptx` | slide 3 only | `grant-proposal`, technical-route explanation; `strategic-hierarchy`, `asymmetric-evidence-zones` | Primary positive evidence |
| `联合基金PPT-吴沛霖.pptx` | slide 2 | None | **Excluded from personal-style evidence.** It was only an upstream reference used while creating slide 3. |
| `引导向量场驱动的空地无人系统协同控制与验展厅-吴沛霖.pptx` | slide 1, right purple region only | `technical-review`, system validation; `system-purple-field` | Personal evidence for that local region only; no other region is attributed |
| `毕业答辩_吴沛霖.pptx` | whole deck | `thesis-defense`; formal scaffold, section rhythm, evidence sequencing, plus recorded anti-patterns | Supporting evidence; not an exact template |
| `吴沛霖湖大面试.pptx` | whole deck | `personal-introduction`; selective identity, project narrative, plus recorded anti-patterns | Supporting evidence; do not import its personal-presentation habits into ordinary academic decks |
| `数模模拟答辩.pptx` | whole deck; especially slides 2–10 for ordinary content pages | `modeling-competition-defense`, `technical-review`; `neutral-gray-canvas`, `dense-mixed-evidence`, `bottom-synthesis` | Supporting positive and anti-pattern evidence; density and source identity are not transferable defaults |

If a future user explicitly designates another PPTX as a template, record that current-task decision separately. Supplying a deck as content does not make it a style source.

## Shared base and conditional components

The current presentation mode is selected under [context-aware style routing](context-style-routing.md). Route B then applies named components rather than merging every source into one style.

The following preferences form the shared personal base whenever B is active:

- `functional-canvas-occupation`: avoid large nonfunctional blank regions and scale sparse content as a system;
- `readable-native-academic-content`: preserve editable evidence, formulas, charts, tables, and readable type;
- `content-driven-asymmetry`: use unequal regions when evidence importance differs;
- `stable-semantic-color`: map color to meaning and keep it consistent;
- `non-dashboard-evidence`: prefer academic evidence carriers over repeated interface cards;
- `deck-level-continuity`: vary page silhouettes while preserving an intelligible outer scaffold and argument.

These shared preferences do not determine a complete appearance. The table below is the sole component registry; do not create a parallel registry file. Select conditional components only when the mode, claim, and evidence support them:

| Component | Use when | Avoid when |
|---|---|---|
| `stable-academic-scaffold` | A formal or accountable deck needs a consistent title rail, edge alignment, source treatment, or section identity | A research-talk sequence benefits from a full-bleed hero or progressive reveal |
| `asymmetric-evidence-zones` | Evidence items have unequal importance or must form an explicit reading path | Items are true peers under identical comparison conditions |
| `system-evidence-composition` | A technical or accountable deck must relate system structure, interaction, and observed state or result | A simple list, single result, or personal narrative has no real system relationship |
| `neutral-gray-canvas` | Dense technical, modeling, or evaluative evidence needs a quiet unifying field | The deck is image-led, highly public-facing, or an authorized template defines another surface |
| `dense-mixed-evidence` | The audience must inspect several related figures, formulas, tables, or progress artifacts together | One result should be remembered, or the audience cannot inspect details during delivery |
| `bottom-synthesis` | A technical or accountable page needs a visible decision, recommendation, or “so what” after the evidence | The page is an opening question, an intentionally unresolved diagnosis, or a progressive reveal |
| `system-purple-field` | A system-validation or coupled-control region needs a restrained method/strategy identity | Purple would conflict with an authorized palette or has no stable semantic role |
| `strategic-hierarchy` | A proposal or technical route must distinguish need, objective, method, and payoff | A working slide must expose raw uncertainty or competing hypotheses without premature synthesis |
| `hero-evidence` | A research talk, section synthesis, or personal introduction has one decisive image/result | Several exact values or coupled mechanisms must be inspected simultaneously |

Record selected and suppressed components in `deck-map.json` when route A is active. Activating a component admits its rules below; it does not activate every component supported by the same source deck.

## Composition grammar: structured abundance

- Keep a stable outer scaffold: consistent title zone, edge alignment, footer/source treatment, and semantic color usage.
- Let evidence create heterogeneous internal regions. Use content-driven asymmetry instead of equal occupancy.
- Establish one visual center and normally 3–7 major visual objects. Minor labels, ticks, and connector segments do not count as major objects.
- Scale visual mass by information importance; a 7:5, 8:4, 5:3:4, or golden-ratio-like relationship is a candidate to test, never a law.
- Mix evidence types when the claim needs them: paper figures, experiment captures, equations, native charts/tables, and editable diagrams.
- Preserve clear reading channels between zones. Remove meaningless holes, but do not fill every gap or equalize every container.
- Treat a large contiguous blank region as a design element only when it visibly provides grouping, focus, direction, comparison separation, or pacing. If it merely leaves the content group floating small on the canvas, the slide is unfinished.
- Vary silhouettes across the deck while retaining the scaffold and tokens. Use the deck-level repetition rule in [deck architecture](deck-architecture.md).

Choose the page structure from [layout archetypes](layout-archetypes.md); this file supplies the visual grammar applied to that structure.

## Personal density emphasis

Use the universal content-volume calibration in [layout archetypes](layout-archetypes.md). Within this personal grammar, avoidance of large nonfunctional blank regions is a priority: sparse pages should visibly enlarge typography, carriers, borders, and meaningful junctions together rather than treating an arbitrary whitespace percentage as premium style.

On an ordinary content slide, inspect occupation in both directions. Content clustered in one corner while the opposite side or lower field remains inert is unfinished even if every local box is tidy. Recompose the evidence zones, enlarge the dominant carrier, or promote the conclusion before adding decoration. Cover, section-divider, and closing slides may remain deliberately sparse when their scale and centering make the pause unmistakable.

## Conditional component: `neutral-gray-canvas`

Apply this restrained academic component only when the current `styleProfile` selects it:

- Keep the outer scaffold light and quiet—often white—with a thin header rail, compact identity marker, section cue, or rule. Place the substantive body on one broad light-neutral-gray field such as `#F2F2F2` or `#EDEDED`.
- Treat gray as a unifying canvas for heterogeneous evidence, not as another semantic accent. Use near-black text and reserve two or three mapped accent colors for stage labels, local contrast, and the final synthesis.
- Prefer one continuous gray body field over many separate gray cards. Internal grouping should come from alignment, scale, dividers, and evidence geometry; otherwise the slide drifts toward a dashboard.
- Let the body field be visibly occupied by the argument. A broad gray region with a small content island merely makes the unused area more obvious.
- Do not force this mode onto every deck or every page. White, tinted, or image-led pages remain valid when they better serve the evidence or narrative role.

## Conditional component: `dense-mixed-evidence`

When `dense-mixed-evidence` is selected, use the reusable lesson from `数模模拟答辩.pptx`: density comes from mixed academic evidence rather than small text or repeated containers.

- Keep the outer scaffold stable, but vary the body silhouette. Useful combinations include assumptions + explanatory figure + symbol table; reasoning column + chart/table column + bottom synthesis; and text + native chart + recommendation.
- Give each major region a different evidentiary job. Text explains the question or method, the figure/chart shows evidence, the table carries exact values or symbols, and the final statement answers “so what.” Do not duplicate the same sentence across all carriers.
- Use a short lower-edge synthesis or recommendation when the evidence needs closure. It should be visually stronger than body text, semantically earned by the material above, and connected by alignment or proximity rather than decorative arrows.
- Dense pages still preserve visible reading channels and normally keep audience-facing body/annotation text within the 14–16 pt dense range. Increase information density first by replacing prose with a native diagram, chart, table, or compact equation—not by shrinking or overlapping text.
- Large visuals should be legible evidence, not thumbnails inserted to claim “图文并茂.” Crop and scale them around the relevant signal, then place interpretation close enough to read as one unit.

## Semantic color

Use two to four semantic color families on an ordinary slide. Reuse each family for the same meaning across the deck.

| Meaning | Main | Light fields |
|---|---|---|
| Strategy and method | `#8062AA` | `#E4DEEC`, `#F1EEF5` |
| Input, observation, academic scaffold | `#4D94D8` | `#D7E0EF`, `#CFE5FE` |
| Feasible, safe, valid, structural | `#839F39` | `#E6F3E5`, `#D8F1CF` |
| Trajectory, feedback, warning | `#FD7F0E` | `#FDF1E6`, `#FECB9E` |
| Risk, error, negative result, key contrast | `#F14C4A` | `#FBE1E0`, `#FFF5F4` |
| Context and secondary structure | `#5F5F5F` | `#D8D8D8`, `#EDEDED`, `#F2F2F2` |

For system-validation evidence boards, the user-derived purple range `#5B4388`, `#695495`, `#BFB5EC`, `#CFC6E2` is available. Use `#FBD35A` only as a small highlight.

Color is not decoration-by-zone. A color must encode a role, state, causal thread, or comparison that remains stable.

## Typography

Use the role-based point-size ranges in [layout archetypes](layout-archetypes.md). This personal grammar adds one preference: when content is light, raise type size and the scale of its surrounding carriers together until the page feels intentionally occupied; when content is dense, preserve hierarchy and real projection readability rather than enforcing one fixed size across all roles.

Use Source Han Sans SC or Noto Sans CJK SC for Chinese, with Microsoft YaHei as the Windows fallback. Use Source Sans 3 for English, with Arial as fallback. Mathematics follows the font and roman/italic role contract in [native editability](native-editability.md); do not apply ordinary body-font styling to formulas.

Align with actual text-box coordinates, guides, and object geometry. Do not insert literal spaces to simulate columns or indentation.

## Positive patterns

- Unequal evidence zones organized by one dominant claim.
- A clear visual center supported by a narrow reasoning rail or integrator.
- Soft semantic fields behind native charts, formulas, or diagrams rather than decorative card wallpaper.
- Evidence-board compositions that keep sources traceable and visually distinct.
- Sparse connectors with clear direction and endpoints.
- Controlled density: abundant evidence with readable text and uninterrupted channels.
- Sparse-page scale calibration: limited content presented with larger readable type, expanded carriers, and visibly resolved junctions rather than a small composition surrounded by unused canvas.
- A broad light-gray evidence canvas inside a restrained white scaffold, used to unify text, figures, charts, and tables without turning them into equal cards.
- Mixed-evidence pages in which prose, a native visual carrier, exact values or symbols, and a short synthesis perform distinct roles.
- A compact lower-edge conclusion or recommendation that closes the reading path after the evidence.
- A coherent palette and outer scaffold combined with varied internal silhouettes.

## Anti-patterns and corrections

| Failure | Why it fails | Correction |
|---|---|---|
| Primary content compressed below the readable role range | Projection readability collapses and hierarchy becomes flat | Shorten, split, or promote evidence to a larger carrier; reserve 10–14 pt for captions, sources, and true metadata. |
| Overlap, clipped text, or overfilled panels | Hides hierarchy and may corrupt meaning | Recompose geometry/copy; do not cover the problem with a visual overlay. |
| Repeated equal rounded cards | Produces generic AI/UI rhythm and erases evidence importance | Use unequal regions determined by claim and evidence mass. |
| Empty decorative containers | Creates meaningless holes while pretending to add structure | Remove the container or assign it a real evidence/transition role. |
| Small content island plus large nonfunctional blank region | Makes limited content look unfinished and wastes projection area | Enlarge type, carriers, borders, and meaningful junctions as one system; recompose before adding decoration. |
| Literal-space alignment | Breaks under fonts, edits, and export | Use separate text boxes, tabs, tables, guides, or coordinates. |
| UI dashboard/card-grid appearance | Makes research evidence look like interface chrome | Use diagrams, figures, equations, tables, and causal/spatial arrangements as the primary carriers. |
| Same silhouette slide after slide | Removes pacing and hides narrative roles | Change archetype or evidence carrier while keeping scaffold and tokens. |
| Too many accent colors | Weakens semantics | Limit ordinary slides to two to four mapped color families. |
| Gray applied to every container or layer | Produces a muddy interface, weakens hierarchy, and confuses canvas with semantics | Use one broad neutral field; recover grouping with geometry and reserve color for meaning. |
| Copying a dense reference page literally | Inherits its collisions, clipping, source-specific identity, or fragile formula/chart rendering | Rebuild the composition from its evidence roles, then reflow and verify every editable object under the current content and fonts. |
| AI-template look | Repeated equal cards, generic gradients, decorative icons, and interchangeable slogans make the page feel generated rather than argued | Make visual hierarchy trace the actual claim/evidence relationship; vary silhouette for a reason, use source-specific evidence, and remove decoration that carries no meaning. |

Equal cards are permitted only when the content is genuinely a set of peer items under the same comparison conditions. They are never the default deck grammar.
Even then, equality governs semantic status, not small scale: size the peer system to the available canvas and the reading distance.
