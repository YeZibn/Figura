## Why

Figura's Provider layer can transmit function schemas and normalize model tool calls, but `src/figura` has no application-owned tool definitions, registry, local argument validation, handler dispatch, or bounded result contract. A small provider-neutral ToolRuntime gives the later Agent loop one controlled way to expose and execute tools without importing ChartAgent's chart-specific lifecycle.

## What Changes

- Add immutable, versioned tool definitions and a registry that owns the exact set of tools available to an execution context.
- Validate registered input and result schemas at construction, project model-facing input schemas to the existing Provider function-tool contract, and reject schemas that cannot be represented faithfully by the selected provider.
- Add single-call dispatch that parses and validates model arguments before invoking a handler, associates the result with the original `call_id`, and leaves serial provider-batch ordering to the caller.
- Normalize handler success and failure into bounded structured results. Do not expose raw exception details, perform retries, or let ToolRuntime invoke a Provider.
- Declare each tool's replay effect so later durable execution can make explicit retry and recovery decisions.

## Capabilities

### New Capabilities
- `tool-runtime`: Provider-neutral tool definition, registration, schema projection, validated single-call dispatch, and bounded result/error contracts.

### Modified Capabilities
<!-- No existing capability requirements change in this proposal. Provider schema transport and Run persistence retain their existing contracts. -->

## Impact

- Adds an application-owned tool package under `src/figura/tools/` and tests for registry construction, schema projection, dispatch validation, and result normalization.
- Integrates with the existing `figura.providers.models.FunctionTool` contract without changing Provider request/response or SQLite Run schemas.
- Does not add concrete chart tools, Agent/ReAct orchestration, durable tool-call/result records, Provider continuation persistence, attachments, Gateway/UI, automatic retry, or parallel dispatch. Those remain later changes.
