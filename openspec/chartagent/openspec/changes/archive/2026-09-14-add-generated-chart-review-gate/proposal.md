## Why

Figura can now render and deterministically audit a ChartSpec, but a generated
chart may still be treated as a final artifact before the Agent has completed
an independent semantic review. This is especially risky when the ChartSpec
was inferred from an attached source image, so generated output needs an
explicit candidate state and a mandatory review gate.

## What Changes

- Add a post-generation hook that recognizes generated chart candidates and
  transitions them to `review_pending` before final publication.
- Require every candidate to pass the applicable deterministic artifact and
  render-fidelity checks before it can become a published generated chart.
- Require an independent semantic review for source-image redraw workflows,
  comparing the source evidence, ChartSpec, and generated image.
- Let the Agent choose review tools, evidence order, and correction or retry
  actions while preventing it from bypassing a pending or failed review.
- Separate candidate-image retention from final artifact publication and bind
  review results to the run, candidate, and ChartSpec version.
- Publish successful results as verified, publish recoverable warnings only
  with explicit status, and reject or regenerate candidates with blocking
  fidelity or semantic failures.
- Add bounded retry and timeout handling so a failed review cannot create an
  unbounded Agent loop.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `chart-generation`: require a post-generation review gate, candidate
  lifecycle, independent semantic review where applicable, and publication
  only after the required checks complete.

## Impact

- Affected Python Agent lifecycle, tool-dispatch hooks, generated-image
  transport, Gateway artifact persistence, and run/event state projection.
- The generated-chart result contract gains candidate, review, and publication
  status metadata without exposing image bytes, local paths, or provider data.
- Existing deterministic renderer and PNG checks remain the first validation
  layer; the change adds a later semantic gate rather than replacing them.
- Tests must cover mandatory transitions, skipped-review prevention, candidate
  cleanup, source-linked semantic comparison, warning publication, retries,
  timeouts, and Gateway authorization.
- This introduces a behavior change for callers that previously treated the
  first returned generated image as a final published artifact.
