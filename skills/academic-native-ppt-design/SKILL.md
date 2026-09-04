---
name: academic-native-ppt-design
description: Use when creating, substantially redesigning, template-following, or reviewing academic PPT/PPTX decks for group meetings, thesis defenses, grant presentations, project reports, research talks, native editability, or reusable personal presentation style.
---

# Academic Native PPT Design

Build academic decks as cumulative, source-traceable arguments and deliver PowerPoint structures that remain editable.

## Classify build action, presentation context, and style constraints

Classify these three dimensions independently. A context or personal style never replaces the build action, and a reference deck never activates all of its visual habits at once.

### 1. Build action

| Build action | Observable request | Required route |
|---|---|---|
| New deck | Create a deck from papers, notes, data, a brief, or a designated template | Enter A. Read [deck architecture](references/deck-architecture.md) before [layout archetypes](references/layout-archetypes.md), then read [native editability](references/native-editability.md) and [quality gates](references/quality-gates.md). |
| Major redesign | Change the argument, section order, transitions, slide roles, or most page structures | Enter A through the same route as New deck; architecture precedes geometry. |
| Personal-pattern or template distillation | Extract a reusable personal grammar, pattern library, or template rules without yet building/redesigning a deck | Enter B. Add A only when the request also creates/redesigns a deck or changes its argument, order, claims, or transitions. Add C only for explicitly requested or materially useful visual exploration. |
| Content-preserving restyle or template fill | Keep the argument, order, claims, and transitions unchanged while replacing content in established slots or applying a style | A may be omitted only after confirming those four elements remain unchanged. Read [layout archetypes](references/layout-archetypes.md), [native editability](references/native-editability.md), and [quality gates](references/quality-gates.md). |
| Localized edit | Change named slides, regions, or objects while preserving the rest of an existing deck | Record `targetSlides`, `protectedSlides`, and whether slide order, claims, or transitions change. If none change outside the target, do not rebuild the full deck map; read only the references that own the edit plus [quality gates](references/quality-gates.md). If order or narrative changes, enter A for the affected section. |
| Review | Diagnose an existing deck without building it | Read the reference that owns the concern: narrative, visual system/layout, editability, or QA. Do not mutate the deck unless asked. |

If it is unclear whether the argument, order, claims, or transitions will change, route through A.

### 2. Presentation context

Before creating a deck or materially redesigning one, name the primary presentation mode, optional secondary mode, audience, decision goal, posture, density strategy and its basis, enabled components, and suppressed components in a concise user-facing update. Derive density from the current information/evidence load, allowed page count, speaking time, slide roles, and readability; never assign it from the mode name alone. Read [context-aware style routing](references/context-style-routing.md) for the mode table and overlap rules.

Contexts are not isolated templates. Apply the shared invariants to every deck, let one primary mode set defaults, and use at most one secondary mode to add compatible behavior. If the user names a setting such as a group meeting, client progress report, defense, grant pitch, technical review, research talk, or personal introduction, infer the remaining fields and state the assumption. Ask only when the choice would materially change the result.

For new decks and major redesigns, persist the choice in the single `deck-map.json` defined by [deck architecture](references/deck-architecture.md). For a localized edit or narrow review, a one-sentence context statement plus the target/protected slide scope is sufficient; do not manufacture a deck-wide planning artifact.

### 3. Style constraint

- A user-designated PPTX, reusable personal grammar, or template-following request adds B: read [personal visual system](references/personal-visual-system.md), then select only the components admitted by the current context.
- For a New deck or Major redesign, B is added to A; it never bypasses deck architecture.
- For a confirmed Content-preserving restyle or template fill, B may operate without A under the unchanged-content condition above.
- Activate C only when the user requests a visual style board or visual exploration is materially useful; state its exploratory scope and keep it optional.

Use [skill landscape](references/skill-landscape.md) only when selecting or comparing an external production route.

## Route boundaries

- **A — design compiler core:** converts sources and the communication job into an argument, slide contracts, content-driven layouts, native PPTX, and verified delivery. A owns every Create and Major redesign request.
- **B — personal pattern library:** supplies tagged scaffolds, design tokens, evidence structures, and preferences as a component library. The active context selects a subset for A, or for a confirmed content-preserving route without A; B is neither an automatic clone instruction nor a single blended house style.
- **C — optional visual style board:** explores cover art, section openings, or composition alternatives in image/HTML form. C is never the default final slide surface and cannot silently replace native academic claims, labels, charts, diagrams, tables, or formulas with slide images.

When explaining or recommending an architecture, template system, or personal style grammar, explicitly name the presentation context and the responsibilities of active A, B, and C routes. If a route or component is inactive, say why instead of silently blending its responsibilities into another route.

When a user choice changes the route, record the choice and reload only the newly relevant references.

## Keep the workflow lean

Use one artifact for each concern: one `deck-map.json` when A is active, one final package audit, and one visual review route. Do not add parallel style plans, density plans, component registries, duplicate XML inspectors, or ceremonial hashes. Extend the existing reference that owns a rule instead of adding another process layer.
