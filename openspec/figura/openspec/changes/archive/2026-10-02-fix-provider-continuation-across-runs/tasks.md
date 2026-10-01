## 1. Resolve source-Run continuations during request projection

- [x] 1.1 Build a request-local continuation index from the target and prior `RunState` values, keyed by `(run_id, response_record_id)`; reject duplicate or inconsistent source identities.
- [x] 1.2 Attach a stored continuation only to its matching assistant message and only when its Provider identity matches the selected Provider; preserve continuation content and format unchanged.
- [x] 1.3 Add request-assembly coverage for multiple prior Runs and responses, verifying each continuation maps to the correct assistant message and tool history remains ordered.
- [x] 1.4 Retain coverage that `SessionHistory` contains no continuation and that provider-mismatched continuation is not copied into another Provider's request.

## 2. Separate local Provider preparation from transport dispatch

- [x] 2.1 Refactor `ProviderClient` into local preparation and one-shot dispatch phases; preparation validates the model/request and builds the provider payload without transport activity.
- [x] 2.2 Keep the prepared call private and non-serializable, excluding prompt, continuation, and payload content from its representation; do not persist it or retain an old compatibility call path.
- [x] 2.3 Update `tests/test_figura_provider.py` to verify local policy rejection makes no transport call and dispatch sends the exact prepared payload once.
- [x] 2.4 Keep generic Provider request validation owned by preparation rather than repeating it in Agent request assembly.

## 3. Move preparation before the durable Provider attempt

- [x] 3.1 Prepare the selected Provider call before entering the attempt-claim path; on local preparation failure, commit the existing bounded Run failure without a Provider attempt or attempt outcome.
- [x] 3.2 Under the per-Run lock, re-read and compare Run status, checkpoint revision, and next action before claiming; discard stale prepared calls without dispatch.
- [x] 3.3 After a successful durable claim, dispatch the already-prepared call exactly once and retain the existing response, known-failure, unknown-outcome, and recovery transitions.
- [x] 3.4 Add executor and attempt regression coverage proving preparation failure creates no attempt, transport sees a committed attempt before dispatch, and stale or failed claims do not dispatch.

## 4. Verify continuation policy and privacy boundaries

- [x] 4.1 Add an integration regression for a later DeepSeek thinking-mode Run with tools, confirming all required historical assistant continuations are replayed from their source responses.
- [x] 4.2 Verify missing or incompatible continuation fails locally before attempt claim, without dropping history, changing Provider selection, disabling thinking, or contacting the transport.
- [x] 4.3 Preserve and run the existing MiMo continuation-policy coverage without asserting unverified upstream requirements; verify continuation remains absent from public history, events, and diagnostics.
- [x] 4.4 Run focused Figura request, provider, executor, and attempt tests, then run the full Python suite with `conda run -n agent python -m pytest -q`.
  - Focused Figura regressions: 155 passed. Full suite: 974 passed, 8 failed; all 8 failures are legacy `tests/test_gateway.py` readiness cases under `src/chartagent`, and the current `agent` environment has no `OPENAI_API_KEY`. This change only modifies `src/figura` and its Figura tests.
