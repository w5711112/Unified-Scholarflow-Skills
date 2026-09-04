# Skill Landscape

This runtime register is derived from the dated [authoritative shortlist source](../../../docs/research/2026-08-31-ppt-skill-landscape-source.md). It supports route selection; it is not a dependency list, exhaustive census, maturity ranking, or star-count ranking. Re-open the source record and repository before adopting code.

## Evidence scale

- **Core:** directly useful to native PPTX, academic narrative, template distillation, editability, or QA.
- **A-tier reference:** contains a substantial reusable idea or implementation, but does not satisfy the whole contract by itself.
- **Partial/boundary:** useful for a bounded concern; incompatible with at least one default route or not an independent implementation.

## Core register

| Project / repository | Output route | Strongest reusable quality | Editability / math evidence | Maturity / important risk | How this skill uses it | License / verification status |
|---|---|---|---|---|---|---|
| Codex `Presentations` runtime (installed; URL N/A) | Local `.pptx` authoring and render workflow | Current runtime integration for creation, inspection, and rendering | Native-object authoring is available; OfficeMath still requires package evidence | Implementation varies by installed runtime version | Execution substrate when present; this skill owns academic structure and design grammar | N/A — installed runtime, not a repository license claim |
| [Anthropic skills](https://github.com/anthropics/skills) | Agent skill → PptxGenJS/native `.pptx` route | Maintained PPTX construction and QA patterns | Native text/shapes/tables/charts where emitted; no blanket OMML guarantee | General-purpose; repository paths and tooling can change | API/geometry and QA reference, not narrative authority | Unknown — re-verification required |
| [PPT Master](https://github.com/hugohe3/ppt-master) | Presentation-design skill → PPTX workflow | Full-deck strategy and design orchestration | Native object and OMML behavior require the local gates | Compatibility and fixture evidence must be rechecked | Reference for deck strategy, design contract, and staged production | MIT — verified in the 2026-08-31 review input; re-check repository LICENSE before reuse |
| [EasySlides](https://github.com/Rimagination/easyslides) | Papers/Markdown/reference decks → editable `.pptx` | Academic material-before-layout and reference-deck distillation | Editable-object claims exist; structured OMML needs independent proof | Output and round-trip behavior need current fixtures | Reference for academic interview, source-first flow, and template grammar | Unknown — re-verification required |
| [powerpoint-skill](https://github.com/Noi1r/powerpoint-skill) | Dedicated agent skill → PowerPoint/PPTX | PowerPoint-specific skill surface rather than a catalog wrapper | Native-object and math behavior require fixture recheck | Current implementation and QA depth are not assumed | Candidate native-PPTX implementation reference | MIT — verified in the 2026-08-31 review input; re-check repository LICENSE before reuse |
| [research-skills / scholar-slides](https://github.com/luwill/research-skills) | Research-oriented skill route; final format requires re-verification | Scholarly-content and research-slide specialization | Native PPTX ownership and OMML are not established by current evidence | Repository bundle scope must be inspected before reuse | Reference for scholarly narrative, citations, and audience framing | MIT — verified in the 2026-08-31 review input; re-check repository LICENSE before reuse |
| [Scene Native PPTX](https://github.com/denelwu-GH/scene-native-pptx) | Scene/SVG model → DrawingML/native `.pptx` | Semantic layers, native reconstruction, and honest hybrid boundaries | Native DrawingML/text and replaceable-asset modes; OMML remains separate | Constrained authoring and real PowerPoint round-trip are necessary | Reference for semantic reconstruction and SVG-to-native boundaries | Unknown — re-verification required |

## A-tier and reference register

| Project / repository | Output route | Strongest reusable quality | Editability / math evidence | Maturity / important risk | How this skill uses it | License / verification status |
|---|---|---|---|---|---|---|
| [SlideWeaver](https://github.com/RFYoung/slideweaver) | Dedicated slide-composition workflow | Reusable orchestration ideas in an independent implementation | Native PPTX and structured-math evidence require fixture review | Academic narrative and final-format behavior are not assumed | Composition/orchestration reference only | MIT — verified in the 2026-08-31 review input; re-check repository LICENSE before reuse |
| [thesis-defense-pptx-skill](https://github.com/zouchenzhen/thesis-defense-pptx-skill) | Thesis-defense skill → PPTX-oriented workflow | Narrow thesis-defense specialization | Native editability and OMML need re-verification | Domain templates can overpower content-driven architecture | Domain-language and defense-sequence reference | Unknown — re-verification required |
| [Academic PPT Plugin](https://github.com/SHALINS428/Academic-PPT-Skill) | Academic presentation plugin/skill | Academic-PPT task framing and reusable plugin packaging | Native OMML/editability needs independent fixtures | Generic academic layouts may not match personal grammar | Academic workflow and packaging reference | MIT — verified in the 2026-08-31 review input; re-check repository LICENSE before reuse |
| [agents-skills / scholar-ppt-cn](https://github.com/Jensen-Yao/agents-skills) | Chinese scholarly-presentation skill route | Chinese academic specialization | Native output and structured math are not established by current evidence | Bundle scope and maintained entrypoint require re-verification | Chinese scholarly wording and task-routing reference | Unknown — re-verification required |
| [qiaomu-ppt](https://github.com/joeseesun/qiaomu-ppt) | Dedicated PPT workflow | Presentation-specific guidance in an independent project | Native editability/math require fixture evidence | AGPL obligations affect reuse and redistribution | Reference only after license and output review | AGPL-3.0-only — verified in the 2026-08-31 review input; re-check repository LICENSE before reuse |
| [slide-skill](https://github.com/icgma/slide-skill) | Focused slide-skill route | Compact presentation-skill packaging | Final output route, editability, and math need re-verification | Maintenance and compatibility evidence are not assumed | Discovery and workflow reference | Unknown — re-verification required |
| [PPTX-Template-Skills](https://github.com/CxyZyr/PPTX-Template-Skills) | Template-oriented skill → PPTX route | Template-following and reusable-template specialization | Native object/math behavior requires fixture review | Template use can bypass architecture unless A/B routing is enforced | B-route template reference; never a substitute for A on new builds | MIT — verified in the 2026-08-31 review input; re-check repository LICENSE before reuse |
| [academic-pptx-skill](https://github.com/Gabberflast/academic-pptx-skill) | Academic PPTX skill | Academic presentation specialization | Native output and structured math need fixtures | License evidence conflicts and blocks code reuse until resolved | Conceptual reference only while license is unresolved | Conflict — SKILL metadata says Proprietary while README search result says MIT; re-check repository LICENSE before reuse |
| [pptx-skills](https://github.com/jiandong01/pptx-skills) | Repository bundle of PPTX skills | Multiple presentation routes in one maintained location | Each skill's output/editability/math must be evaluated separately | A bundle or catalog count is not independent implementation evidence | Discovery source; promote individual entries only after inspection | MIT — verified in the 2026-08-31 review input; re-check repository LICENSE before reuse |
| [MiniMax PPTX generator](https://github.com/MiniMax-AI/skills/tree/main/skills/pptx-generator) | Agent workflow → PptxGenJS slide modules → `.pptx` | Runnable modular slide generation and compilation | Inherits native objects PptxGenJS emits; OMML is not established | Page-local modules can encourage isolated-slide or repeated-template behavior | Module/compilation reference under this skill's deck-level plan | Unknown — re-verification required |

## Partial and boundary register

| Project / repository | Output route | Strongest reusable quality | Boundary / reason not default | License / verification status |
|---|---|---|---|---|
| [cn-academic-spark](https://github.com/wycmochi/cn-academic-spark) | Chinese academic presentation workflow | Domain-specific Chinese academic route | Formula PNG is the default and conflicts with the native-math rule without explicit waiver | Unknown — re-verification required |
| [competition-ppt-template-first-skill](https://github.com/che626/competition-ppt-template-first-skill) | Template-first visual workflow | Strong visual/template matching | Whole-slide visual underlay conflicts with semantic native ownership as a default | Unknown — re-verification required |
| [ppt-agent-skills](https://github.com/sunbigfly/ppt-agent-skills) | Agent workflow → HTML presentation | Agent-oriented presentation construction | HTML output is not native editable PPTX | Unknown — re-verification required |
| [Slidev](https://github.com/slidevjs/slidev) | Markdown/Vue → HTML/PDF/PNG/PPTX export | Interactive composition, code, diagrams, and math inspiration | Export does not itself prove native PowerPoint semantic ownership or OMML | Unknown — re-verification required |
| [Marp](https://github.com/marp-team/marp) | Markdown → HTML/PDF/PPTX/images | Fast prototypes and theme exploration | Export requires flattening inspection and is not the default native route | Unknown — re-verification required |
| [many-ppt-skills](https://github.com/brycewang-stanford/many-ppt-skills) | Catalog of presentation skills | Broad discovery surface | Catalog, not one independent implementation; deduplicate by canonical lineage | Unknown — re-verification required |

## Search accounting

The broad discovery pass scanned about **36.8k URLs** and found roughly **180 PPT-related hits**, of which roughly **110 were actual skill pages**. Deduplication by canonical repository, implementation lineage, and independent behavior left about **20–30 serious independent projects**. These are approximate research counts, not a claim of exhaustive coverage or 100 unique mature projects.

## Continuation-search protocol

1. Record search date, query, index/source, and raw result count in a new dated research record.
2. Resolve each result to a canonical repository; mark broken or ambiguous links pending rather than guessing.
3. Deduplicate forks, mirrors, translations, wrappers, and catalogs by implementation lineage.
4. Classify the actual output route: native OOXML/PPTX, application automation, HTML/browser, image/raster, reconstruction, or catalog.
5. Inspect maintained source and at least one output fixture for text, shapes/connectors, charts, tables, images, OfficeMath/OMML, OLE, and full-slide rasters.
6. Record the strongest observed quality, important conflict, license evidence, activity, platform, and compatibility risks. Stars are not quality evidence.
7. Promote a project only when its reusable strength is evidenced and its conflicts with this skill are explicit.
8. Update the dated authority first, then synchronize this runtime register.
