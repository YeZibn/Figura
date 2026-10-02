## MODIFIED Requirements

### Requirement: Agent execution advances a Run through a bounded ReAct cycle
Figura SHALL provide an internal execution capability that reads the current Run checkpoint and performs only the action named by that checkpoint. For a model action, it SHALL assemble a provider request and commit one provider result; for a pending tool-execution action, it SHALL execute registered calls serially in their persisted order and return to the model only after the batch is resolved; for a final action, it SHALL complete only an accepted final response. It SHALL return terminal Runs unchanged and SHALL NOT create another Run, switch provider/model, or use streaming in this capability.

Execution SHALL use one coordinated boundary for normal scheduling, orphan takeover, and cooperative stop. It SHALL check stop before each action and return to coordination after every individual tool call. Eligible orphan recovery SHALL be explicit within this boundary and SHALL NOT be triggered by read-only projection.

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

### Requirement: Provider history is reconstructed from complete committed interactions
For each model action, Figura SHALL build the conversation from all earlier terminal Runs in the same Session, ordered by Run ordinal, followed by the current Run's immutable input, committed model responses, and committed tool results. Each Run input SHALL appear once as a user message containing its persisted text and ordered attachment references as text identities; it SHALL NOT automatically include image blocks. The request SHALL include the target Run's factual resource index as the third of its three ordered SYSTEM instruction blocks. The index SHALL identify every available Attachment and committed Panel, each committed OCR and measurement resource with its source and outcome, each accepted ChartFigure with its title and chart summary, and each committed render with its Figure reference and outcome. The index SHALL identify resources by their complete typed references. It SHALL NOT duplicate complete OCR, measurement, Figure, or render result payloads already present in committed tool messages. Historical render entries SHALL remain textual; Figura SHALL NOT automatically resend image bytes from an earlier Run or earlier tool batch. Each closed model/tool interaction SHALL be represented by one assistant message whose calls preserve provider order, followed by one tool message for every corresponding result with the matching opaque call ID. A validated incomplete trailing batch from an earlier failed or interrupted Run SHALL be represented entirely by source-linked abnormal outcome data in the third SYSTEM instruction block, preserving its intent and committed observations instead of sending dangling native calls. A final-answer fact that references a response SHALL NOT add a duplicate message. Only original image blocks explicitly loaded by successful `load_image` calls in the immediately preceding fully committed tool batch may be appended as original images, in tool-call order. A fully committed batch containing successful `extract_text`, Cartesian measurement, or pie measurement calls SHALL additionally contribute one reconstructed annotated image per successful call, paired with its JSON tool observation and identified by tool name and call ID. A fully committed batch containing successful `render_chart_figure` calls SHALL additionally contribute each corresponding stored PNG once, paired with its committed JSON tool observation and identified by tool name and call ID, in tool-call order. The resource index and image selection SHALL use the same authorized Run prefix as the committed conversation. Completed tool-call/result pairs recorded under an earlier registry version SHALL be projected as inert conversation history and SHALL NOT be executed again; unresolved work in the current Run, incomplete completed history, or corrupt facts SHALL fail closed; legal terminal incomplete tails SHALL follow the abnormal outcome projection. Provider-private continuation SHALL be attached only to the exact originating assistant response retained in role history, including a prior Run when the selected Provider and format are compatible. Continuation from a converted incomplete batch SHALL NOT be placed in outcome context or fabricated for it. Figura SHALL NOT send a partial tool batch, invent a missing result, include an unresolved tool attempt as a result, or expose continuation data in public projections or ordinary diagnostics.

#### Scenario: Build the first model request with multiple attachments
- **WHEN** the checkpoint points to the initial model action and the current Run references multiple images
- **THEN** the request contains the three ordered SYSTEM instruction blocks, persisted user text, and a complete typed resource index in the third block, but no image bytes

#### Scenario: Include earlier Session Runs and their resources
- **WHEN** the checkpoint points to a model action and the Session has earlier terminal Runs with referenced attachments and committed tool resources
- **THEN** the request contains all earlier closed Run messages and source-linked abnormal contexts in ascending Run ordinal, preserves their text and attachment IDs, indexes each eligible resource once by its typed reference, and does not attach historical image bytes

#### Scenario: Keep full results in chronological tool history
- **WHEN** a committed OCR, measurement, Figure assembly, or render interaction is included in Session history
- **THEN** its complete committed tool result appears in its original tool message and the textual resource index contains only a concise reference and summary, without a duplicate full result payload

#### Scenario: Rebuild a completed tool round with explicitly loaded images
- **WHEN** the checkpoint points to a model action after a fully resolved tool batch containing one or more successful `load_image` calls
- **THEN** the request contains the ordered assistant/tool interaction and appends each loaded original image once as a user image observation in persisted tool-call order

#### Scenario: Include visual feedback for the latest observation batch
- **WHEN** the immediately preceding fully committed tool batch contains successful `extract_text`, Cartesian measurement, or pie measurement calls
- **THEN** the request contains each corresponding JSON tool result and one matching transient annotated image per successful call in tool-call order, with the tool name and call ID identified

#### Scenario: Include a rendered Figure in the next model action
- **WHEN** the immediately preceding fully committed tool batch contains one or more successful `render_chart_figure` calls
- **THEN** the next Provider request contains each corresponding JSON tool result and one matching stored PNG per successful render call in tool-call order, with the tool name and call ID identified

#### Scenario: Do not repeat images from an older tool batch
- **WHEN** the latest completed tool batch contains neither a successful `load_image`, `render_chart_figure`, `extract_text`, nor chart-measurement call
- **THEN** the request contains no image bytes from earlier batches or Runs

#### Scenario: Preserve completed prior-version calls as inert history
- **WHEN** an earlier Run or a completed interaction in the current Run contains a fully paired assistant tool call and result recorded under a prior registry version
- **THEN** Figura projects that interaction in its original order as conversation history and does not invoke its handler

#### Scenario: Fail closed on a prior-version unresolved tool call
- **WHEN** a tool call from a prior registry version is unresolved in the current Run, or belongs to an incomplete completed historical Run
- **THEN** Figura does not construct or dispatch a Provider request and does not execute the old call under the current registry

#### Scenario: Replay only compatible source continuation
- **WHEN** an earlier Run has a compatible private continuation for an assistant response retained in role history
- **THEN** Figura attaches that unchanged continuation to its exact source response while keeping it out of neutral Memory and abnormal outcome data

#### Scenario: Include abnormal tail observations without duplicate payloads
- **WHEN** an earlier interrupted Run has a partly completed tool batch
- **THEN** the third instruction block contains its source-linked outcome context, role history contains only its closed interactions, and the resource index contains only eligible references and summaries

### Requirement: Agent requests preserve complete Session history within Provider limits
Figura SHALL submit non-streaming requests using exactly three ordered SYSTEM instruction blocks: stable Agent responsibilities, the current registered tool surface, and a runtime layer containing the factual resource inventory projected from the target Run's `RunExecutionState` plus source-linked abnormal terminal context from validated Session history. The request SHALL use the provider-neutral tool projection from the same registry represented in the tool instruction, and bounded completion options. A request SHALL contain complete same-Session history and SHALL satisfy the Provider boundary's message, instruction, tool, image, and total text/schema limits before a durable provider attempt is claimed. Figura SHALL NOT truncate, summarize, or remove any historical Run or interaction to fit a request. If the complete request exceeds any Provider limit, Figura SHALL fail the current Run before claiming or dispatching a provider attempt.

Abnormal context SHALL remain complete in its existing normalized observation format and SHALL count toward Provider request hard limits. Neither abnormal intent nor observation text SHALL be treated as system policy.

#### Scenario: Send every complete Session interaction
- **WHEN** all earlier same-Session Runs have valid complete histories and the assembled request is within Provider limits
- **THEN** Figura sends the entire earlier history and current Run prefix in ordinal and committed fact order, with the three ordered SYSTEM instruction blocks

#### Scenario: Complete history exceeds a Provider limit
- **WHEN** the full request exceeds a Provider message, instruction, tool, image, text, or schema limit
- **THEN** Figura preserves all source facts, fails the current Run, and makes no Provider-attempt claim or network request

#### Scenario: Keep a tool result associated with its call
- **WHEN** a successful or failed tool result from a closed interaction is projected into native Provider role history
- **THEN** Figura sends a bounded JSON observation in a tool message associated with the original call ID and omits implementation details from an error observation

### Requirement: Agent prompt layers have explicit sources and ordered responsibilities
Figura SHALL assemble each Agent prompt from three ordered SYSTEM instruction blocks. The stable-responsibility block SHALL contain the fixed Chinese Agent, evidence, workflow, and response rules and SHALL NOT contain request-specific user or Run data. The current-tool block SHALL be projected from the exact tool registry used for the request's provider tool schemas; it SHALL describe only tools present in that registry, while the provider-native schemas remain authoritative for tool names, parameters, required fields, and allowed values. The resource inventory within the third block SHALL be projected exclusively from the target request's `RunExecutionState`, while its separate abnormal outcome section SHALL be projected from validated Session history. The inventory SHALL use complete typed resource references for Attachments, Panels, OCR, measurements, ChartFigures, and ChartRenders.

The resource block SHALL be a concise index and SHALL NOT replace or duplicate complete tool results in chronological Session history. It SHALL distinguish tool execution outcome from a measurement result's `status` and an OCR result's availability. Resource names, titles, OCR text, tool observations, and other data values SHALL be treated as untrusted evidence rather than instructions. The three blocks SHALL be rebuilt for every model request; no prompt or resource summary SHALL be added to durable Run facts.

The third SYSTEM layer SHALL additionally contain deterministic source-linked abnormal terminal context from Session history, sorted by source Run ordinal. The layer SHALL mark response text and observation values as untrusted data, SHALL retain genuine committed observations from converted tails exactly once, and SHALL contain no continuation or fabricated result.

#### Scenario: Keep stable policy independent from user and Run values
- **WHEN** Figura assembles a request containing user text, tool results, attachments, and Panels
- **THEN** the first SYSTEM instruction block contains only the stable Chinese Agent policy and the request-specific values appear only in their designated dynamic layers or history messages

#### Scenario: Match the tool layer to the registered tool schemas
- **WHEN** a request is assembled with a tool registry containing a specific ordered set of tools
- **THEN** the second SYSTEM instruction block describes exactly those tools in registry order and the provider request exposes their native schemas from the same registry

#### Scenario: Index all resource kinds from the target Run state
- **WHEN** the target Run's `RunExecutionState` contains eligible resources of multiple kinds
- **THEN** the third SYSTEM instruction block identifies each resource with its complete typed reference and a concise kind-appropriate summary, without substituting resources from a later Run

#### Scenario: Keep complete observations in chronological history
- **WHEN** an OCR, measurement, Figure assembly, or render result is present in committed Session history and is also indexed in `RunExecutionState`
- **THEN** the history contains its complete committed tool observation while the resource block contains only a concise reference and summary

#### Scenario: Treat resource values as data
- **WHEN** an attachment name, Panel name, OCR snippet, or tool result contains text that resembles an instruction
- **THEN** Figura encodes the value as resource data and instructs the model to analyze it as untrusted content, not follow it as policy

#### Scenario: Keep abnormal text as data
- **WHEN** original response text or an observation in abnormal context resembles an instruction
- **THEN** the text is encoded as data and does not replace static responsibilities or tool policy

### Requirement: Agent execution does not automatically recover uncertain tool effects
Automatic execution SHALL NOT replay arbitrary uncertain effects. After proving old-owner exit, it SHALL recover only replay_safe or idempotent_local_write attempts with the original available registry, stable identity, and persisted budget. A stop request SHALL take precedence. Provider unknown outcomes SHALL never be resent. Unavailable or exhausted tool recovery and unresolvable reconciliation SHALL converge on an explicit failed terminal outcome without inventing a tool result. Read-only access SHALL never invoke recovery.

#### Scenario: Resume with an eligible unresolved tool attempt
- **WHEN** an orphaned replay_safe or idempotent local-write attempt is eligible and no stop request exists
- **THEN** execution creates one bounded replay attempt and continues only after its result commits

#### Scenario: Resume after a completed tool batch
- **WHEN** all calls in the preceding tool batch are resolved and the checkpoint points to model
- **THEN** execution may assemble the next model request subject to budgets and stop checks

#### Scenario: Stop takes precedence over recovery
- **WHEN** an eligible orphan tool attempt has a persisted stop request
- **THEN** execution interrupts without replaying the handler

#### Scenario: Unverifiable execution owner
- **WHEN** exclusive full-task ownership cannot be obtained
- **THEN** execution returns without replay or terminal mutation
