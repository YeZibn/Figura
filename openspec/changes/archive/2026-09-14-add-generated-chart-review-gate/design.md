## Context

See `proposal.md` for the motivation and scope. The current Agent dispatches a
tool call, sends any generated image to the visual-observation sink, and lets
the next model response become a final answer when it contains no more tool
calls. The Gateway currently persists an image marked `generated_chart` as a
final artifact during that sink callback.

The previous chart-generation change already provides deterministic
ChartSpec, Matplotlib-artist, layout, font, and encoded-PNG checks. This design
adds a later publication gate for semantic review without replacing those
checks or creating a second authoritative renderer.

## Goals / Non-Goals

**Goals:**

- Make review completion a machine-enforced postcondition for generated chart
  publication and qualified final answers.
- Keep candidate images available for the Agent's visual review while keeping
  them out of the final artifact route until promotion.
- Bind every review to one run, candidate image, and immutable ChartSpec
  version so retries and duplicate events cannot cross-contaminate results.
- Preserve Agent freedom to select evidence and correction tools within the
  required review phase.
- Make review state visible in memory, trace events, Gateway projections, and
  bounded result metadata.

**Non-Goals:**

- Do not require pixel-identical equality between a source image and a
  generated image; rendering style and dimensions may differ.
- Do not treat an unstructured model claim such as "looks correct" as a
  verifier result.
- Do not force one fixed order for OCR, chart sensors, visual inspection, or
  ChartSpec correction.
- Do not add unlimited automatic retries or a second frontend rendering path.

## Decisions

### D1: Use a candidate-to-publication lifecycle

Treat the first generated image as a candidate rather than a final artifact.
The candidate carries an opaque candidate ID, the run ID, a digest of the
ChartSpec snapshot, source provenance when present, and a bounded review
requirement. It remains available to the Agent's visual evidence path and to
the internal reviewer, but the public generated-chart route only returns
promoted candidates.

Review completion atomically promotes a candidate to a final artifact. A
blocking failure, timeout, or exhausted retry leaves the candidate rejected or
expired and never issues a final artifact reference. A permitted warning may
promote the candidate with an explicit warning status.

This separates the model's need to inspect an image from the user's guarantee
that a published image passed the required checks. Existing persisted final
artifacts remain readable; only newly generated candidates use the gated
lifecycle.

### D2: Run the post-generation hook at the Agent dispatch boundary

The hook runs after a tool result has been normalized and before the generated
image is handed to the Gateway's final-artifact persistence path. It recognizes
the existing generated-chart metadata marker, creates one idempotent review
record, and changes the candidate state to `review_pending`.

The hook does not invoke a nested LLM loop. It exposes the candidate image and
a bounded review instruction to the next Agent turn, allowing the Agent to
choose its evidence and correction actions. The hook also records a trace and
memory event so the frontend and run history can distinguish a candidate from a
published chart.

The Gateway remains a second publication guard. Its promotion operation accepts
only a candidate with a matching completed review record; a direct attempt to
store a pending candidate as a final `generated_chart` is rejected.

### D3: Use a dedicated review operation with deterministic evidence first

Add a model-facing review operation for a candidate and its associated
ChartSpec snapshot. The operation performs independent, reproducible checks
against the encoded candidate image and returns bounded evidence. For a
source-linked candidate it also uses the authorized source attachment and
compares the source evidence, ChartSpec, and candidate structure.

The review covers chart type, categories and order, series identity, point or
sector count, values or coordinates, labels, and material ambiguity. Existing
chart sensors and OCR can supply evidence, but the comparator must not depend
on PNG pixel snapshots.

When deterministic evidence cannot resolve a semantic association, the review
operation returns a bounded `requires_model_decision` result. The Agent can
inspect the supplied candidate and source evidence, then submit a structured
decision tied to the review ID and evidence references. The system records that
decision as a review result; free-form text alone cannot complete the gate.

For direct structured-data generation with no source-image equivalence claim,
the applicable renderer and artifact checks are sufficient unless the caller
explicitly requests semantic review. Source-linked generation always requires
the review operation.

### D4: Enforce the gate as a postcondition, not a fixed tool sequence

The Agent can call tools in any useful order while a review is pending. Before
accepting a final answer that claims a generated result, the Agent runtime
checks all generated candidates in the current run:

- no required candidate remains `review_pending`;
- every required deterministic check has completed without a blocking issue;
- every source-linked candidate has a completed semantic review;
- every published candidate has a matching candidate ID and ChartSpec digest;
- warning publication, when allowed, is represented explicitly.

If the model returns a final answer while a required review is pending, the
runtime appends bounded review state and continues the run instead of marking
the result as a successful final answer. If the step budget or review timeout
is reached, the run ends with a transparent incomplete or failed review state
and no verified artifact; it does not loop indefinitely.

### D5: Model review controls correction, not publication authority

The model decides whether to inspect another evidence source, revise the
ChartSpec, retry rendering, or report an unresolved issue. It does not decide
that a candidate is published merely by saying that it is correct.

Publication authority belongs to the review record and Gateway promotion
check. A review result is accepted only when it is linked to the current
candidate, run, ChartSpec digest, and bounded evidence. Blocking semantic or
fidelity findings reject the candidate. Non-blocking readability findings can
produce `published_with_warning`, but completing review is still mandatory.

### D6: Make transitions idempotent and observable

Use a stable transition key based on run ID, candidate ID, and ChartSpec digest.
Repeated hook delivery creates no duplicate review record or artifact.
Promotion and rejection use an atomic state transition so two concurrent
review completions cannot publish the same candidate twice.

Record bounded events for `generated_chart_candidate`, `chart_review_started`,
`chart_review_completed`, `generated_chart_published`, and
`generated_chart_rejected`. Persist review status and bounded diagnostics in
the run projection, while excluding image bytes, local paths, credentials, and
provider payloads.

### D7: Bound retries and cleanup

Each candidate may have a configured maximum number of review or regeneration
attempts and a review deadline. A correction creates a new candidate linked to
the previous review record; it never mutates the semantic identity of an old
candidate. Rejected or expired candidate bytes are removed according to the
existing retention policy, while the bounded review event remains for audit.

## Risks / Trade-offs

- [A model may call the review operation but still make a wrong semantic
  judgment] -> Require deterministic evidence where possible, preserve
  uncertainty as warning or failure, and never treat an unsupported free-form
  claim as completion.
- [The additional model turn increases latency and provider cost] -> Require
  semantic review only for source-linked or explicitly requested workflows;
  use the existing deterministic checks for direct structured-data generation.
- [A pending candidate may consume storage while waiting for review] -> Keep
  candidate retention bounded, use one candidate per attempt, and clean up on
  timeout or rejection.
- [A hook can be bypassed by a direct caller of the renderer] -> Enforce the
  same promotion check in the Gateway artifact boundary and reject pending
  candidates there.
- [Strict gating can prevent a useful chart when only presentation is
  imperfect] -> Distinguish blocking fidelity or semantic failures from
  permitted warnings and expose the warning in every projection.
- [A failed review can cause repeated Agent turns] -> Apply per-review timeout,
  maximum attempts, and a terminal `review_incomplete` state.

## Migration Plan

1. Add candidate and review state representations, stable identity fields, and
   bounded trace and memory records while keeping existing final artifacts
   readable.
2. Insert the post-generation hook at the Agent dispatch boundary and change
   Gateway persistence to store candidates as non-final until promotion.
3. Add the independent review operation, model-visible review instructions,
   structured review completion, and the final-answer postcondition gate.
4. Add atomic promotion and rejection handling, bounded retry and timeout
   cleanup, and frontend/run projections for candidate and review states.
5. Add unit, integration, and end-to-end tests for every transition, bypass
   attempt, source-linked comparison, warning, retry, timeout, and duplicate
   event case.

Rollback can disable the mandatory semantic-review policy for new runs while
retaining deterministic renderer checks. Candidate records can be marked
expired and existing published artifacts require no migration.
