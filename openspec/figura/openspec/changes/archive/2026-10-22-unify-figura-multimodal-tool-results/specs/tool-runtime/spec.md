## MODIFIED Requirements

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
