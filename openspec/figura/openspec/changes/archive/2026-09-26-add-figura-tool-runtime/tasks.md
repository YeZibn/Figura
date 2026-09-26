## 1. Shared bounded JSON Schema contract

- [x] 1.1 Add a pure Figura schema utility for the supported schema subset, definition validation, instance validation, deterministic JSON serialization, and depth/property limits.
- [x] 1.2 Route Provider function-schema structural checks through the shared utility while retaining provider- and endpoint-specific capability checks and existing rejection behavior.
- [x] 1.3 Add focused coverage for supported keywords, invalid instances, unsupported keywords, depth/property limits, non-finite values, and provider-specific strict-schema behavior.

## 2. Tool definitions and immutable registry

- [x] 2.1 Add typed tool contracts for `ToolDefinition`, `ToolContext`, `ToolInvocation`, bounded `ToolInvocationError`, `ToolExecutionResult`, `ToolExecutionError`, declared handler failure, and replay-effect values.
- [x] 2.2 Validate definition names, bounded descriptions, object input/result schemas, handler shape, and required replay-effect classification during registry construction.
- [x] 2.3 Add a versioned immutable `ToolRegistry` that rejects duplicate names, preserves declared order, provides read-only lookup, and prevents schema mutation through defensive copies.
- [x] 2.4 Add a narrow Provider projection/normalization adapter that maps registered metadata to `FunctionTool` and `ProviderToolCall` to `ToolInvocation` without exposing handlers or runtime context.
- [x] 2.5 Add registry and projection coverage for ordering, uniqueness, immutability, exact schema preservation, and hidden handler data.

## 3. Single-call ToolRuntime

- [x] 3.1 Implement single-call dispatch with call-ID/name checks, argument byte bounds, duplicate-key/non-finite-number rejection, JSON-object parsing, registered-name resolution, and input-schema validation before handler invocation.
- [x] 3.2 Invoke the synchronous handler once with validated arguments and call-scoped context; support cooperative pre-invocation cancellation without adding forced timeout or retry behavior.
- [x] 3.3 Validate successful object output against `result_schema`, serialize deterministically, enforce the result byte limit, and return an exclusive success envelope associated with the original call ID.
- [x] 3.4 Normalize unknown tools, malformed/schema-invalid arguments, declared handler failures, cancellation, invalid results, and unexpected exceptions into bounded safe error envelopes without exposing raw exceptions or payloads.
- [x] 3.5 Add fake-handler coverage proving invalid inputs never execute, valid calls execute exactly once, outputs/errors preserve `call_id`, oversized or invalid outputs are rejected, and failures are never automatically retried.

## 4. Integration boundaries and verification

- [x] 4.1 Confirm ToolRuntime has no Provider invocation, batch scheduler, Run persistence, checkpoint/event writes, concrete chart tools, or Agent/ReAct loop.
- [x] 4.2 Run the focused Figura schema/provider/tool-runtime tests and the repository's required broader checks for the affected Python modules; resolve regressions without relaxing provider schema constraints.
- [x] 4.3 Run `openspec validate add-figura-tool-runtime --strict --no-interactive --store figura` and review the final artifact status and diff.
