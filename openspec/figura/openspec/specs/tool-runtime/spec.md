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
Figura SHALL accept one success-output contract containing a business JSON object and an ordered image-output collection from every registered handler. A plain dictionary or an old/new union return SHALL be rejected. Figura SHALL validate the business object against the unchanged registered result schema, the complete observation against the shared payload guard, and every image against the common media contract before returning a successful result. The normalized result SHALL retain the original call ID and tool name, mutually exclusive result/error, and an attachments array; the array SHALL be empty for nonvisual successes and failures. Attachment descriptions SHALL contain no raw bytes, filesystem paths, URLs, or Provider messages. Each newly executed successful load_image, extract_text, measure_chart, render_chart_figure, or read_resource_image call SHALL have the promised validated image attachment.

Known handler errors, invalid results with resolved effects, and unexpected handler exceptions whose effects are known SHALL produce a controlled error code, bounded safe message, retryability flag and optional field pointer. Images that cannot be prepared or installed with known resolved effects SHALL produce a safe tool failure rather than a successful result with a silently omitted image. Exceptions SHALL NOT disclose exception text, stack traces, credentials, local paths, or raw Provider payloads. ToolRuntime SHALL NOT retry a failed handler.

There SHALL be no separate 256 KiB successful-result limit. The complete result and attachment descriptions SHALL satisfy the shared execution-payload contract, while raw media retains its independent existing image protections. Retryability SHALL remain informational. If a durable write-capable invocation's effects cannot be determined, Figura SHALL preserve an unknown attempt rather than publish a failure that falsely claims resolved effects.

#### Scenario: Return a valid handler result
- **WHEN** a registered handler returns the single success-output contract with business data matching its result schema and media satisfying the shared guards
- **THEN** the runtime returns one successful structured result and ordered attachment descriptions associated with the invocation's call ID and tool name

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

#### Scenario: Reject the previous dictionary-only handler output
- **WHEN** a handler returns a bare JSON dictionary after the contract cutover
- **THEN** Figura reports invalid_result, applies unknown-effect handling when required, and does not adapt the dictionary into the new success-output contract

#### Scenario: Fail a promised image before publishing tool success
- **WHEN** a newly executed visual tool has valid business data but its required image cannot be prepared with effects known
- **THEN** the call returns a bounded tool failure with an empty attachment array instead of publishing an incomplete success
### Requirement: Every tool declares replay behavior without implicit replay
Every registered definition SHALL declare exactly one replay effect: `replay_safe`, `idempotent_local_write`, or `reconcile_required`. The classification SHALL be available to later execution coordination. ToolRuntime SHALL execute only the requested invocation and SHALL NOT infer that a failed, cancelled, or uncertain invocation is safe to replay from its error code alone.

#### Scenario: Preserve the declared replay effect
- **WHEN** a valid definition is registered and later resolved for invocation
- **THEN** its declared replay effect remains associated with the same registry version and tool definition

#### Scenario: A failed invocation is not automatically repeated
- **WHEN** an invocation returns a failed result or its handler raises unexpectedly
- **THEN** ToolRuntime returns the result once and leaves any retry or reconciliation decision to a higher execution owner

### Requirement: Model-facing tool guidance explains selection and consequential semantics
Each registered model-callable tool SHALL provide a nonempty Chinese description explaining its purpose, accepted source, principal result, and consequential limitation or follow-up. Native parameter Schema SHALL describe fields whose meaning cannot be established from structural constraints alone, including coordinate units and frames, opaque reference provenance, optional defaults, search filters, pagination, selectors, and chart-type data semantics. Tool descriptions and parameter annotations SHALL agree with execution behavior and SHALL NOT invent capabilities, success guarantees, or automatic failure retries. Numeric and structural constraints SHALL remain authoritative in Schema rather than being duplicated as a separate fixed tool manual.

#### Scenario: Understand observation scope before calling a sensor
- **WHEN** a model receives an OCR or chart-measurement definition
- **THEN** the native parameters explain normalized source-relative coordinates, the `[x, y]` point shape, include-union minus exclude-union semantics, whole-source behavior when omitted, and the need for remaining observable pixels

#### Scenario: Distinguish decomposition and scoped observation
- **WHEN** the model chooses between Panel decomposition and an observation scope
- **THEN** tool guidance distinguishes creating an independent polygon-cropped Panel with `{x, y}` points from applying a temporary observation mask that preserves the selected source dimensions and result coordinate frame

#### Scenario: Interpret OCR and measurement results accurately
- **WHEN** the model receives OCR, bar, line, scatter, or pie tool guidance
- **THEN** it can distinguish execution success from observation quality, unavailable OCR from an empty available observation, possible truncation, calibrated chart values from pixel geometry, line markers from tick-position trace samples, visible scatter marks from hidden sample counts, and pie proportions from absolute totals

#### Scenario: Construct chart-type data with supported references
- **WHEN** the model receives Figure assembly parameters
- **THEN** guidance explains category/value points for bar and pie, x/y points for line and scatter, category positions and increasing x for line, actual committed measurement reference provenance, and the returned Figure reference without implying that references verify all supplied values

#### Scenario: Render using the exact returned reference
- **WHEN** a model uses a successful assembly result to request rendering
- **THEN** guidance identifies the nested `figure_ref` parameter, describes PNG feedback in the next request, and distinguishes rendering success from semantic approval

### Requirement: Tool guidance shares the request's registry identity
Figura SHALL derive model-facing tool names, descriptions, and native parameters from the same selected registry. Tool definitions whose input acceptance or observation semantics change SHALL use a new registry version. Completed prior-version calls SHALL remain inert readable history; unresolved prior-version work SHALL retain the existing rejection behavior. Prompt and tool metadata changes SHALL participate in existing request identity checks and SHALL NOT silently replace an already bound request.

#### Scenario: Project annotated native parameters
- **WHEN** a tool parameter Schema contains semantic descriptions
- **THEN** the Provider tool projection retains those descriptions and uses the same name and tool description as the request's tool directory

#### Scenario: Resume a request after assets change
- **WHEN** reconstructed prompt or registry metadata differs from an already bound request identity
- **THEN** Figura follows the existing identity mismatch behavior instead of dispatching a different request under the old binding
