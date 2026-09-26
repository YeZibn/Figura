## Why

Figura's three model providers can be called through a common client, but Figura has no durable Run identity or authoritative execution history. The next stage needs a transactional place to freeze the selected provider/model and record progress before Agent, tools, and transport are connected.

## What Changes

- Add Figura-owned SQLite persistence for minimal Session, Run, ordered ExecutionRecord, ExecutionCheckpoint, creation idempotency, and safe RunStreamEvent facts.
- Add an internal RunCoordinator boundary that validates a text-only request, resolves an explicit allowlisted and locally configured provider/model, and creates the Run, input record, initial checkpoint, idempotency mapping, and creation event in one transaction.
- Add atomic execution-commit and terminal-commit operations, with append-only records, monotonic per-Run sequences, guarded lifecycle transitions, and restart-readable committed state.
- Keep provider network calls, attachment ingestion, Agent and tool execution, private continuation storage, HTTP/SSE delivery, CLI, and frontend integration in later changes. This change does not change the existing `model-provider` behavior contract.

## Capabilities

### New Capabilities

- `run-execution-core`: Persist and read Figura Run identity, input, ordered execution facts, checkpoint, lifecycle, idempotency, and safe event projections through one application boundary.

### Modified Capabilities

None.

## Impact

- Adds Figura-only domain, application, and SQLite storage modules under `src/figura/`; the existing provider factory supplies configuration-only selection at Run creation.
- Creates a separate Figura database under the configured Figura data root; it does not access ChartAgent storage or migrate ChartAgent sessions.
- Exposes an internal Python application contract for later Agent, Gateway, CLI, and evaluation changes. No user-facing transport or live provider request is added here.
