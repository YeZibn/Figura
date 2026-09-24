## Context

See `proposal.md` for the observed failure. `GatewayService._build_runtime_for_run` prepares per-run candidate persistence, review-input resolution, and execution-gate callbacks, then filters keyword arguments against the selected runtime factory's signature. The default `_build_runtime` does not declare or forward those three callbacks, even though `create_agent_runtime` accepts them. The filter therefore turns an integration defect into an absent optional dependency; the review flow later interprets the absent candidate sink as an unsuccessful persistence result.

## Goals / Non-Goals

**Goals:**

- Make the Gateway runtime-factory contract explicit and preserve all review lifecycle dependencies end to end.
- Fail explicitly when a required integration is not provided.
- Keep actual candidate-store failures non-publishable and distinguishable from missing wiring.
- Cover the default Gateway runtime path, not only injected test doubles.

**Non-Goals:**

- Change review policy, retry limits, candidate identity, ChartSpec format, or publication rules.
- Change HTTP/SSE payloads or add a frontend presentation change.
- Make previously failed runs pass retroactively.

## Decisions

### Use one explicit Gateway runtime-factory contract

Define the runtime factory's supported per-run inputs explicitly, including
`execution_gate_sink`, `candidate_input_sink`, and
`candidate_input_resolver`. The default Gateway builder must accept and forward
all three to `create_agent_runtime`. Remove signature-based filtering that
silently drops unsupported keyword arguments; update test factories to implement
the same contract. Keep `create_agent_runtime`'s optional integrations usable by
non-Gateway callers, while requiring them at the Gateway run boundary.

An explicit callable protocol is preferred over adding a second callback
container or retaining a permissive compatibility adapter: the failure comes
from two runtime-factory signatures drifting apart, and the contract should
make that drift visible.

### Separate missing wiring from a real storage failure

Validate the required Gateway integrations before Agent execution. A missing
callback is a bounded runtime-integration/configuration failure; it is not a
`candidate_storage_failure`. If the configured persistence callback is invoked
and storage rejects or cannot save the image and ChartSpec, retain the existing
fail-closed candidate-storage outcome. Do not invoke semantic review or publish
an unpersisted candidate.

### Keep review and recovery on the same candidate inputs

The Gateway-provided resolver must reach the review manager so review and
recovery use the stored candidate image and the exact ChartSpec digest that
were persisted for that candidate. Gate updates must reach the owning run
through the same runtime construction path. No alternate review state or
publication path is introduced.

### Test the real composition boundary

Use focused unit coverage for argument forwarding and failure classification,
plus a Gateway integration test that exercises the default runtime builder with
stubbed model/reviewer dependencies and a temporary database. Assert that the
candidate persistence callback receives both image and ChartSpec, the resolver
returns them for review/recovery, and gate transitions reach the run. Keep a
separate case where storage itself fails and verify the candidate remains
unpublished.

## Risks / Trade-offs

- [Injected runtime factories currently use narrower signatures] → Update all in-repository factories and test doubles to the explicit contract; incompatible factories should fail visibly instead of silently losing lifecycle behavior.
- [A real storage outage can still reject a valid rendered candidate] → Preserve fail-closed publication semantics and report the actual storage failure distinctly.
- [Runtime construction errors could expose implementation details] → Convert integration failures to bounded safe run errors; do not include callback representations, local paths, or raw exceptions in events.

## Migration Plan

No database or event-schema migration is required. Update the runtime contract,
default builder, and injected factories together; then run Gateway/review
regression tests. Existing historical runs remain unchanged. New runs use the
correctly wired callbacks. If the wiring change must be rolled back, revert the
runtime integration code; the existing fail-closed review behavior prevents an
unreviewed candidate from being published.
