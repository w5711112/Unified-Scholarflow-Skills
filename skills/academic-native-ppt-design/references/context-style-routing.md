# Context-Aware Style Routing

This file owns presentation-context selection and the mapping from context to visual components. Contexts overlap; they are communication postures, not isolated templates.

## Shared invariants

Every mode keeps the same non-negotiable base:

- source truth and explicit uncertainty;
- native editability for claims, labels, diagrams, tables, charts, and structured mathematics;
- readable typography, functional blank space, visible hierarchy, and no overlap or clipping;
- one cumulative deck argument with explicit slide-to-slide transitions;
- style derived from the current communication job, not copied wholesale from a reference deck.

Greater freedom means more variation in density, annotation, page silhouette, and work-in-progress evidence. It never means weaker factual discipline, unreadable type, decorative filling, or careless alignment.

Public-facing does not mean less rigorous. It raises the standard for selection, pacing, consistency, and visual finish without prescribing how dense a particular deck or slide must be.

## Pre-design context declaration

Before creating a new deck or materially redesigning one, state the context in the user-facing work update before proposing page geometry. Use one primary mode and at most one secondary mode:

```text
Context: <primary mode> [with <secondary mode> overlay].
Audience: <who will judge or use the deck>.
Decision goal: <what they should understand, accept, critique, or authorize>.
Posture: <working | accountable | evaluative | public-facing>.
Density strategy: <derived from information/evidence load, page budget, speaking time, slide roles, and readability>.
Enable: <selected visual components>. Suppress: <components or reference habits intentionally not used>.
```

If the user has already named the setting, infer the rest from the sources and state the assumption. Ask only when two plausible contexts would materially change the argument or deliverable. A short review or single-slide edit may use a compact one-sentence declaration; do not create ceremony unrelated to the requested change.

## Primary modes

| Mode | Communication job | Posture and density caution | Prefer | Suppress by default |
|---|---|---|---|---|
| `group-meeting` | Enable peers to critique the current inference, failure, or next experiment | Working; no density preset—use the actual evidence load and available pages | Process traces, failed cases, uncertainty, annotated figures, compact evidence boards, visible open questions | Ceremonial section pages, sales language, over-polished storytelling that hides unresolved work |
| `client-progress` | Make completed work, evidence, variance, risk, and next action accountable | Accountable; no density preset—balance evidence obligations against page/time limits | Milestone structure, screenshots/video stills, status evidence, issue–decision–action chains, bottom synthesis, restrained semantic status color | Raw derivations without a decision purpose, speculative claims, decorative system complexity, excessive ceremony |
| `thesis-defense` | Establish novelty, rigor, validation, contribution, and limitations | Evaluative; density follows the contribution/evidence chain and defense budget | Formal scaffold, method core, native formulas, controlled evidence boards, simulation/experiment comparisons, traceable conclusions | Casual annotations, unexplained decorative imagery, unbalanced claims, density that prevents oral explanation |
| `grant-proposal` | Make need, aims, feasibility, risk control, and payoff credible | Evaluative and persuasive; density follows required aims, evidence, and time/page constraints | Strong problem–aim–approach hierarchy, technical route, preliminary evidence, risk/impact synthesis, strategic accent color | Parameter dumps, long derivations, dashboard repetition, unsupported promotional language |
| `technical-review` | Let specialists inspect mechanisms, interfaces, assumptions, parameters, and risks | Evaluative; density follows the number of interfaces, assumptions, and inspectable evidence items | System diagrams, formulas, exact-value tables, comparison rails, failure modes, assumptions, interface evidence | Hero imagery without technical content, superficial summaries, tiny labels, implied equivalence across unmatched tests |
| `modeling-competition-defense` | Show a defensible chain from problem abstraction through model, solution, validation, and recommendation | Evaluative; density follows model complexity, required proof, and page/time budget | Neutral-gray canvas when suitable, numbered stages, formulas, native charts/tables, mixed-evidence pages, lower-edge synthesis | Literal copying of dense reference pages, crowded text, fragile formula rendering, source-specific identity |
| `research-talk` | Move a field-aware audience from a question to one memorable implication | Public-facing; no density preset—derive it from the evidence, allotted pages/time, and desired audience inspection | Hero evidence, progressive reveal, large figures, concise mechanism diagrams, deliberate pacing, strong section synthesis | Unreadable tables or derivations, several unsupported equal claims, excessive local annotations |
| `personal-introduction` | Present a coherent, credible professional identity and selected evidence | Public-facing; no density preset—derive it from selected experiences, page/time budget, and narrative role | Selective projects, role/evidence/outcome framing, strong image hierarchy, consistent identity, restrained narrative pacing | Exhaustive chronology without hierarchy, decorative self-branding, unrelated technical detail |

## Overlap and conflict resolution

Modes are intentionally composable. Choose one primary mode to set the deck's communication posture and optionally one secondary overlay to modify compatible details.

Examples:

- a laboratory update for an external partner can be `client-progress` with a `technical-review` overlay;
- a formal research progress defense can be `thesis-defense` with a `group-meeting` overlay for open questions;
- a competition pitch can be `modeling-competition-defense` with a `research-talk` overlay to sharpen selection and pacing without predetermining density.

Resolve conflicts in this order:

1. Shared invariants always hold.
2. The primary mode controls argument emphasis and visual posture; it does not assign average density.
3. The secondary mode may add components but cannot reverse the primary communication job.
4. The actual claim and available evidence choose the slide archetype; a mode never forces an unsuitable carrier.
5. A user-authorized template may override visual tokens and fixed scaffold geometry, but not evidence truth, editability, legibility, or source-specific permissions.

Do not average incompatible defaults into a vague middle. Record which component wins and why in the deck's `styleProfile`.

## Component selection

When route B is active, select named components from [personal visual system](personal-visual-system.md). Selection is component-level, not source-level. A reference deck may support several components, but activating one component does not admit its other layouts, identity, colors, or defects.

## Density derivation

Never infer density from the presentation mode alone. Derive it in this order:

1. Inventory the information and evidence that must survive into the deck; distinguish mandatory support from optional context.
2. Resolve the permitted or practical page count and speaking time. If the user has not fixed them, propose a range from the source load and state the assumption.
3. Distribute claims and evidence across that budget before designing individual pages. More available pages may permit narrower slide roles; a tight page budget may require denser but still readable evidence compositions.
4. Classify each resulting slide as sparse, medium, or dense from its actual carriers and labels, then apply the adaptive layout rules. Do not back-fill a sparse page or compress a dense one merely to match a mode stereotype.
5. Rebalance the page plan when any slide would violate the body-text floor, evidence legibility, oral explainability, or functional-blank-space rules.

Mode affects which evidence deserves emphasis and how it is narrated. Total information load, mandatory evidence, page/time budget, and slide role determine density. The same mode may legitimately produce sparse, medium, or dense decks on different tasks.
