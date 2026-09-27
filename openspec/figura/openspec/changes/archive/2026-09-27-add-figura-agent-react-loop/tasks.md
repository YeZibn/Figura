## 1. Persisted Provider Attempt State

- [x] 1.1 Add the provider-attempt model, lifecycle enum, `ActionKind.PROVIDER_ATTEMPT`, RunState projection, and `provider_outcome_unknown` terminal code without changing public Run fields.
- [x] 1.2 Add the `run_provider_attempts` table, constraints, same-Run response reference, and transactional SQLite v3-to-v4 migration; preserve existing migrations from schema versions 0–2.
- [x] 1.3 Implement compare-and-swap attempt claim from a current model checkpoint, persisting its sequence and record/tool history cursors before any Provider request.
- [x] 1.4 Require the active attempt when committing a Provider response; atomically link response, continuation, tool-call facts, attempt outcome, and next checkpoint.
- [x] 1.5 Implement atomic known-failure, unknown-outcome, and orphaned-start recovery transitions; ensure the last case requires the exclusive Run lock and never dispatches a request.
- [x] 1.6 Extend state reconstruction and integrity validation for attempt ordering, status/link constraints, checkpoint consistency, and legacy response prefixes; cover migration and stale/concurrent transition cases.

## 2. Build Provider Requests From Durable Run History

- [x] 2.1 Add the fixed v1 system instruction asset and an Agent request builder that returns a non-streaming Provider request using the Run's explicit provider/model and `project_provider_tools()` output.
- [x] 2.2 Project persisted input, ordered assistant tool calls, matching tool observations, and response-scoped private continuation into valid Provider messages without maintaining a separate transcript.
- [x] 2.3 Add canonical bounded tool-result/error serialization and reject incomplete batches, unavailable registry versions, or unresolved tool attempts before Provider dispatch.
- [x] 2.4 Enforce Provider request limits by removing only oldest complete resolved rounds; preserve the user input and newest complete round and fail before claiming an attempt if the required context does not fit.
- [x] 2.5 Add focused request-builder coverage for initial history, multiple tool rounds, continuation association, errors, registry mismatch, and complete-round trimming.

## 3. Implement the Checkpoint-Driven ReAct Scheduler

- [x] 3.1 Add `AgentExecutor` to dispatch only the current checkpoint action through RunCoordinator, the selected ProviderClient, and DurableToolExecutor.
- [x] 3.2 Hold the existing per-Run lock across Provider claim, one synchronous request, and outcome commit; on restart resolve a still-started Provider attempt as unknown rather than resending.
- [x] 3.3 Extend `DurableToolExecutor.execute_pending()` with an optional logical-call slice limit and have Agent execution pass only the remaining per-Run budget.
- [x] 3.4 Enforce the 8 Provider-attempt and 32 distinct started-tool-call budgets from durable rows/facts, with no separate mutable counter and no over-budget dispatch.
- [x] 3.5 Accept only valid `tool_calls` responses or nonempty `stop` answers; route unsupported/empty responses, known Provider failures, unknown outcomes, and finalization through their specified safe terminal transitions.
- [x] 3.6 Return unresolved tool-attempt state without automatically replaying or reconciling it; return terminal Runs without side effects.
- [x] 3.7 Add scheduler coverage for text-only completion, ordered multi-tool rounds, tool failure observations, invalid model outcomes, budgets, lock contention, and terminal-state no-ops.

## 4. Verify Recovery and Compatibility End to End

- [x] 4.1 Add fake-Provider integration coverage for a complete multi-round Run and restart after committed response, completed tool batch, and unresolved Provider attempt.
- [x] 4.2 Verify unknown Provider outcomes and crashes after attempt claim never cause an implicit resend or provider/model fallback.
- [x] 4.3 Verify v0–v3 store migration retains old Run identities, records, continuations, tool facts, checkpoints, and terminal states without synthetic attempt rows.
- [x] 4.4 Run focused Figura provider/runtime/tool tests, the full Python suite in the `agent` Conda environment, and `openspec validate add-figura-agent-react-loop --strict --store figura`; resolve regressions without changing the declared scope.
