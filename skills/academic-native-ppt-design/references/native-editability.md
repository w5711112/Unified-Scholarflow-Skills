# Native Editability

This file owns the semantic editability contract. “Editable” means that the PowerPoint object representing a meaning can be selected and changed without reconstructing the slide.

## Semantic owners

| Semantic content | Required owner in the final PPTX | Permitted source/route | Not equivalent |
|---|---|---|---|
| Titles, labels, values, body copy, citations | Native PowerPoint text runs in text boxes or shape text frames | Theme-aware text with explicit language/font roles | Text baked into a slide screenshot or decorative image |
| Simple diagrams, arrows, relationships, boundaries | Native shapes and native connectors with meaningful grouping/order | DrawingML shapes/connectors generated directly or reconstructed from an approved scene model | A bitmap diagram, unconnected line segments that only look joined, or editable labels over a flattened diagram |
| Complex structured diagrams | Native/editable conversion route whose output survives selection and round-trip inspection | Constrained SVG/scene representation converted to DrawingML; keep semantic text native | An inserted SVG called “editable” merely because it is vector |
| Charts | Native PowerPoint chart with editable series/categories when the target format supports the chart | Chart object plus embedded/source data and explicit axis/legend semantics | Screenshot of a plot when the underlying data and chart are available |
| Tables | Native PowerPoint table when technically representable | Native cells, text, borders, and fills; complex paper tables may be simplified with source trace | A table screenshot used only to save layout time |
| Structured mathematics | Native OfficeMath/OMML with real fractions, matrices, scripts, operators, and symbol roles | Direct OMML generation or a conversion route verified to emit OMML in the PPTX package | Plain Unicode fake scripts, PNG equations, ordinary text approximations, or OLE equation objects |
| Photographs, screenshots, paper result figures | Separate replaceable source image with crop/provenance retained | PNG/JPEG/WebP/SVG as appropriate to the source and PowerPoint compatibility | One full-slide raster that absorbs native claims, labels, diagrams, tables, or formulas |
| Video or motion evidence | Native PowerPoint media object when reliable in the delivery environment; otherwise a replaceable poster frame plus explicit linked/local video path | Embed a compatible MP4 when portability is required and tested; use a poster frame with play affordance and timestamp/caption for a controlled linked-media route | A screenshot presented as if it were playable, an unverified external URL, or an unlabeled video thumbnail |
| Decorative vector artwork | Replaceable SVG or converted native shapes, chosen by compatibility and edit needs | Keep the original SVG alongside the deck when conversion is not reliable | Treating optional vector decoration as the semantic owner of academic content |

No final slide may be a single full-slide raster image. A hybrid slide is acceptable only when the image is a legitimate replaceable source asset and the editable semantic layers remain separate.

## SVG conversion boundary

SVG insertion preserves vector appearance but does not automatically provide object-level PowerPoint editability. Use one of two explicit routes:

1. **Replaceable vector asset:** retain an SVG for decorative or source-derived artwork whose internal elements do not need semantic editing.
2. **Native conversion:** convert a constrained SVG/scene into DrawingML shapes, connectors, and native text; then verify grouping, text, connector behavior, gradients, and PowerPoint round-trip safety.

If conversion loses semantic structure, use simpler native geometry or keep a replaceable asset and record the limitation. Do not claim editability from visual fidelity alone.

## Screenshot and video evidence

- Crop screenshots to the relevant interface state while retaining enough context to identify the system; add native labels, callouts, and status interpretation outside the bitmap.
- A video poster frame must show what the audience should inspect, not merely a generic first frame. Keep the title, duration/timestamp, and one-sentence takeaway as native text.
- Verify playback on the intended PowerPoint environment when media is embedded or linked. If playback cannot be verified, present the poster frame honestly and keep the source video beside the deck; do not imply that the thumbnail is an embedded playable object.
- Keep media replaceable: do not bake surrounding claims, captions, arrows, or conclusions into the video frame.

## Mathematics contract

New structured formulas use OfficeMath/OMML. The object must preserve mathematical structure, not just glyph placement:

- fractions are fractions, matrices retain rows/cells, and super/subscripts are script objects;
- variables are italic;
- functions, operators, units, and explanatory text are roman;
- math font is STIX Two Math, with Latin Modern Math or Computer Modern as fallback;
- surrounding prose and term labels remain native text with the appropriate Chinese/English font.

Plain text is acceptable only for genuinely linear non-structured notation whose semantics remain unambiguous. It is not a shortcut for a fraction, matrix, cases expression, multi-level script, or aligned equation.

## Explicit waiver

PNG, ordinary Unicode text, or OLE may replace a technically representable structured formula only after an explicit user waiver. Record:

- the exact formula or object scope;
- why native OMML is not being delivered;
- the resulting editability/compatibility limitation;
- who accepted the tradeoff.

A deadline, visual similarity, or tool inconvenience is not itself a waiver. The waiver does not authorize flattening the rest of the slide.

Verification and failure routing are owned by [quality gates](quality-gates.md).
