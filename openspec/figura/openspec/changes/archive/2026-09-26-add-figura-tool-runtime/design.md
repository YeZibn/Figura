## Context

See `proposal.md` for motivation and `specs/tool-runtime/spec.md` for the observable contract.

The Provider boundary already defines `FunctionTool` and normalized `ProviderToolCall` values, validates the supported JSON Schema shape and provider-specific constraints, and rejects unsupported requests before transport. It does not validate returned argument values against a registered handler's schema. `src/figura` has no tool package. The Run store currently accepts only input, model-response, and final-answer facts, and the coordinator rejects model responses containing tool calls or private continuation.

The legacy ChartAgent has a mutable registry and a dispatcher coupled to chart, measurement, evidence, recovery, and trace behavior. Its replay-effect classification is a useful concept; its registry and full tool execution flow are not a Figura implementation contract. The large Figura architecture draft is a candidate reference, not an authoritative specification.

## Goals / Non-Goals

**Goals:**

- Provide provider-neutral, typed tool definitions, an immutable versioned registry, and a single-call executor.
- Keep one definition as the source for model-visible name, description, input schema, private handler, output schema, and replay-effect declaration.
- Validate model arguments and handler results locally with one bounded JSON Schema subset.
- Return bounded results or safe structured errors associated with the original call ID.
- Let later Agent and durable-execution changes consume these contracts without making ToolRuntime own a loop or persistence.

**Non-Goals:**

- Creating actual chart-analysis, attachment, measurement, rendering, or publication tools.
- Calling the Provider, building prompts or history, running a ReAct loop, batching or parallelizing calls.
- Persisting tool invocations/results, checkpoint actions, provider continuation, or tool registry versions on Runs.
- Retrying, resuming, reconciling side effects, emitting Gateway/SSE/UI events, or creating user-facing tool presentation fields.

## Decisions

### 1. Keep tool contracts separate from Provider and Run contracts

Add an application-owned `figura.tools` package with provider-neutral `ToolDefinition`, `ToolRegistry`, `ToolContext`, `ToolInvocation`, `ToolInvocationError`, `ToolExecutionResult`, `ToolExecutionError`, and a `ToolRuntime` single-call entry point. `ToolInvocation` carries `call_id`, `name`, and raw `arguments_json`; ToolRuntime does not accept SDK objects. A narrow adapter maps definitions to `figura.providers.models.FunctionTool` and normalized `ProviderToolCall` values to `ToolInvocation`. Provider adapters remain unaware of handlers and registries.

The handler signature is synchronous and explicit: `handler(context, validated_arguments)`. Arguments are passed as one validated mapping, not expanded into Python keyword arguments. Runtime composition injects handler dependencies when constructing definitions; `ToolContext` is not a general-purpose service locator.

**Alternative considered:** Put ToolRegistry in `figura.providers` or make ProviderClient dispatch handlers. This would mix transport/schema translation with application execution and make the provider layer depend on Figura business handlers.

### 2. Build an immutable, ordered registry once per runtime configuration

`ToolRegistry` receives an explicit nonempty `registry_version` and an ordered sequence of definitions. It rejects duplicate names and keeps that declaration order as the model-facing order. Its name lookup is read-only; schemas are defensively copied on input and projection so callers cannot mutate a registered definition after construction. A registry instance is the exact set of tools available to its ToolRuntime. This change does not add a separate per-Run permission engine; later composition can provide a scoped registry when tools require different authorization.

The definition contains `name`, `description`, `parameters_schema`, `result_schema`, `replay_effect`, and a private `handler`. It does not contain `strict`, `display_name`, `group`, `prompt_guidance`, or budget fields. `strict` is provider/endpoint-specific; presentation, prompt guidance, and Agent budgets have no consumer in this change.

**Alternative considered:** Reuse the mutable legacy registry API. Build-once registration makes the provider schema and invoked handler stable for a registry version and avoids changes during an execution.

### 3. Use one explicit, bounded JSON Schema subset for definitions and values

Add a pure Figura JSON Schema utility that validates schema structure and validates instances against that schema. The first supported subset is the keyword set already accepted by Provider validation: `type`, `properties`, `required`, `additionalProperties`, `items`, `enum`, `description`, `title`, `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `minLength`, `maxLength`, `pattern`, `minItems`, `maxItems`, `uniqueItems`, `anyOf`, and `const`. Unsupported keywords such as `$ref`, `oneOf`, and `allOf` are rejected; no layer silently removes a constraint.

The shared utility owns structural/schema-instance semantics. `figura.providers.validation` retains provider-specific support checks, including the existing endpoint-specific `strict` rules. Tool argument validation and result validation use the shared instance validator. Input and result schemas have top-level type `object`.

Initial hard bounds are constants in ToolRuntime: at most 64 registered tools; 128 KiB canonical JSON per individual schema; 512 KiB canonical JSON total for one registry's schemas and descriptions; 64 KiB UTF-8 per argument JSON string; 256 KiB UTF-8 per serialized result; 2,048 UTF-8 bytes per description; 128 UTF-8 bytes per registry version; 256 UTF-8 bytes per call ID; 512 UTF-8 bytes per safe error message; 16 schema levels; and 256 properties per object. These are initial implementation defaults, not caller-controlled request fields. The argument/result limits may be revised before implementation if a concrete first chart tool requires it.

**Alternative considered:** Add a third-party JSON Schema package. The current Provider accepts a deliberately limited dialect; sharing a small local validator avoids accepting schema features that the Provider cannot faithfully transmit and avoids introducing a dependency for this bounded contract.

### 4. Validate before handler execution and return a typed result

The `ToolInvocation` adapter/model rejects malformed or overlong call IDs and invalid tool-name syntax with a bounded `ToolInvocationError`; these malformed envelopes cannot create a correlated tool result. `ToolRuntime.invoke()` checks the matching context call ID, resolves the name, bounds and parses the JSON, rejects duplicate object keys and non-finite numeric constants, requires an object, and validates it against `parameters_schema` before calling the handler once. Unknown but syntactically valid names and invalid arguments return a failed `ToolExecutionResult` tied to the call ID without invoking a handler. Provider batches are not accepted here; a future AgentExecutor iterates normalized calls serially in provider order.

A successful handler returns a JSON object validated against `result_schema`. The result envelope is exclusive: `outcome=succeeded` carries `result` and no `error`; `outcome=failed` carries `error` and no `result`. The error carries a controlled `code` matching `[a-z][a-z0-9_.-]{0,63}`, a safe `message` no longer than 512 UTF-8 bytes, a `retryable` boolean, and an optional JSON Pointer field path no longer than 256 UTF-8 bytes. Validation failures may be marked retryable for a later Agent decision; unknown tool, unexpected handler failure, invalid handler output, and cancellation are not automatically retried. Handler code can raise a typed `ToolFailure` with the same bounded fields to report a known safe failure. Unexpected exceptions map to a fixed `handler_failed` message; exception text and stack are omitted from the result and ordinary logs.

Serialized results use deterministic JSON encoding with non-finite numbers rejected. ToolRuntime returns structured data; the future Agent layer converts it to the Provider `tool` message using the same `call_id`. Image bytes and artifact manifests are not generic ToolExecutionResult fields; later tools can return authorized opaque references through their declared result schema.

**Alternative considered:** Return arbitrary handler objects or JSON strings. Requiring an object that conforms to a declared schema catches handler contract drift and gives later persistence a bounded typed value rather than an unrestricted Python object.

### 5. Declare replay effects but leave replay ownership above ToolRuntime

Each definition declares exactly one `replay_effect`: `replay_safe`, `idempotent_local_write`, or `reconcile_required`. The registry version binds this declaration to the handler/schema set. ToolRuntime invokes only the requested call once and does not decide whether to repeat an invocation. The later durable-execution owner records call/result facts, provider unknown outcomes, and recovery state before any automatic retry policy is considered.

**Alternative considered:** Let the executor retry transient exceptions. A local exception cannot prove that a remote or local side effect did not occur, and the present Runtime has no persisted intent/result boundary.

### 6. Do not change persistent Run schema in this change

Tool definitions and results are in-process contracts only. No SQLite table, `RecordKind`, `ActionKind`, Run payload, checkpoint, event, or ProviderContinuation field changes here. A later durable tool-execution change will add the required append-only facts and schema migration together with unknown-outcome and continuation rules. This keeps the current Run fail-closed behavior intact until it can represent tool work.

**Alternative considered:** Add tool-result persistence as part of ToolRuntime. That would combine dispatch mechanics with recovery semantics and require the Agent/Run owner to decide atomic commit, call ordering, schema migration, and crash reconciliation at the same time.

## Risks / Trade-offs

- **[Risk] Shared schema utilities can drift from what providers support.** → Provider-specific request validation remains authoritative and rejects unsupported schemas before transport; contract tests cover shared and endpoint-specific cases.
- **[Risk] A handler may block after invocation.** → The first version is synchronous and supports cooperative cancellation checks before/during handler work; it does not promise forcible interruption of an arbitrary Python function. Supervision/timeouts belong to a later execution runner.
- **[Risk] A bounded result can still contain sensitive domain data.** → Tool definitions validate shape and size, while each handler owns domain redaction; raw arguments, results, and exception details are excluded from ordinary diagnostics.
- **[Risk] `replay_effect` could be mistaken for an implemented retry guarantee.** → ToolRuntime treats it as metadata only; specs and APIs explicitly leave replay/reconciliation to a later durable execution owner.
- **[Risk] The initial byte caps may constrain a future chart tool.** → Limits are centralized constants and can be adjusted before adding such a tool; image bytes and large artifacts use later artifact/reference contracts, not this generic result envelope.

## Migration Plan

No persistent data migration is required. Existing `model-provider` request/response contracts and Run SQLite schema remain unchanged. Add the new package and shared schema utility without enabling tool calls in `RunCoordinator`; the current unsupported-payload rejection remains until a later durable-execution change expands the stored fact/checkpoint contract.
