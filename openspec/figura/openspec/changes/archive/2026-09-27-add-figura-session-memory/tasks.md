## 1. Session-scoped Run reads and creation ordering

- [x] 1.1 Add a validated read operation that returns only the target Run's lower-ordinal RunState aggregates from the same Session in ascending ordinal order within one SQLite read transaction.
- [x] 1.2 Validate Session ownership, target Run existence, prior Run terminal status, and attachment ownership while loading history; reject nonterminal or invalid prior state without returning a partial history.
- [x] 1.3 In the Run creation write transaction, preserve idempotency lookup first, then reject a distinct create request when the Session already has a `running` Run; retain exact replay behavior for the existing Run.
- [x] 1.4 Add Run repository tests for ordinal ordering, Session isolation, terminal-state checks, concurrent distinct creates, and active-Run idempotent replay.

## 2. Provider-neutral Session Memory projection

- [x] 2.1 Add immutable role-specific projection models for `SessionHistory`, `UserMessage`, `AssistantMessage`, `MemoryToolCall`, and `ToolMessage` with the fields defined in `design.md`.
- [x] 2.2 Implement a pure projector that maps Run inputs, model responses, ordered tool calls, and matching tool results into a complete conversation while omitting lifecycle events, final-answer references, attempt metadata, and provider continuation payloads.
- [x] 2.3 Fail closed when an earlier Run contains an incomplete tool batch, unresolved tool attempt, mismatched result, invalid source reference, or unsupported historical fact; never fabricate or selectively omit a message.
- [x] 2.4 Add Memory projection tests for multiple Run order, user attachment order, text-only and tool-call responses, success and failure observations, final-answer de-duplication, continuation boundaries, and incomplete history rejection.

## 3. Agent request integration

- [x] 3.1 Load the target Run's Session history before each model action and prepend it to the current Run's input and committed response/tool prefix in `AgentRequestBuilder`.
- [x] 3.2 Resolve every current and historical attachment ID through the owning Session and preserve each user message's text-then-image order in the Provider request.
- [x] 3.3 Remove complete-round trimming and validate the complete request with the existing Provider validator before claiming a Provider attempt; preserve current-Run continuation attachment and omit prior-Run continuation.
- [x] 3.4 Add Agent request tests proving all same-Session Runs are included, other Sessions are excluded, final answers are not duplicated, and older tool rounds are not removed.
- [x] 3.5 Add fail-before-claim tests for Provider message/text/image/schema limits, missing historical attachments, invalid historical registry versions, and incomplete prior tool work; assert no Provider attempt is claimed and the Provider client is not called.

## 4. Regression validation

- [x] 4.1 Run the focused Figura repository, memory projection, attachment, Provider validation, and Agent request test files in the `agent` Conda environment.
- [x] 4.2 Run the full Figura Python test suite and `git diff --check`; record any existing unrelated workspace changes separately.
