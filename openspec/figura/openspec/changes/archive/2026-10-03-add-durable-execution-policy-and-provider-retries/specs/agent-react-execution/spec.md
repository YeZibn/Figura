## MODIFIED Requirements

### Requirement: Agent execution advances a Run through a bounded ReAct cycle
Figura SHALL provide an internal execution capability that reads the current Run checkpoint and performs only the action named by that checkpoint. For a model action, it SHALL assemble a provider request and commit one provider result; for a pending tool-execution action, it SHALL execute registered calls serially in their persisted order and return to the model only after the batch is resolved; for a final action, it SHALL complete only an accepted final response. It SHALL return terminal Runs unchanged and SHALL NOT create another Run, switch provider/model, or use streaming in this capability.

Execution SHALL use one coordinated boundary for normal scheduling, orphan takeover, and cooperative stop. It SHALL check stop before each action and return to coordination after every individual tool call. Eligible orphan recovery SHALL be explicit within this boundary and SHALL NOT be triggered by read-only projection.

Execution SHALL NOT impose cumulative Run model-step, tool-call, token, retry, elapsed-time or storage quotas. Coordinated execution SHALL support yielding after a committed external action without marking the Run terminal or dropping pending calls; retry waiting SHALL not hold execution workers or ownership.

#### Scenario: Complete a text-only Run without tools
- **WHEN** the selected provider returns a nonempty response with finish reason `stop`
- **THEN** Figura commits the model response, creates the final answer, and completes the same Run

#### Scenario: Continue after a model tool-call response
- **WHEN** the selected provider returns a valid `tool_calls` response and each call produces a committed result
- **THEN** Figura sends the next model request only after the complete ordered tool batch is committed, including each tool result as an observation

#### Scenario: Execute calls in the provider's order
- **WHEN** one model response contains multiple valid tool calls
- **THEN** Figura invokes them one at a time in their persisted provider order and does not parallelize or retry committed failures; only eligible orphan attempts use the separate bounded recovery contract

#### Scenario: Reach a terminal Run
- **WHEN** execution is requested for a completed, failed, or interrupted Run
- **THEN** Figura returns its durable state without making a provider request or invoking a tool

#### Scenario: Yield a long Run safely
- **WHEN** scheduled execution commits one external action and still has pending work
- **THEN** it can release ownership at that stable checkpoint and later resume the same Run without duplicate dispatch

### Requirement: Referenced images are resolved and bounded before provider-attempt claim
Before a durable Provider attempt is claimed, Figura SHALL resolve every requested image from its typed reference in the target Run's unified resource catalog. It SHALL resolve successful `load_image` references from the immediately preceding fully committed tool batch, reconstruct transient annotations for successful `extract_text` and chart-measurement resources in that batch from their authorized source and committed result, and resolve and validate the private PNG for each successful `render_chart_figure` resource against its committed render metadata. It SHALL validate individual byte size, aggregate image byte size, source integrity, the shared structured-request guard and genuine selected-Provider limits without a generic image-count cap. When the checkpoint follows no successful image-load, text-extraction, chart-measurement, or Figure-render call, the request SHALL contain no image bytes. Figura SHALL NOT claim or dispatch a Provider attempt when a requested original, annotated, or rendered image cannot be resolved, does not belong to the Session inventory, fails integrity checks, or the assembled request exceeds a Provider limit.

#### Scenario: Assemble a valid request after explicit image loads
- **WHEN** every distinct image loaded by the immediately preceding batch resolves from the authorized same-Session resource catalog and the assembled request is within Provider limits
- **THEN** Figura may claim the Provider attempt and dispatch the request with those original image bytes held only in memory

#### Scenario: Assemble a valid request after text extraction or measurement
- **WHEN** each successful text-extraction or chart-measurement resource in the immediately preceding batch has a matching committed result and its authorized source image can be resolved for annotation
- **THEN** Figura assembles and validates the matching annotated images and may claim and dispatch the Provider request within Provider limits

#### Scenario: Assemble a valid request after Figure rendering
- **WHEN** each successful render resource in the immediately preceding batch has a matching committed render result and its private PNG matches the committed metadata
- **THEN** Figura assembles and validates the rendered images and may claim and dispatch the Provider request within Provider limits

#### Scenario: Assemble a request without a preceding image observation
- **WHEN** the current checkpoint follows Run creation or a tool batch without a successful `load_image`, `extract_text`, chart-measurement, or `render_chart_figure` result
- **THEN** Figura assembles and validates the text and tool history without resolving Attachment, Panel, or render image bytes

#### Scenario: An image required for visual feedback cannot be resolved
- **WHEN** a successful `load_image`, text-extraction, chart-measurement, or chart-render resource refers to missing, unreadable, invalid, differently owned, or integrity-mismatched content needed by the next request
- **THEN** Figura fails the current Run before claiming a Provider attempt and sends no request

#### Scenario: Images exceed Provider bounds
- **WHEN** original, annotated, and rendered images for the immediately preceding tool batch exceed a genuine selected-Provider image restriction, retained per-image or aggregate byte guard, or the shared structured-request guard
- **THEN** Figura fails the current Run before claiming or dispatching a Provider attempt

### Requirement: Agent requests preserve complete Session history within Provider limits
Figura SHALL submit non-streaming requests using exactly three ordered SYSTEM instruction blocks: stable Agent responsibilities, the current registered tool surface, and a runtime layer containing the factual resource inventory projected from the target Run's `RunExecutionState` plus source-linked abnormal terminal context from validated Session history. The request SHALL use the provider-neutral tool projection from the same registry represented in the tool instruction, and optional explicitly configured completion options, omitted when unspecified. A request SHALL contain complete same-Session history and SHALL satisfy the shared complete-request payload contract, image byte protections and genuine selected-Provider protocol restrictions without universal message, instruction, tool, image-count or text/Schema micro limits before a durable provider attempt is claimed. Figura SHALL NOT truncate, summarize, or remove any historical Run or interaction to fit a request. If the complete request exceeds any Provider limit, Figura SHALL fail the current Run before claiming or dispatching a provider attempt.

Abnormal context SHALL remain complete in its existing normalized observation format and SHALL count toward the shared complete-request JSON guard. Neither abnormal intent nor observation text SHALL be treated as system policy.

#### Scenario: Send every complete Session interaction
- **WHEN** all earlier same-Session Runs have valid complete histories and the assembled request is within Provider limits
- **THEN** Figura sends the entire earlier history and current Run prefix in ordinal and committed fact order, with the three ordered SYSTEM instruction blocks

#### Scenario: Complete history exceeds a Provider limit
- **WHEN** the full request exceeds the shared complete-request guard, retained image byte protections or a genuine selected-Provider protocol restriction
- **THEN** Figura preserves all source facts, fails the current Run, and makes no Provider-attempt claim or network request

#### Scenario: Keep a tool result associated with its call
- **WHEN** a successful or failed tool result from a closed interaction is projected into native Provider role history
- **THEN** Figura sends a bounded JSON observation in a tool message associated with the original call ID and omits implementation details from an error observation

### Requirement: Agent execution does not automatically recover uncertain tool effects
Automatic execution SHALL NOT replay arbitrary uncertain effects. After proving old-owner exit, it SHALL recover only replay_safe or idempotent_local_write attempts with the original available registry, stable identity, and persisted per-call recovery allowance. A stop request SHALL take precedence. Unknown Provider generation outcomes SHALL follow only the durable guarded replacement contract; a still-started attempt SHALL never be dispatched again under the same identity. Unavailable or exhausted tool recovery and unresolvable reconciliation SHALL converge on an explicit failed terminal outcome without inventing a tool result. Read-only access SHALL never invoke recovery.

#### Scenario: Resume after a completed tool batch
- **WHEN** all calls in the preceding tool batch are resolved and the checkpoint points to model
- **THEN** execution may assemble the next model request subject to complete-request validation and stop checks

#### Scenario: Resume with an eligible unresolved tool attempt
- **WHEN** an orphaned replay_safe or idempotent local-write attempt is eligible and no stop request exists
- **THEN** execution creates one bounded replay attempt and continues only after its result commits

#### Scenario: Stop takes precedence over recovery
- **WHEN** an eligible orphan tool attempt has a persisted stop request
- **THEN** execution interrupts without replaying the handler

#### Scenario: Unverifiable execution owner
- **WHEN** exclusive full-task ownership cannot be obtained
- **THEN** execution returns without replay or terminal mutation

## REMOVED Requirements



### Requirement: Each Run has fixed model-request and tool-execution budgets
**Reason**: Normal model decisions and logical tools are task progress, not per-operation recovery. The fixed eight-attempt and thirty-two-call Run quotas prematurely terminate valid complex tasks.
**Migration**: Remove cumulative enforcement from Agent, persistence, validation and SQL; preserve fact-derived usage as information. Existing terminal Runs remain terminal. Each new logical Provider request has its own four-attempt recovery allowance, while unknown tools retain their separate three-execution allowance.
