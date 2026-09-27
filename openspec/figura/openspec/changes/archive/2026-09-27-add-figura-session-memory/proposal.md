## Why

Each Figura Run durably retains its own user input, model responses, and tool results, but the Agent currently builds requests from only the current Run. A later Run in the same Session therefore loses the earlier conversation, while the existing request policy may trim old complete tool rounds to fit Provider limits.

## What Changes

- Add a Session Memory domain that reconstructs prior conversation messages from existing Run facts, ordered by Run ordinal, without adding a second durable message store or database migration.
- Include the full same-Session history in every model request, together with the current Run's committed progress. Preserve user-message attachment order, assistant tool-call order, and matching tool observations.
- Remove request-history trimming and summarization. Validate the complete request against existing Provider limits before claiming a Provider attempt; fail without dropping history or dispatching when it does not fit.
- Keep provider-private continuation attached only to its source response within its original Run. Do not carry continuation into a later Run.
- Serialize new Runs within a Session: allow at most one `running` Run per Session, with an idempotent replay of that same Run still allowed. This keeps Session history ordered and stable.
- Fail closed before Provider dispatch when durable facts cannot form a complete valid history, including an unresolved tool batch or an unresolvable historical attachment.

## Capabilities

### New Capabilities
- `session-memory`: Reconstruct complete, ordered same-Session conversation history from durable Run facts.

### Modified Capabilities
- `agent-react-execution`: Build requests from complete Session history and reject over-limit requests without trimming.
- `run-execution-core`: Prevent overlapping active Runs within one Session so later Runs have a stable history boundary.

## Impact

- Add provider-neutral history projection and Session-scoped history reads under `src/figura/memory/` and the existing runtime store/repository boundary.
- Update `RunCoordinator` creation validation and `AgentRequestBuilder` request assembly; retain existing attachment resolution, tool registry validation, and Provider request limits.
- Update the Figura OpenSpec capabilities and add regression coverage for ordering, isolation, complete tool rounds, continuation ownership, concurrency, and fail-before-claim behavior.
- No new SQLite message table, persistent message fields, API request fields, or frontend protocol fields are required. Existing Run facts remain authoritative.
