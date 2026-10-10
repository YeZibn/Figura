## 1. Select active Run process coverage

- [x] 1.1 Extend compaction selection to combine eligible prior Run interactions with the active Run's committed prefix in chronological order.
- [x] 1.2 Apply the shared `floor(C / 10)` raw-tail budget across that combined process stream while preserving complete interactions and assistant tool-call batches.
- [x] 1.3 Keep unresolved Provider work, uncommitted records, incomplete tool batches, and uncrossable abnormal history raw; preserve already-covered active prefixes if the Run later becomes abnormal.
- [x] 1.4 Add selector tests for active-only history, mixed prior/active history, a cutoff inside the active Run, oversized newest interactions, incomplete work, and abnormal completion after earlier coverage.

## 2. Persist and project an active-Run checkpoint

- [x] 2.1 Update Runtime checkpoint and operation validation to permit coverage inside the running target Run only at or before its frozen committed record/tool prefix and at a complete interaction boundary.
- [x] 2.2 Preserve existing compare-and-swap, source-reference ownership, stale-prefix, stop-request, and integrity checks for same-Run coverage.
- [x] 2.3 Update ordinary request projection to apply a checkpoint to the active Run's process while retaining its exact input as the native user message and keeping post-cutoff interactions raw.
- [x] 2.4 Add Runtime and request-projection tests for commit, read, same-Run continuation, subsequent Run projection, invalid cursor, and recovery when the Run later completes or becomes abnormal.

## 3. Build and recover active-Run summaries

- [x] 3.1 Allow summary construction to read an active Run only through the frozen committed prefix, passing its original input, attachment IDs, and source reference separately from newly covered process messages.
- [x] 3.2 Update the compaction prompt so a running source Run is represented as ongoing and covered observations are not mistaken for Run completion.
- [x] 3.3 Bind and reconstruct the same active source slice, capacity-derived budgets, rendered prompt, and Provider request descriptor across retries and process restart.
- [x] 3.4 Preserve preflight capacity checks, four-attempt summary retry behavior, checkpoint CAS, and fallback to the previous checkpoint or complete raw projection without truncation.
- [x] 3.5 Add summary-request and executor tests for active Run inputs, source-reference validation, summary preflight, retry/restart identity, post-summary re-estimation, and failure fallback.

## 4. Update specifications and implementation documentation

- [x] 4.1 Sync the approved active-Run compaction behavior into the main `session-context-compaction` specification and Figura Agent documentation.
- [x] 4.2 Document that the 80% estimate includes the full active request, while `floor(C / 10)` applies to process history spanning prior Runs and the active committed prefix; user-input text remains separately preserved.
- [x] 4.3 Run focused compaction, request-projection, summary, Runtime persistence/recovery, and prompt tests, then run the Figura test suite and `git diff --check`.
