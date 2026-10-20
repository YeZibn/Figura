## 1. Define the canonical Provider stream

- [x] 1.1 Add the typed Provider stream event contract and explicit per-Provider/model streaming capability declarations.
- [x] 1.2 Convert each configured Provider adapter to parse text, tool-call, usage, terminal, and private continuation events into the shared contract.
- [x] 1.3 Replace non-stream response normalization with terminal-stream assembly and reject incomplete or unsupported streams before producing a normalized response.
- [x] 1.4 Add transport phase controls for connect and request transmission, disable hidden SDK/HTTP retries, and remove the total generation timeout.
- [x] 1.5 Add Provider adapter and transport tests for fragmented UTF-8/SSE events, long waits, heartbeats, terminal events, connection closure, malformed events, and DeepSeek continuation distinctions.

## 2. Unify durable Provider request and attempt records

- [x] 2.1 Define canonical logical Provider request and physical attempt records for Agent and context-compaction purposes, including frozen contract/policy identities and phase diagnostics.
- [x] 2.2 Replace the split request-binding persistence with one canonical request repository and one attempt ledger, including atomic phase updates and terminal transitions.
- [x] 2.3 Add a direct SQLite migration that preserves completed facts and checkpoints, migrates request estimates and retry metadata, closes incompatible in-flight work safely, and validates the migrated database atomically.
- [x] 2.4 Update Runtime codecs, validation, indexes, triggers, event projections, and persistence tests to accept only the canonical schemas.

## 3. Use one Provider execution and retry coordinator

- [x] 3.1 Implement shared attempt claiming, phase reporting, cancellation, failure classification, durable retry scheduling, and recovery for every Provider request purpose.
- [x] 3.2 Route ordinary Agent and tool-call model turns through the streaming coordinator; commit only complete normalized responses and execute only complete validated tool-call batches.
- [x] 3.3 Route compaction summaries through the same coordinator, remove duplicated operation request binding and attempt counting, and retain validation plus checkpoint compare-and-swap semantics.
- [x] 3.4 Add Agent, retry, cancellation, restart, duplicate-billing uncertainty, and compaction fallback regression tests.

## 4. Expose safe Provider progress and transient text

- [x] 4.1 Extend Gateway progress projections with allowlisted Provider purpose, attempt, and phase fields while preserving durable `run_id:sequence` event identity.
- [x] 4.2 Deliver Session-scoped assistant text deltas as transient SSE messages without durable event IDs or persistence; exclude reasoning and tool-call fragments.
- [x] 4.3 Update the shared frontend run controller and Figura conversation view to render ordered provisional deltas, reset on retry, detect gaps after reconnect, and converge on canonical committed history.
- [x] 4.4 Add Gateway and frontend tests for event replay, transient delta ordering, reconnect gaps, retry reset, Session isolation, and terminal convergence.

## 5. Remove the old request path and verify the complete contract

- [x] 5.1 Remove `stream=False`, non-stream dispatch and normalization branches, old binding decoders, and compaction-specific attempt scheduling.
- [x] 5.2 Run the focused Provider, Agent, Runtime migration/recovery, compaction, Gateway, and frontend test suites.
- [ ] 5.3 Run the full Python test suite, frontend build and smoke checks, strict OpenSpec validation, and `git diff --check`.
- [ ] 5.4 Verify against each configured Provider that a request lasting beyond the former timeout remains open while live, explicit transport failure is classified by phase, and no partial response or tool effect is committed.

## Verification notes

- Focused Provider, Agent, Runtime migration/recovery, context-compaction, Gateway, and frontend checks pass. Frontend production build and smoke checks pass; strict OpenSpec validation and `git diff --check` pass.
- The full Python suite was run: 1,296 passed, 35 failed, and 1 skipped. All 35 failures reference absent `tests/fixtures/legacy_charts/` images or `tests/fixtures/real_chart_diagnostic_manifest.json`; these fixtures are not present in this checkout.
- Live Provider checks were not sent, so task 5.4 remains open.
