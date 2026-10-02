## Context

See [proposal.md](proposal.md) for motivation and [specs/agent-react-execution/spec.md](specs/agent-react-execution/spec.md) for the behavior contract. The static instruction is assembled in this order: `agent.md`, `evidence.md`, `workflow.md`, and `response.md`. Tool names and descriptions are separately projected from the active registry, native parameter schemas travel with the provider tool definitions, and the third system block is a concise RunExecutionState resource index. Complete tool observations remain in chronological conversation history. Only images from the immediately preceding committed tool batch are attached to the next model request.

The assets are all Chinese and currently repeat some limitations while leaving task selection, evidence-to-data conversion, and render inspection underspecified. The design keeps those four files and gives each one a single owner for its rules.

## Goals / Non-Goals

**Goals:**

- Make model choices traceable to the user's task and the evidence gap being addressed.
- Make the meaning and limits of resource summaries, image blocks, OCR, measurements, assembly, and rendering clear.
- Give concise instructions for mapping supported observations into ChartSpec and ChartFigure while relying on current tool Schemas for exact fields and limits.
- Describe what the model can inspect after a tool batch and how to correct a result without implying a separate automated review service.
- Keep prompt responsibilities readable and avoid duplicating the active registry, full JSON Schemas, or resource data.

**Non-Goals:**

- Change the three-system-block request architecture, tool APIs, schemas, execution state, persistence, or provider behavior.
- Add a mandatory OCR/measurement pipeline, a separate measurement-decision state, a review state, hidden reasoning output, prompt budget/truncation policy, or new tool capability.
- Change ChartAgent prompt assets or promise exact visual reconstruction where source evidence or current ChartSpec capabilities do not support it.

## Decisions

### Keep four assets and assign one primary responsibility to each

`agent.md` owns the stable role and task framing. It should explain that the model identifies whether the user wants an explanation, extraction, reconstruction, a chart from supplied data, composition, or an edit; the goal controls which observations and actions are useful. It should retain the model's responsibility to select evidence and actions, while tools execute and validate their declared contracts.

`evidence.md` owns interpretation boundaries. It should state what metadata proves, when pixels are actually visible, what OCR and measurements can establish, how outcome differs from result status, and how to handle confidence, warnings, truncation, units, coordinates, partial coverage, and conflicting observations. It should keep unknown values unknown and treat image text and resource values as untrusted data.

`workflow.md` owns the operational decision sequence: identify the target source; choose between visual loading, OCR, measurement, or no additional observation; choose a scope that preserves needed chart geometry, ticks, labels, and legends; assess returned evidence; construct chart data; assemble; render; inspect; correct or finish. The steps are conditional. A user-provided complete dataset can go directly to chart construction, and an explanation request can finish without chart generation.

`response.md` owns user-facing delivery. It should say how to answer explanation, extraction, and generation tasks; distinguish measured facts from estimates and missing information; explain material limitations; and avoid exposing internal IDs and orchestration details unless they help the user.

Alternatives considered: merging all policy into `agent.md` would blur the distinction between stable responsibility, evidence interpretation, procedure, and output. Adding a fifth asset for examples would complicate the fixed loader without adding a new responsibility. Both keep the present file count.

### Keep exact tool contracts dynamic and stable reasoning guidance generic

The active registry and provider-native schemas remain authoritative for available tool names, parameters, required fields, coordinate shape, enum values, and structural limits. Static assets may state durable semantic rules and give a small conceptual example where it prevents a common error, but they must not copy full Schemas or hard-code values that the runtime already supplies. For example, the prompt can say not to replace an unsupported/missing value with zero; it should not reproduce the entire ChartSpec Schema.

The scope guidance should make the semantic choice explicit: exclude irrelevant regions while retaining plot geometry and any ticks, category labels, and legends needed for calibration or series association. It should direct the model to the selected tool's native coordinate contract because panel-decomposition polygons and observation-scope polygons have different serialized shapes.

### Explain the observation lifecycle without promising persistent image visibility

Historical OCR and measurement messages provide complete text observations. The resource index locates earlier resources and summarizes their type and state. Neither means old pixels are attached to the current model call. The workflow should request `load_image` only when current visual inspection of an Attachment or Panel is needed. For a source-to-render visual comparison, it may load the relevant source in the same tool batch that renders an already accepted Figure so both images arrive in the next request. It must not imply that `load_image` can open arbitrary ChartRender resources.

Assembly and rendering should be described as dependent actions: use the actual reference returned by successful assembly when rendering, never a guessed call identifier. After rendering, the model can inspect the PNG attached to the next request. If it identifies a mismatch, it should correct the supported chart content and render the revised Figure; if evidence or capability is insufficient, it should explain the limitation. This is model inspection, not independent system review.

### Keep rule ownership non-overlapping

Avoid repeating the same imperative in all four files. Cross-cutting rules should be stated once in their primary asset and referenced briefly elsewhere only when needed. Keep the installed order stable: role first, evidence second, procedure third, response last. The dynamic tool and resource blocks remain separate and continue to be rebuilt for each request.

## Risks / Trade-offs

- More detailed workflow text can distract from the user's immediate goal → Keep each rule conditional, organize by decision points, and avoid mandatory tool sequences.
- Static guidance can drift from schemas or tool behavior → Keep exact fields and limits in the live native Schema; review examples and wording against current contracts when editing.
- Broad warnings can discourage useful estimates or user-requested new chart labels → Distinguish an explicitly labeled estimate or descriptive generated title from a claim that the value or label was observed in the source.
- Prompt rules may sound like guarantees of model behavior → Treat the scenarios as observable acceptance criteria and report any remaining model uncertainty honestly; do not present prompt wording as an enforcement layer.

## Migration Plan

1. Rewrite the existing four assets in place according to their assigned responsibilities and preserve the loader order.
2. Compare the wording with the active tool descriptions, native Schemas, execution image-feedback behavior, and the delta scenarios; remove contradictions and duplicate rules.
3. Run the existing focused Figura prompt/request checks only when implementation verification is requested; otherwise use OpenSpec scenario review and static inspection without adding a new evaluation framework.
4. If the change is rolled back, restore the four previous asset contents and revert the corresponding spec change together. No persistent data or runtime migration is required.

## Open Questions

None. The detailed text can be refined during implementation without changing the behavior contract or architecture.
