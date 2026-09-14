## 1. Review Lifecycle and Contracts

- [x] 1.1 Define bounded candidate, review, and publication status models with
  stable candidate IDs, review IDs, run IDs, and ChartSpec digests.
- [x] 1.2 Define the review policy that distinguishes direct structured-data
  generation from source-linked redraws and records the required checks.
- [x] 1.3 Extend generated-chart result metadata and event payloads with
  candidate, review, and publication state without exposing image bytes,
  local paths, or provider payloads.

## 2. Candidate Persistence and Publication Gate

- [x] 2.1 Change generated-image persistence to retain a bounded candidate
  before final publication while preserving access for the Agent's visual
  review.
- [x] 2.2 Add an atomic candidate promotion operation that accepts only a
  matching completed review record and returns the final artifact reference.
- [x] 2.3 Reject pending, failed, expired, timed-out, or mismatched candidates
  at the Gateway final-artifact boundary.
- [x] 2.4 Preserve read compatibility for existing published generated-chart
  artifacts and keep candidate retrieval scoped to the owning run and session.

## 3. Post-Generation Hook and Agent Gate

- [x] 3.1 Add an idempotent post-generation hook at the Agent tool-dispatch
  boundary that recognizes generated chart images and enters `review_pending`.
- [x] 3.2 Expose a bounded review instruction and candidate visual evidence to
  the next model turn without invoking a nested LLM loop.
- [x] 3.3 Add a model-facing review operation that accepts only a candidate
  reference and its bound review context, with a structured result schema.
- [x] 3.4 Enforce the final-answer postcondition so pending or failed required
  reviews cannot be reported as verified or published results.
- [x] 3.5 Allow the Agent to select evidence, revise the ChartSpec, and retry
  while preserving the mandatory gate and current candidate identity.

## 4. Independent Semantic Review

- [x] 4.1 Implement deterministic candidate-to-ChartSpec comparison for bar,
  line, scatter, and pie outputs using existing sensors or bounded evidence.
- [x] 4.2 Add source-linked comparison using authorized source attachments and
  verify chart type, category order, series identity, values, labels, and
  unresolved ambiguity.
- [x] 4.3 Add structured model-decision handling for associations that cannot
  be resolved deterministically, binding each decision to review ID and
  evidence references.
- [x] 4.4 Classify blocking semantic or fidelity mismatches separately from
  permitted readability warnings and require explicit warning publication.
- [x] 4.5 Ensure direct structured-data generation uses deterministic checks by
  default and does not claim equivalence to a source image.

## 5. Retry, Timeout, and Observability

- [x] 5.1 Add bounded review deadlines, retry counts, and terminal incomplete
  or retry-exhausted states for candidates and Agent runs.
- [x] 5.2 Create idempotent atomic transitions for duplicate hook delivery,
  repeated review results, concurrent promotion, and candidate replacement.
- [x] 5.3 Persist bounded review events and project candidate, review, warning,
  rejection, and publication states through run history and Gateway responses.
- [x] 5.4 Clean up rejected or expired candidate bytes while retaining bounded
  audit metadata and preserving authorization checks.
- [x] 5.5 Update the desktop client to distinguish candidates, pending review,
  verified results, warning publication, and rejected results.

## 6. Regression and Acceptance Tests

- [x] 6.1 Add unit tests for lifecycle transitions, candidate/spec binding,
  policy selection, idempotency, and publication-state invariants.
- [x] 6.2 Add Agent tests proving a final answer cannot bypass pending review
  and that model-selected tool order remains supported.
- [x] 6.3 Add reviewer tests for chart-type, category, series, point, value,
  label, ambiguity, warning, and blocking-failure comparisons.
- [x] 6.4 Add Gateway tests for candidate isolation, atomic promotion,
  rejected-state access, duplicate events, cleanup, and legacy artifacts.
- [x] 6.5 Add end-to-end tests for source-image redraw, direct structured-data
  generation, successful review, warning publication, failed review, retry,
  timeout, and review-tool failure.

## 7. Verification

- [x] 7.1 Run focused Agent, chart-generation, Gateway, and frontend tests in
  the `agent` Conda environment where applicable.
- [x] 7.2 Run the complete Python test suite with `conda run -n agent python
  -m pytest -q` and resolve regressions.
- [x] 7.3 Run frontend build and smoke checks for the new review states.
- [x] 7.4 Run strict OpenSpec validation for the change and main specs, then
  run `git diff --check`.
