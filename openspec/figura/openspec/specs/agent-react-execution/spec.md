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
For each model action, Figura SHALL build the conversation from all earlier terminal Runs in the same Session, ordered by Run ordinal, followed by the current Run's immutable input, committed model responses, and committed tool results. Each Run input SHALL appear once as a user message containing its persisted text and ordered attachment references as text identities; it SHALL NOT automatically include image blocks. The request SHALL include a text inventory of every available attachment and committed Panel in the target Run's `RunExecutionState`, including same-Session attachments referenced only by earlier terminal Runs. Each model response containing tool calls SHALL be represented by one assistant message whose calls preserve provider order, followed by one tool message for every corresponding result with the matching opaque call ID. A final-answer fact that references a response SHALL NOT add a duplicate message. Only image blocks explicitly loaded by successful `load_image` calls in the immediately preceding fully committed tool batch may be appended to the request, in tool-call order. A provider-private continuation SHALL be attached only to its originating assistant response in the current Run and SHALL NOT be carried across Run boundaries. Figura SHALL NOT send a partial tool batch, invent a missing result, include an unresolved tool attempt as a result, or expose continuation data in public projections or ordinary diagnostics.

#### Scenario: Build the first model request with multiple attachments
- **WHEN** the checkpoint points to the initial model action and the current Run references multiple images
- **THEN** the request contains the fixed v1 instruction, the persisted user text, and a complete textual image inventory, but no image bytes

#### Scenario: Include earlier Session Runs and their attachments
- **WHEN** the checkpoint points to a model action and the Session has earlier terminal Runs with referenced attachments
- **THEN** the request contains all earlier Run messages in ascending Run ordinal, preserves their text and attachment IDs, lists their images in the available-image inventory, and does not attach their historical image bytes

#### Scenario: Rebuild a completed tool round with explicitly loaded images
- **WHEN** the checkpoint points to a model action after a fully resolved tool batch containing one or more successful `load_image` calls
- **THEN** the request contains the original ordered assistant/tool interaction and attaches each loaded image once after the text inventory in the persisted tool-call order

#### Scenario: Do not repeat images from an older tool batch
- **WHEN** the latest completed tool batch contains no successful `load_image` call, even though an earlier batch or Run loaded an image
- **THEN** the request contains no image bytes from that earlier batch or Run

#### Scenario: History contains an unresolved tool attempt
- **WHEN** the current Run or an earlier Run contains a tool attempt without a committed result
- **THEN** Figura does not construct or dispatch a model request from that incomplete interaction

#### Scenario: Historical tool registry is unavailable
- **WHEN** the current registry does not match the registry version recorded by a committed tool batch in the current or an earlier Run
- **THEN** Figura fails closed without dispatching a provider request or a tool

#### Scenario: Do not carry continuation across Runs
- **WHEN** an earlier Run's response has provider-private continuation data
- **THEN** Figura includes the normalized assistant response and committed tool facts in Session history but omits that continuation from the later Run's Provider request

### Requirement: Referenced images are resolved and bounded before provider-attempt claim
Before a durable Provider attempt is claimed, Figura SHALL derive the authorized attachment and Panel inventories from the target Run's `RunExecutionState`, resolve only the successful `load_image` results in the immediately preceding fully committed tool batch, assemble their bytes as user-role image blocks, and validate image count, individual byte size, aggregate image byte size, and all other Provider limits. If the checkpoint follows no `load_image` call, the request SHALL contain no image bytes. Figura SHALL NOT claim or dispatch a Provider attempt when a requested image cannot be resolved, does not belong to the Session inventory, or the assembled request exceeds a Provider limit.

#### Scenario: Assemble a valid request after explicit image loads
- **WHEN** every distinct image loaded by the immediately preceding tool batch resolves from the authorized same-Session inventory and the request is within Provider limits
- **THEN** Figura may claim the Provider attempt and dispatch the request with those image bytes held only in memory

#### Scenario: Assemble a request without a preceding image load
- **WHEN** the current checkpoint follows Run creation or a tool batch without a successful `load_image` result
- **THEN** Figura assembles and validates the text and tool history without resolving any attachment or Panel bytes

#### Scenario: An explicitly loaded image cannot be resolved
- **WHEN** a successful `load_image` result refers to a missing, unreadable, invalid, or differently owned image
- **THEN** Figura fails the current Run before claiming a Provider attempt and sends no request to the Provider

#### Scenario: Explicitly loaded images exceed Provider bounds
- **WHEN** images loaded by the immediately preceding tool batch exceed the Provider image count, per-image size, aggregate image size, or another request limit
- **THEN** Figura fails the current Run before claiming or dispatching a Provider attempt

### Requirement: Agent requests preserve complete Session history within Provider limits
Figura SHALL submit non-streaming requests using one fixed v1 system instruction, the provider-neutral tool projection for the selected registry, and bounded completion options. A request SHALL contain complete same-Session history and SHALL satisfy the Provider boundary's message, instruction, tool, image, and total text/schema limits before a durable provider attempt is claimed. Figura SHALL NOT truncate, summarize, or remove any historical Run or interaction to fit a request. If the complete request exceeds any Provider limit, Figura SHALL fail the current Run before claiming or dispatching a provider attempt.

#### Scenario: Send every complete Session interaction
- **WHEN** all earlier same-Session Runs have valid complete histories and the assembled request is within Provider limits
- **THEN** Figura sends the entire earlier history and current Run prefix in ordinal and committed fact order

#### Scenario: Complete history exceeds a Provider limit
- **WHEN** the full request exceeds a Provider message, instruction, tool, image, text, or schema limit
- **THEN** Figura preserves all source facts, fails the current Run, and makes no Provider-attempt claim or network request

#### Scenario: Keep a tool result associated with its call
- **WHEN** a successful or failed tool result is projected into Provider history
- **THEN** Figura sends a bounded JSON observation in a tool message associated with the original call ID and omits implementation details from an error observation

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
