# tool-runtime Specification

## Purpose

Provides Figura with a provider-neutral contract for defining, registering, validating, and invoking model-selectable tools. It keeps model-visible schemas aligned with the handlers that execute them and returns bounded, call-associated observations for later Agent orchestration.

## Requirements

### Requirement: Tool definitions are immutable, versioned, and executable only through their registry
Figura SHALL expose a versioned registry containing immutable tool definitions. Each definition SHALL declare a unique stable name, a bounded model-facing description, an object input schema, an object result schema, a replay-effect classification, and a private handler. Registry construction SHALL reject duplicate names, malformed schemas, unsupported schema keywords, and invalid replay-effect values. The registry SHALL expose only the tools it owns, in deterministic order, to callers that build Provider requests.

#### Scenario: Build a registry with valid definitions
- **WHEN** the runtime is composed with unique definitions whose schemas and replay effects satisfy the supported contract
- **THEN** it produces an immutable registry with a stable registry version and deterministic tool ordering

#### Scenario: Reject duplicate or invalid definitions
- **WHEN** registry construction receives duplicate names, malformed schemas, unsupported schema keywords, or an unknown replay-effect value
- **THEN** construction fails before any handler can be invoked

#### Scenario: Expose a registered tool to a model request
- **WHEN** a caller projects the registry's definitions into Provider function tools
- **THEN** each projected function preserves its registered name, description, and input constraints, and no handler implementation or private runtime data is included

### Requirement: Tool invocations are parsed and validated before execution
Figura SHALL accept one normalized tool invocation at a time, preserving its opaque call ID, name, and raw JSON arguments. Before invoking a handler, the runtime SHALL verify that the name is registered, parse the arguments as a JSON object, reject duplicate object keys and non-finite numeric constants, and validate them against that definition's input schema. Unknown names, invalid JSON, non-object arguments, or schema violations SHALL produce a bounded failed result associated with the original call ID and SHALL NOT invoke a handler. ToolRuntime SHALL NOT reorder, parallelize, or automatically retry calls.

#### Scenario: Execute a valid invocation
- **WHEN** an invocation names a registered tool and its bounded JSON object arguments satisfy the registered input schema
- **THEN** the runtime invokes that tool's handler once with validated arguments and the call-scoped context

#### Scenario: Reject invalid arguments without running the handler
- **WHEN** the arguments are invalid JSON, are not a JSON object, exceed the runtime limit, or violate the registered input schema
- **THEN** the runtime returns a bounded validation failure for the same call ID and does not invoke the handler

#### Scenario: Reject an unknown tool name
- **WHEN** an invocation names a tool that is absent from the registry
- **THEN** the runtime returns a bounded unknown-tool failure for the same call ID and invokes no handler

#### Scenario: Reject a malformed invocation identity
- **WHEN** an invocation has a missing or overlong call ID, invalid name syntax, or a context call ID that does not match
- **THEN** the runtime rejects the invocation before handler execution with a bounded invocation error and does not construct a mismatched result envelope

### Requirement: Tool results are bounded and errors do not disclose implementation details
Figura SHALL validate handler success values against the registered result schema and require them to be JSON-serializable within the result-size limit. A successful result SHALL retain the original call ID and tool name. Handler-declared errors, invalid results, and unexpected handler exceptions SHALL be represented by a mutually exclusive structured error result with a controlled code, bounded safe message, and retryability flag. Unexpected exceptions SHALL NOT disclose exception text, stack traces, credentials, local paths, or raw provider payloads. ToolRuntime SHALL NOT retry a failed handler.

#### Scenario: Return a valid handler result
- **WHEN** a registered handler returns a value matching its result schema and within the output limit
- **THEN** the runtime returns a successful structured result associated with the invocation's call ID and tool name

#### Scenario: Reject an invalid or oversized handler result
- **WHEN** a handler returns a value that violates its result schema, cannot be safely serialized, or exceeds the output limit
- **THEN** the runtime returns a bounded result-validation failure without exposing the invalid payload

#### Scenario: Contain an unexpected handler exception
- **WHEN** a handler raises an exception not represented by its declared tool error contract
- **THEN** the runtime returns a generic bounded handler-failure result and excludes raw exception details from the result and ordinary diagnostics

### Requirement: Every tool declares replay behavior without implicit replay
Every registered definition SHALL declare exactly one replay effect: `replay_safe`, `idempotent_local_write`, or `reconcile_required`. The classification SHALL be available to later execution coordination. ToolRuntime SHALL execute only the requested invocation and SHALL NOT infer that a failed, cancelled, or uncertain invocation is safe to replay from its error code alone.

#### Scenario: Preserve the declared replay effect
- **WHEN** a valid definition is registered and later resolved for invocation
- **THEN** its declared replay effect remains associated with the same registry version and tool definition

#### Scenario: A failed invocation is not automatically repeated
- **WHEN** an invocation returns a failed result or its handler raises unexpectedly
- **THEN** ToolRuntime returns the result once and leaves any retry or reconciliation decision to a higher execution owner
