# tool-runtime Specification

## Purpose

Provides Figura with a provider-neutral contract for defining, registering, validating, and invoking model-selectable tools. It keeps model-visible schemas aligned with the handlers that execute them and returns bounded, call-associated observations for later Agent orchestration.

## Requirements

### Requirement: Tool definitions are immutable, versioned, and executable only through their registry
Figura SHALL expose a versioned registry containing immutable tool definitions. Each definition SHALL declare a unique stable name, a model-facing description protected as part of the complete Registry projection, an object input schema, an object result schema, a replay-effect classification, and a private handler. Registry construction SHALL reject duplicate names, malformed schemas, unsupported schema keywords, and invalid replay-effect values. The registry SHALL expose only the tools it owns, in deterministic order, to callers that build Provider requests.

Registry projection SHALL use the shared execution-payload contract and SHALL NOT impose independent generic tool count, Schema byte, description byte, property count or enum count limits. Registered domain Schema constraints SHALL remain intact. Names SHALL remain nonempty, unique and syntactically valid; genuine Provider name restrictions belong to the selected Provider boundary.

#### Scenario: Build a registry with valid definitions
- **WHEN** the runtime is composed with unique definitions whose schemas and replay effects satisfy the supported contract
- **THEN** it produces an immutable registry with a stable registry version and deterministic tool ordering

#### Scenario: Reject duplicate or invalid definitions
- **WHEN** registry construction receives duplicate names, malformed schemas, unsupported schema keywords, or an unknown replay-effect value
- **THEN** construction fails before any handler can be invoked

#### Scenario: Expose a registered tool to a model request
- **WHEN** a caller projects the registry's definitions into Provider function tools
- **THEN** each projected function preserves its registered name, description, and input constraints, and no handler implementation or private runtime data is included

#### Scenario: Build a larger valid registry
- **WHEN** more than 64 valid definitions fit the complete Registry guard
- **THEN** Figura retains every definition in deterministic order instead of rejecting or clipping the Registry by generic count

### Requirement: Tool invocations are parsed and validated before execution
Figura SHALL accept one normalized tool invocation at a time, preserving its opaque call ID, name, and raw JSON arguments. Before invoking a handler, the runtime SHALL verify that the name is registered, parse the arguments as a JSON object, reject duplicate object keys and non-finite numeric constants, and validate them against that definition's input schema. Unknown names, invalid JSON, non-object arguments, or schema violations SHALL produce a bounded failed result associated with the original call ID and SHALL NOT invoke a handler. ToolRuntime SHALL NOT reorder, parallelize, or automatically retry calls.

Argument admission SHALL use the shared execution-payload contract without a separate 64 KiB limit. Opaque call IDs SHALL be preserved in full and SHALL NOT have an independent arbitrary length cap.

#### Scenario: Execute a valid invocation
- **WHEN** an invocation names a registered tool and its bounded JSON object arguments satisfy the registered input schema
- **THEN** the runtime invokes that tool's handler once with validated arguments and the call-scoped context

#### Scenario: Reject invalid arguments without running the handler
- **WHEN** the arguments are invalid JSON, are not a JSON object, exceed the shared complete-payload guard, or violate the registered input schema
- **THEN** the runtime returns a bounded validation failure for the same call ID and does not invoke the handler

#### Scenario: Reject an unknown tool name
- **WHEN** an invocation names a tool that is absent from the registry
- **THEN** the runtime returns a bounded unknown-tool failure for the same call ID and invokes no handler

#### Scenario: Reject a malformed invocation identity
- **WHEN** an invocation has a missing, empty or invalid UTF-8 call ID, invalid name syntax, or a context call ID that does not match
- **THEN** the runtime rejects the invocation before handler execution with a bounded invocation error and does not construct a mismatched result envelope

### Requirement: Tool results are bounded and errors do not disclose implementation details
Figura SHALL validate handler success values against the registered result schema and require them to be JSON-serializable within the shared complete-observation payload guard. A successful result SHALL retain the original call ID and tool name. Known handler errors, invalid results with resolved effects, and unexpected handler exceptions whose effects are known SHALL be represented by a mutually exclusive structured error result with a controlled code, bounded safe message, and retryability flag. Unexpected exceptions SHALL NOT disclose exception text, stack traces, credentials, local paths, or raw provider payloads. ToolRuntime SHALL NOT retry a failed handler.

There SHALL be no separate 256 KiB successful-result limit. Safe error messages and field pointers SHALL retain their existing bounded display contract. The retryability flag SHALL be informational and SHALL NOT authorize automatic reinvocation. If a durable write-capable invocation's effects cannot be determined, Figura SHALL preserve an unknown attempt for its recovery owner rather than commit a failure observation that falsely implies the effects were resolved.

#### Scenario: Return a valid handler result
- **WHEN** a registered handler returns a value matching its result schema and within the shared payload guard
- **THEN** the runtime returns a successful structured result associated with the invocation's call ID and tool name

#### Scenario: Reject an invalid or oversized handler result
- **WHEN** a handler with known resolved effects returns a value that violates its result schema, cannot be safely serialized, or exceeds the shared complete-observation guard
- **THEN** the runtime returns a bounded result-validation failure without exposing the invalid payload

#### Scenario: Contain an unexpected handler exception
- **WHEN** a replay-safe handler or a handler with proven resolved effects raises an exception not represented by its declared tool error contract
- **THEN** the runtime returns a generic bounded handler-failure result and excludes raw exception details from the result and ordinary diagnostics

#### Scenario: Keep retryable failure as an observation
- **WHEN** a tool returns a known failed result with retryable set true
- **THEN** Figura returns that result once and does not automatically invoke the handler with the same arguments

#### Scenario: Preserve an uncertain partial write
- **WHEN** a write-capable tool may have applied effects and cannot establish a genuine success or known failure
- **THEN** durable coordination retains an unknown outcome instead of publishing a fabricated resolved observation

### Requirement: Every tool declares replay behavior without implicit replay
Every registered definition SHALL declare exactly one replay effect: `replay_safe`, `idempotent_local_write`, or `reconcile_required`. The classification SHALL be available to later execution coordination. ToolRuntime SHALL execute only the requested invocation and SHALL NOT infer that a failed, cancelled, or uncertain invocation is safe to replay from its error code alone.

#### Scenario: Preserve the declared replay effect
- **WHEN** a valid definition is registered and later resolved for invocation
- **THEN** its declared replay effect remains associated with the same registry version and tool definition

#### Scenario: A failed invocation is not automatically repeated
- **WHEN** an invocation returns a failed result or its handler raises unexpectedly
- **THEN** ToolRuntime returns the result once and leaves any retry or reconciliation decision to a higher execution owner
