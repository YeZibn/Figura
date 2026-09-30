# agent-react-execution Specification

## Purpose

Defines a bounded ReAct execution capability that turns a durable Figura Run into ordered model decisions, tool observations, and a final answer. It keeps committed Run facts as the conversation history and delegates persistence and tool effects to their existing owners.

## Requirements

### Requirement: Agent execution advances a Run through a bounded ReAct cycle
Figura SHALL provide an internal execution capability that reads the current Run checkpoint and performs only the action named by that checkpoint. For a model action, it SHALL assemble a provider request and commit one provider result; for a pending tool-execution action, it SHALL execute registered calls serially in their persisted order and return to the model only after the batch is resolved; for a final action, it SHALL complete only an accepted final response. It SHALL return terminal Runs unchanged and SHALL NOT create another Run, switch provider/model, or use streaming in this capability.

#### Scenario: Complete a text-only Run without tools
- **WHEN** the selected provider returns a nonempty response with finish reason `stop`
- **THEN** Figura commits the model response, creates the final answer, and completes the same Run

#### Scenario: Continue after a model tool-call response
- **WHEN** the selected provider returns a valid `tool_calls` response and each call produces a committed result
- **THEN** Figura sends the next model request only after the complete ordered tool batch is committed, including each tool result as an observation

#### Scenario: Execute calls in the provider's order
- **WHEN** one model response contains multiple valid tool calls
- **THEN** Figura invokes them one at a time in their persisted provider order and does not parallelize or implicitly retry them

#### Scenario: Reach a terminal Run
- **WHEN** execution is requested for a completed, failed, or interrupted Run
- **THEN** Figura returns its durable state without making a provider request or invoking a tool

### Requirement: Provider history is reconstructed from complete committed interactions
For each model action, Figura SHALL build the conversation from all earlier terminal Runs in the same Session, ordered by Run ordinal, followed by the current Run's immutable input, committed model responses, and committed tool results. Each Run input SHALL appear once as a user message containing its persisted text and ordered attachment references as text identities; it SHALL NOT automatically include image blocks. The request SHALL include the target Run's factual resource index as the third of its three ordered SYSTEM instruction blocks. The index SHALL identify every available Attachment and committed Panel, each committed OCR and measurement resource with its source and outcome, each accepted ChartFigure with its title and chart summary, and each committed render with its Figure reference and outcome. The index SHALL identify resources by their complete typed references. It SHALL NOT duplicate complete OCR, measurement, Figure, or render result payloads already present in committed tool messages. Historical render entries SHALL remain textual; Figura SHALL NOT automatically resend image bytes from an earlier Run or earlier tool batch. Each model response containing tool calls SHALL be represented by one assistant message whose calls preserve provider order, followed by one tool message for every corresponding result with the matching opaque call ID. A final-answer fact that references a response SHALL NOT add a duplicate message. Only original image blocks explicitly loaded by successful `load_image` calls in the immediately preceding fully committed tool batch may be appended as original images, in tool-call order. A fully committed batch containing successful `extract_text`, Cartesian measurement, or pie measurement calls SHALL additionally contribute one reconstructed annotated image per successful call, paired with its JSON tool observation and identified by tool name and call ID. A fully committed batch containing successful `render_chart_figure` calls SHALL additionally contribute each corresponding stored PNG once, paired with its committed JSON tool observation and identified by tool name and call ID, in tool-call order. The resource index and image selection SHALL use the same authorized Run prefix as the committed conversation. Completed tool-call/result pairs recorded under an earlier registry version SHALL be projected as inert conversation history and SHALL NOT be executed again; unresolved calls or incomplete batches SHALL fail closed. Provider-private continuation SHALL be attached only to its originating assistant response in the current Run and SHALL NOT be carried across Run boundaries. Figura SHALL NOT send a partial tool batch, invent a missing result, include an unresolved tool attempt as a result, or expose continuation data in public projections or ordinary diagnostics.

#### Scenario: Build the first model request with multiple attachments
- **WHEN** the checkpoint points to the initial model action and the current Run references multiple images
- **THEN** the request contains the three ordered SYSTEM instruction blocks, persisted user text, and a complete typed resource index in the third block, but no image bytes

#### Scenario: Include earlier Session Runs and their resources
- **WHEN** the checkpoint points to a model action and the Session has earlier terminal Runs with referenced attachments and committed tool resources
- **THEN** the request contains all earlier Run messages in ascending Run ordinal, preserves their text and attachment IDs, indexes each eligible resource once by its typed reference, and does not attach historical image bytes

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
- **WHEN** a tool call from a prior registry version has no committed matching result or belongs to an incomplete batch
- **THEN** Figura does not construct or dispatch a Provider request and does not execute the old call under the current registry

#### Scenario: Do not carry continuation across Runs
- **WHEN** an earlier Run's response has provider-private continuation data
- **THEN** Figura includes the normalized assistant response and committed tool facts in Session history but omits that continuation from the later Run's Provider request

### Requirement: Referenced images are resolved and bounded before provider-attempt claim
Before a durable Provider attempt is claimed, Figura SHALL resolve every requested image from its typed reference in the target Run's unified resource catalog. It SHALL resolve successful `load_image` references from the immediately preceding fully committed tool batch, reconstruct transient annotations for successful `extract_text` and chart-measurement resources in that batch from their authorized source and committed result, and resolve and validate the private PNG for each successful `render_chart_figure` resource against its committed render metadata. It SHALL validate image count, individual byte size, aggregate image byte size, and all other Provider limits. When the checkpoint follows no successful image-load, text-extraction, chart-measurement, or Figure-render call, the request SHALL contain no image bytes. Figura SHALL NOT claim or dispatch a Provider attempt when a requested original, annotated, or rendered image cannot be resolved, does not belong to the Session inventory, fails integrity checks, or the assembled request exceeds a Provider limit.

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
- **WHEN** original, annotated, and rendered images for the immediately preceding tool batch exceed Provider image count, per-image size, aggregate image size, or another request limit
- **THEN** Figura fails the current Run before claiming or dispatching a Provider attempt

### Requirement: Agent requests preserve complete Session history within Provider limits
Figura SHALL submit non-streaming requests using exactly three ordered SYSTEM instruction blocks: stable Agent responsibilities, the current registered tool surface, and a factual resource inventory projected from the target Run's `RunExecutionState`. The request SHALL use the provider-neutral tool projection from the same registry represented in the tool instruction, and bounded completion options. A request SHALL contain complete same-Session history and SHALL satisfy the Provider boundary's message, instruction, tool, image, and total text/schema limits before a durable provider attempt is claimed. Figura SHALL NOT truncate, summarize, or remove any historical Run or interaction to fit a request. If the complete request exceeds any Provider limit, Figura SHALL fail the current Run before claiming or dispatching a provider attempt.

#### Scenario: Send every complete Session interaction
- **WHEN** all earlier same-Session Runs have valid complete histories and the assembled request is within Provider limits
- **THEN** Figura sends the entire earlier history and current Run prefix in ordinal and committed fact order, with the three ordered SYSTEM instruction blocks

#### Scenario: Complete history exceeds a Provider limit
- **WHEN** the full request exceeds a Provider message, instruction, tool, image, text, or schema limit
- **THEN** Figura preserves all source facts, fails the current Run, and makes no Provider-attempt claim or network request

#### Scenario: Keep a tool result associated with its call
- **WHEN** a successful or failed tool result is projected into Provider history
- **THEN** Figura sends a bounded JSON observation in a tool message associated with the original call ID and omits implementation details from an error observation

### Requirement: Agent prompt layers have explicit sources and ordered responsibilities
Figura SHALL assemble each Agent prompt from three ordered SYSTEM instruction blocks. The stable-responsibility block SHALL contain the fixed Chinese Agent, evidence, workflow, and response rules and SHALL NOT contain request-specific user or Run data. The current-tool block SHALL be projected from the exact tool registry used for the request's provider tool schemas; it SHALL describe only tools present in that registry, while the provider-native schemas remain authoritative for tool names, parameters, required fields, and allowed values. The run-resource block SHALL be projected exclusively from the target request's `RunExecutionState` and SHALL use complete typed resource references for Attachments, Panels, OCR, measurements, ChartFigures, and ChartRenders.

The resource block SHALL be a concise index and SHALL NOT replace or duplicate complete tool results in chronological Session history. It SHALL distinguish tool execution outcome from a measurement result's `status` and an OCR result's availability. Resource names, titles, OCR text, tool observations, and other data values SHALL be treated as untrusted evidence rather than instructions. The three blocks SHALL be rebuilt for every model request; no prompt or resource summary SHALL be added to durable Run facts.

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

### Requirement: ReAct decisions accept only supported model outcomes
Figura SHALL continue a Run only for a valid `tool_calls` response with one or more valid calls, or complete it only for a `stop` response with non-whitespace assistant text and no tool calls. A response with an unsupported finish reason, an empty final answer, or an invalid combination of finish reason and calls SHALL fail the Run with a bounded invalid-response outcome. A known tool failure SHALL be provided as a tool observation and SHALL NOT, by itself, cause the Agent to repeat that call.

#### Scenario: Accept a tool-call response
- **WHEN** a normalized response has finish reason `tool_calls` and its calls pass the persisted tool-call contract
- **THEN** Figura commits the response and complete ordered call batch before executing any call

#### Scenario: Reject a non-final provider response
- **WHEN** a normalized response has finish reason `length`, `content_filter`, or `other`
- **THEN** Figura records the provider outcome when validly normalized and fails the Run without treating the response as a final answer or dispatching its calls

#### Scenario: Reject an empty final answer
- **WHEN** a normalized response has finish reason `stop` but its assistant text is empty or whitespace-only
- **THEN** Figura fails the Run and does not create a final-answer record

#### Scenario: Observe a failed tool call
- **WHEN** a tool returns a bounded structured failure
- **THEN** Figura includes that failure as the matching tool observation and lets a later model response decide what to do without an executor retry

### Requirement: Each Run has fixed model-request and tool-execution budgets
Figura SHALL limit one Run to 8 durable provider attempts and 32 distinct logical tool calls whose execution has been started. It SHALL derive usage from persisted attempt and tool facts rather than a separately mutable counter. When a limit is exhausted, Figura SHALL fail the Run with a bounded execution-failure outcome before dispatching the next over-budget provider request or tool handler. A tool-call intent already committed in an over-budget model response SHALL remain durable and SHALL NOT be executed beyond the limit.

#### Scenario: Stop before a ninth provider request
- **WHEN** a model action is reached after 8 provider attempts have been committed or failed
- **THEN** Figura fails the Run without claiming or dispatching a ninth provider request

#### Scenario: Stop before a thirty-third tool execution
- **WHEN** the next persisted tool call would be the 33rd distinct logical call whose execution is started
- **THEN** Figura fails the Run without recording an attempt start or invoking that handler

#### Scenario: Count a logical call once
- **WHEN** a tool call has an attempt-start fact and the Run later reads that call again
- **THEN** budget accounting counts the call ID once, regardless of its number of attempt facts

### Requirement: Agent execution does not automatically recover uncertain tool effects
When the checkpoint points to a tool attempt without a result, Agent execution SHALL return the unresolved Run state without calling the provider, invoking the tool, or asking the durable tool executor to replay or reconcile it. Explicit recovery APIs remain owned by durable tool execution and are outside automatic ReAct scheduling.

#### Scenario: Resume with an unresolved tool attempt
- **WHEN** a Run is opened with a tool attempt recorded but no committed result
- **THEN** Agent execution returns the unresolved checkpoint without invoking the handler or issuing a model request

#### Scenario: Resume after a completed tool batch
- **WHEN** a Run is opened with all calls in the preceding tool batch resolved and its checkpoint points to a model action
- **THEN** Agent execution may assemble and dispatch the next model action subject to the provider-attempt budget
