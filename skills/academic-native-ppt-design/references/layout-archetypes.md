# Layout Archetypes

Select an archetype only after the slide claim, evidence, and transition are known. The catalog order is not a preference ranking; the fifth approved archetype retains its established name **M9**.

Formula representation and math semantics are owned by [native editability](native-editability.md); this catalog only describes formula layout.

| # | Archetype | Narrative/content fit | Visual mass | Recommended evidence carriers | Continuity use | Failure modes |
|---:|---|---|---|---|---|---|
| 1 | Large domain — narrow reasoning spine — large domain | Relates two substantial systems, states, or scales through one explicit inference | Two dominant fields joined by a thin central spine | Domain diagrams, maps, before/after figures, short causal spine | claim → mechanism; comparison → implication | Treating the spine as decoration; equalizing the domains when one is primary; tiny labels in both fields |
| 2 | Dual evidence arena | Compares two evidence bodies under shared conditions | Two unequal but clearly comparable arenas with a shared baseline | Native charts, paired figures, experiment captures, shared metrics | result → comparison | Different axes/conditions, two unrelated mini-posters, duplicated legends |
| 3 | Causal explanation chain | Explains ordered cause, mechanism, and consequence | Directional sequence with one emphasized causal hinge | Native shapes/connectors, equations, state thumbnails, annotations | claim → mechanism; mechanism → prediction | Generic chevrons, ambiguous direction, too many branches, prose standing in for causality |
| 4 | Heterogeneous three-module composition with bottom integrator | Three distinct evidence modules jointly support one synthesis | Unequal upper modules feeding a broad lower integrator | Figure + chart + equation/table; synthesis band | local evidence → section synthesis | Three equal cards, weak integrator, modules that do not support one claim |
| 5 | **M9 asymmetric module constellation** | Genuinely heterogeneous, coupled systems or feedback structures with non-uniform module roles | One visual center with 3–7 unequal satellites and explicit coupling | Editable system modules, sparse connectors, local evidence insets | mechanism → prediction; multiple local facts → system implication | Using M9 for ordinary lists, orbit-like decoration, tangled connectors, equalized modules |
| 6 | Compact evidence board with unequal internal zones | Dense evidence that must be inspected together without losing hierarchy | Stable outer board; one dominant zone plus smaller supporting zones | Result figures, mini tables, concise callouts, source tags | experiment → result; local evidence → synthesis | Dashboard/card-grid appearance, decorative empty cells, unreadable captures |
| 7 | Method core with one or two mechanism insets | One central method needs local magnification or assumptions | Dominant method core with one/two subordinate insets | Editable method diagram, structured formula, zoomed mechanism, assumption box | gap → mechanism; mechanism → prediction | Insets competing with the core, repeated content, formula visually competing with the method core |
| 8 | Formula-centered explanation canvas | A structured equation is the claim carrier and terms must be interpreted | Large equation as center; surrounding semantic annotations | Structured formula, native term labels, small geometry or plot | claim → mechanism; mechanism → prediction | Equation too small or crowded, too many prose boxes, annotations that obscure symbol roles |
| 9 | Large table + experiment capture + comparison rail | Exact values and observed behavior must be read together | Large native table balanced by capture; narrow conclusion rail | Native table, replaceable experiment image, compact delta markers | experiment → result → comparison | Spreadsheet dump, tiny table type, uncited capture, rail repeating all values |
| 10 | Simulation–physical experiment comparison | Tests whether predicted and observed behavior agree | Shared comparison geometry with two evidence fields and one conclusion band | Matched plots, simulation capture, physical capture, native metric chart | prediction → experiment → result | Mismatched scales/time windows, visual parity implying false equivalence, absent uncertainty |
| 11 | Shared-geometry progressive reveal | Builds one complex mechanism or result across a controlled sequence | Same base geometry with one deliberate change per slide | Native diagram, highlighted states, incremental annotations | mechanism → prediction or experiment sequence | Unannounced geometry drift, too many changed elements, using repetition without progression |
| 12 | Hero evidence with a narrow reasoning rail | One figure/result is decisive and needs a concise interpretation path | One dominant evidence object plus a narrow explanatory rail | Paper figure, result chart, experiment image, 2–4 claim annotations | result → implication; opening promise; section synthesis | Decorative hero image, oversized screenshot with unreadable labels, rail becoming a second slide |

## Content- and budget-adaptive density

After mandatory claims/evidence and the deck's page/time budget are resolved, distribute them across slide roles before scaling individual pages. Density follows the resulting content load per slide. A sparse slide is not a dense slide with most objects removed, and no mode name is evidence that a slide should be sparse or dense.

| Observable content load | Required composition response |
|---|---|
| Sparse: a few short points, one compact result, or one simple relationship | Enlarge the primary type, carriers, borders, junctions, and useful internal spacing together until the content group has deliberate visual mass. Recompose before accepting a large empty field. |
| Medium: several evidence carriers with a clear hierarchy | Use the normal type scale and unequal zones; keep channels open without shrinking the whole composition. |
| Dense: multiple figures, formulas, tables, or long labels that must be inspected together | Simplify, restructure, or split first. Tighten spacing carefully and approach the type floor only after the content structure is sound. |

For sparse slides:

1. Start above the dense-page scale instead of treating a minimum as a target. Test primary body copy around 18–22 pt when content is light; 14–16 pt is appropriate for dense but readable body copy, structured notes, compact labels, metadata, and citations. A change such as 10.2 pt to 14/16 pt should trigger a reflow check, not merely a font-size substitution.
2. Expand the primary content group, not just the text. Increase container footprint, internal padding, figure crop, or diagram scale so the group occupies the useful canvas in both width and height rather than becoming a wide but shallow strip or a small central island. As a working check, a sparse slide's principal carrier system should usually occupy about 65%–85% of the usable content area after fixed title, footer, and page margins are removed.
3. Increase structural weight proportionally. A sparse page can support stronger primary borders or rules, commonly around 0.9–1.5 pt, and more visible connector/junction geometry, commonly around 1.2–2.0 pt with correspondingly larger nodes or bridge regions. These are working ranges, not fixed template constants.
4. Make transitions physically legible. When a connector, hinge, integrator, or handoff region carries meaning, give it enough length, thickness, and surrounding space to read as part of the composition. Do not add connections where no relationship exists.
5. Reject an arbitrary whitespace percentage as a production target. Interpret a request such as “at least 35%–40% whitespace” as a request for breathing room, not permission to maximize empty area. Treat a numeric percentage as binding only when the user explicitly says the exact value is non-negotiable or an authorized template demonstrably enforces it.
6. Recheck the page silhouette. If one blank region visually competes with or outweighs the principal content group, enlarge or recompose meaningful objects before adding decoration or inventing content. A continuous top, bottom, or side blank band comparable to the height or width of a major carrier fails unless it has an explicit narrative or template role.

Peer equality may justify equal status or equal containers, but never undersized type, undersized carriers, or a page dominated by unused space. Do not report “more whitespace than requested” as a success criterion; report what each preserved blank region does.

## Selection procedure

1. Confirm the primary/secondary modes, `styleProfile`, page/time budget, content load, and `densityStrategy` under [context-aware style routing](context-style-routing.md). Context controls posture and component eligibility, not density or archetype by itself.
2. Name the slide's primary relationship: comparison, causality, coupled system, synthesis, formula interpretation, exact-value inspection, prediction test, progression, or hero implication.
3. Inventory the evidence carriers and their relative importance.
4. Classify the content load produced by the current claim/evidence distribution and apply the adaptive-density response above before settling geometry. Rebalance the deck map if the page/time budget would force unreadable compression.
5. Select the archetype whose visual mass expresses that relationship.
6. If the Router activated B, apply only the `styleProfile.selectedComponents` from [personal visual system](personal-visual-system.md). Do not import other components merely because the same source deck supports both. Otherwise derive the visual system from the authorized brief or template without importing personal-library defaults.
7. Check the previous and next slide. Change silhouette or evidence carrier when repetition adds no analytical value, while preserving the declared context posture.

M9 receives priority only when the content contains genuinely heterogeneous coupled parts whose unequal roles and interactions are the point. For a peer list, a single equation, a two-way comparison, or a hero result, choose the matching archetype instead.

Archetypes are compositional contracts, not fixed templates. Ratios and region counts may change when content demands it; the narrative relationship must remain legible.

## Typography by role

Use point units (`pt`) for PowerPoint typography; do not transfer browser `px` values directly. An authorized template may set a different scale when it remains readable.

| Role | Working range without a governing template | Adjustment rule |
|---|---:|---|
| Deck title | 40–54 pt | Increase when the cover is intentionally sparse; do not fill a cover with body copy. |
| Slide title | 24–32 pt | Use the lower end on dense academic pages and the upper end on synthesis or content-light pages. |
| Section heading / key callout | 20–26 pt | Must be visually distinct from body copy without competing with the slide title. |
| Primary body | 16–20 pt | Prefer 18–20 pt when content is light; 16 pt is a common dense-page target, not a universal law. |
| Dense body / structured annotation | 14–16 pt | Use only with short lines, strong grouping, and projection-legibility checks. |
| Caption / source / metadata | 10–14 pt | Keep concise and close to its evidence; never use it for a primary claim. |

When content is sparse, scale typography, carriers, borders, figures, and meaningful junctions together. When content is dense, simplify or restructure before shrinking; 14 pt is the practical lower bound for audience-facing academic content unless an authorized template and real projection review justify an exception.
