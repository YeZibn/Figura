## Context

See `proposal.md` for the motivation. The current runtime creates a generated
candidate in the Agent loop, runs deterministic chart sensors in
`ChartReviewManager`, and exposes `review_generated_chart` as a normal model
tool when a source-linked candidate still needs a semantic decision. The LLM
client already supports multimodal messages and calls without tools, while the
attachment boundary can retrieve an authorized source image.

The existing assembly and renderer checks are still needed for structural and
artifact safety. They are different from semantic chart review and must not be
silently removed as part of this change.

## Goals / Non-Goals

**Goals:**

- Make semantic review automatic and VLM-only for every candidate whose policy
  requires source or explicit semantic review.
- Give the reviewer a paired source image, candidate image, and immutable
  ChartSpec so it can reason about orientation, layout, labels, associations,
  and values as one visual problem.
- Keep the reviewer isolated from the main ReAct history and from every tool
  schema, while retaining a bounded structured result for the Agent, Gateway,
  trace, and frontend.
- Make publication a code-owned state transition and make pending, failed,
  timeout, and retry-exhausted states impossible to bypass with model text.
- Preserve targeted OCR, CV, geometry, and layout tools for source restoration
  before `assemble_spec`; they remain auxiliary evidence tools, not review
  implementations.

**Non-Goals:**

- Replacing OCR, CV, geometry, or layout tools as optional source-observation
  aids during chart understanding.
- Asking the VLM to prove PNG decodability, dimensions, ChartSpec schema
  validity, or other mechanical artifact properties.
- Adding a user-facing manual review button or another review tool.
- Introducing a second provider configuration or a new model-selection policy
  in this change.

## Decisions

### 1. Use a separate internal VLM call after rendering

After a semantic-review-required candidate is created, the Agent runtime will
make one nested call through the existing LLM client with a dedicated reviewer
prompt and no `tools` argument. The call will use the current configured
provider and model, so this change adds one request without adding provider
configuration or changing the main model's model-selection behavior.

The reviewer request will contain:

1. the authorized source image, when the policy is source-linked;
2. the generated candidate image; and
3. a bounded JSON representation of the immutable ChartSpec and review
   identifiers.

The request will be constructed as a fresh multimodal conversation. It will
not be appended to the main Agent history, and the reviewer will not receive
the main Agent's tools, previous reasoning, unrelated attachments, local
paths, or raw provider responses.

This is preferred over asking the main model to self-review in its final
answer: a nested call guarantees that the review happens after every eligible
render and that a final text response cannot omit the review step. It also
keeps the review instruction short and specialized instead of expanding the
already stable Agent system prompt.

### 2. Separate semantic review from artifact safety

The review manager will continue to own candidate identity, attempt limits,
deadlines, idempotency, and publication states. Its deterministic path will be
reduced to safety checks that do not interpret the source chart, such as:

- immutable ChartSpec structural validity;
- supported media type and non-empty content;
- PNG decoding and declared dimensions;
- configured byte/dimension limits; and
- blank or otherwise unusable encoded-artifact checks.

The chart sensors will no longer run from the candidate review transition.
The VLM result will supply the semantic checks, while the safety result and
the VLM result must both pass before publication. This preserves a reliable
byte-level boundary without allowing a positional sensor mismatch to decide
whether a rotated or horizontal chart is semantically correct.

### 3. Parse a strict bounded reviewer contract

The reviewer prompt will show the complete response contract, not only a list
of field names. The VLM must return exactly one JSON object with exactly these
top-level fields:

```json
{
  "decision": "pass | pass_with_warning | fail",
  "confidence": 0.0,
  "checks": {
    "chart_type": "pass | warning | fail",
    "orientation": "pass | warning | fail",
    "layout": "pass | warning | fail",
    "data_mapping": "pass | warning | fail",
    "labels": "pass | warning | fail",
    "readability": "pass | warning | fail"
  },
  "issues": [
    {
      "code": "string",
      "location": "string",
      "severity": "warning | error",
      "message": "string"
    }
  ]
}
```

The prompt will require the reviewer to internally proceed in four stages:

1. establish the evidence roles: ChartSpec describes intended chart data and
   structure, the source image describes source visual semantics, and the
   candidate image describes the actual rendered result;
2. establish the coordinate frame, distinguishing whole-canvas rotation,
   horizontal-versus-vertical chart orientation, axis direction, category
   order, plot bounds, and the zero baseline;
3. apply chart-specific checks for bar, line, pie, and scatter charts, such as
   bar baseline alignment, line point order, pie slice-to-label association,
   and scatter x/y placement;
4. classify only material semantic or readability problems, without treating
   font, anti-aliasing, or other harmless styling differences as failures.

The decision relationship is part of the contract:

- `pass` requires every check to be `pass` and `issues` to be empty;
- `pass_with_warning` permits only `pass` or `warning` checks and warning
  issues, and must contain at least one warning detail;
- `fail` requires at least one `fail` check or one `error` issue;
- inability to verify a critical relationship is not a pass and must be
  represented as a warning or failure according to its impact.

The parser will enforce the exact top-level fields, exact check names, decision
enum, confidence range, allowed check statuses, maximum issue count, maximum
field lengths, issue severity, and the decision consistency rules. Missing,
malformed, extra-field, or ambiguous output will be a review failure; it will
never be coerced into a pass. Stored review metadata will contain only the
bounded normalized result, not the raw VLM response or prompt.

### 4. Keep the main Agent tool surface unchanged except for removal of review

The main Agent will retain `assemble_spec`, `render_chart`, source loading,
and optional evidence tools. `review_generated_chart` will not be registered
and will not appear in the system prompt. A render observation will still be
available to the main model as a preview, but its candidate metadata will say
that review is automatic and will include the normalized outcome once
available. The static main-agent prompt will explicitly state that a rendered
image is never a final artifact by itself, and that visual inspection by the
main model cannot replace the automatic VLM review.

The main-agent prompt will use the lifecycle fields with distinct roles:

- `publicationStatus` is authoritative for whether the result may be called
  published;
- `reviewStatus=completed` means only that the review call ended, not that the
  review passed;
- `decision`, `checks`, and bounded `issues` explain the review outcome and
  guide correction;
- `published` permits an unqualified publication claim;
- `published_with_warning` permits publication only with the warning retained;
- `pending`, `rejected`, `review_failed`, `timed_out`, and
  `retry_exhausted` never permit a verified or published claim.

On a blocking VLM result, the Agent receives bounded review-gate context with
the affected candidate and corrective fields. It may call `assemble_spec` and
`render_chart` for a new candidate. The rejected candidate remains immutable,
attributable, and unpublished; a new candidate gets a new candidate/review
identity. The prompt will require the correction sequence to be
`assemble_spec` followed by `render_chart`; the main Agent must not use OCR,
CV, geometry, or layout tools after rendering to replace or override the
automatic VLM review.

### 5. Enforce the gate at every terminal path

The Agent loop will treat both `pending` and `failed` review states as gate
obligations. A no-tool model response cannot finalize a run while an eligible
candidate is unresolved. If the candidate failed and the retry budget is
exhausted, the runtime returns a bounded non-published outcome rather than
accepting a model claim that the chart was verified. The same rule applies at
the step-budget and reviewer-timeout boundaries.

This code-owned transition is necessary even with a VLM reviewer: the VLM
decides semantic correctness, but it does not control artifact publication.

The main-agent prompt will also distinguish source-linked and direct-data
candidates. A source-linked candidate without authorized source evidence cannot
claim source-fidelity review. A direct-data candidate without a source-fidelity
obligation receives only its applicable structural and encoded-artifact safety
checks and must not claim equivalence to a source image.

### 6. Keep observability and client presentation lifecycle-based

The internal call will emit bounded model and chart-review trace events marked
as an internal review with zero tools. Review completion, rejection, timeout,
and publication will remain separate events. Gateway and frontend projections
will reuse the existing candidate/publication fields and add the review mode
and normalized diagnostics where needed; they will not expose raw review
prompts, provider output, image bytes, or local paths.

## Risks / Trade-offs

- [VLM may miss a subtle data or pixel-level mismatch] → Require side-by-side
  source/candidate inputs, include the immutable ChartSpec as a reference,
  require a staged coordinate and chart-type-specific inspection, preserve
  confidence and warnings, and never treat malformed or uncertain output as a
  clean pass.
- [The extra call increases latency and token cost] → Make exactly one review
  call per candidate attempt, reuse the configured client/model, bound image
  and response sizes, and apply the existing timeout/retry policy.
- [A VLM response may not be valid JSON] → Use a dedicated compact prompt,
  bounded parsing and schema validation, and convert invalid output to a
  non-published review failure.
- [Removing the review tool breaks callers that depended on it] → Treat the
  removal as the declared breaking change, update the Agent prompt and tests,
  and expose the same lifecycle metadata through automatic review results.
- [Nested review calls can become part of the wrong run or history] → Bind the
  candidate, review ID, run ID, and ChartSpec digest before applying a result;
  keep the nested messages outside the main history and reject mismatches.
- [A failed candidate can still be mentioned by a model final answer] → Keep
  publication code-enforced, check both pending and failed gate lists on every
  terminal path, and return an explicit non-published outcome when no retry is
  possible.

## Migration Plan

1. Add the internal VLM review request/response boundary and normalized result
   parser behind the existing candidate lifecycle.
2. Replace sensor-based semantic review with artifact safety checks plus the
   automatic VLM result application.
3. Remove `review_generated_chart` from runtime registration, prompt text, and
   model-facing tests; update failed-gate terminal handling.
4. Update trace, Gateway, frontend projections, and regression tests for pass,
   warning, fail, malformed response, timeout, and retry paths.
5. Run the focused review/Agent/Gateway suites, then the full Python suite and
   frontend checks in the `agent` Conda environment and documented client
   commands.

Rollback is a code rollback to the previous review adapter and prompt contract.
Historical bounded review metadata remains readable because the existing
candidate and publication enum values are preserved; new runs after rollback
may use the old tool path until the migration is reapplied.
