# agent-react-execution Specification

## Purpose

Defines a bounded, text-only ReAct execution capability that turns a durable Figura Run into ordered model decisions, tool observations, and a final answer. It keeps committed Run facts as the conversation history and delegates persistence and tool effects to their existing owners.

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
For each model action, Figura SHALL build the conversation from the Run's immutable input, the validated images referenced by that input, committed model responses, and committed tool results. The original user message SHALL contain the persisted text followed by image blocks in the exact order of the persisted attachment IDs. Each model response containing tool calls SHALL be represented by one assistant message whose calls preserve provider order, followed by one tool message for every corresponding result with the matching opaque call ID. A provider-private continuation SHALL be attached only to its originating assistant response. Figura SHALL NOT send a partial tool batch, invent a missing result, include an unresolved tool attempt as a result, or expose continuation data in public projections or ordinary diagnostics.

#### Scenario: Build the first model request
- **WHEN** the checkpoint points to the initial model action after Run creation
- **THEN** the request contains the fixed v1 instruction, the persisted user text followed by its referenced images in persisted order, and the Run's explicit provider/model selection

#### Scenario: Rebuild a completed tool round
- **WHEN** the checkpoint points to a model action after a fully resolved tool batch
- **THEN** the request contains the original user text and images, the assistant tool-call message, and all matching tool result messages in their committed order, with continuation attached to the correct assistant message

#### Scenario: History contains an unresolved tool attempt
- **WHEN** a Run's current checkpoint points to a tool attempt without a committed result
- **THEN** Figura does not construct a later model request from that incomplete interaction

#### Scenario: Historical tool registry is unavailable
- **WHEN** the current registry does not match the registry version recorded by a committed tool batch
- **THEN** Figura fails closed without dispatching a provider request or a tool

### Requirement: Referenced images are resolved and bounded before provider-attempt claim
Before a durable provider attempt is claimed, Figura SHALL resolve every Run input attachment using the Run's Session ID, assemble the Provider request, and validate image count, individual byte size, aggregate image byte size, and all other Provider limits. Figura SHALL NOT claim or dispatch a provider attempt when an attachment cannot be resolved or the assembled request exceeds a Provider limit.

#### Scenario: Assemble a valid bounded image request
- **WHEN** all persisted image references resolve and the assembled request is within Provider image and request limits
- **THEN** Figura may claim the provider attempt and dispatch the request with image bytes held only in memory for the Provider call

#### Scenario: An image reference cannot be resolved
- **WHEN** a Run references a missing, unreadable, or invalid image file
- **THEN** Figura fails the Run before claiming a provider attempt and sends no request to the Provider

#### Scenario: Images exceed Provider request bounds
- **WHEN** referenced images exceed the Provider image count, individual image size, aggregate image size, or another request limit
- **THEN** Figura fails the Run before claiming a provider attempt and sends no request to the Provider

### Requirement: Agent requests preserve complete recent context within provider limits
Figura SHALL submit non-streaming requests using one fixed v1 system instruction, the provider-neutral tool projection for the selected registry, and bounded completion options. A request SHALL satisfy the Provider boundary's message, instruction, tool, and total text/schema limits before a durable provider attempt is claimed. When old interactions must be removed to fit, Figura SHALL remove only the oldest fully resolved assistant/tool rounds, preserve the original user input and newest complete round, and fail before provider dispatch if those required messages still exceed a limit.

#### Scenario: Trim old complete interactions
- **WHEN** the assembled history exceeds the Provider boundary's message or text/schema limit and at least one older complete tool round can be removed
- **THEN** Figura removes oldest complete rounds until the request fits while preserving the user input and newest complete round

#### Scenario: Required history cannot fit
- **WHEN** the user input, fixed instruction, tool schemas, and newest complete round exceed a Provider boundary limit after all older rounds are removed
- **THEN** Figura fails the Run without claiming a provider attempt or sending a request

#### Scenario: Keep a tool result associated with its call
- **WHEN** a successful or failed tool result is projected into provider history
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
