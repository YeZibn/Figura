# agent-react-execution Specification

## Purpose

Defines a bounded ReAct execution capability that turns a durable Figura Run into ordered model decisions, tool observations, and a final answer. It keeps committed Run facts as the conversation history and delegates persistence and tool effects to their existing owners.

## Requirements

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

### Requirement: Provider history is reconstructed from complete committed interactions
For each model action, Figura SHALL build the conversation from all earlier terminal Runs in the same Session, ordered by Run ordinal, followed by the current Run's immutable input, committed model responses, and committed tool results. Without input-aware coverage, each input SHALL appear once with persisted text and ordered attachment identities without automatically including images. With input-aware coverage, covered prior inputs and process SHALL be represented by the source-linked summary; uncovered prior inputs SHALL remain raw. Current input SHALL remain a complete native user message even when current process is summarized. Legacy process-only checkpoints SHALL NOT by themselves authorize omission of prior inputs. The request SHALL include the target Run's factual resource index in its running-resource SYSTEM instruction block. The index SHALL identify the resources selected for the request's authorized locator projection, including eligible Attachments, Panels, OCR, measurements, Figures and renders with kind-appropriate summaries; other authorized resources SHALL remain discoverable through history search and full server-side lookup. The index SHALL identify resources by their complete typed references. It SHALL NOT duplicate complete OCR, measurement, Figure, or render result payloads already present in committed tool messages. Historical render entries SHALL remain textual; Figura SHALL NOT automatically resend image bytes from an earlier Run or earlier tool batch. Each retained raw closed model/tool interaction SHALL be represented by one assistant message whose calls preserve provider order, followed by one tool message for every corresponding result with the matching opaque call ID. A validated incomplete trailing batch from an earlier failed or interrupted Run SHALL be represented entirely by source-linked abnormal outcome data in the running-resource SYSTEM instruction block, preserving its intent and committed observations instead of sending dangling native calls. A final-answer fact that references a response SHALL NOT add a duplicate message. The next ordinary model action following a fully committed visual tool batch SHALL include every ordered attachment of each successful result inside that call's single native tool-result message, after its complete structured observation. Image identity and a type-specific hint SHALL be adjacent to that image. Selection SHALL follow committed attachment descriptions, not a central list of image-producing tool names. Different calls reading the same source SHALL each retain their own image occurrence; cross-call source deduplication SHALL NOT remove an image from its logical result. Failed results SHALL have no image. Older results retained in raw history SHALL retain data and attachment descriptions with an explicit not-loaded projection and SHALL NOT resend image bytes unless a new explicit image-read call returns them. No plain user image feedback message SHALL be appended. The resource index and image selection SHALL use the same authorized Run prefix as the committed conversation. Completed tool-call/result pairs recorded under an earlier registry version SHALL be projected as inert conversation history and SHALL NOT be executed again; unresolved work in the current Run, incomplete completed history, or corrupt facts SHALL fail closed; legal terminal incomplete tails SHALL follow the abnormal outcome projection. Provider-private continuation SHALL be attached only to the exact originating assistant response retained in role history, including a prior Run when the selected Provider and format are compatible. Continuation from a converted incomplete batch SHALL NOT be placed in outcome context or fabricated for it. Figura SHALL NOT send a partial tool batch, invent a missing result, include an unresolved tool attempt as a result, or expose continuation data in public projections or ordinary diagnostics.

#### Scenario: Build the first model request with multiple attachments
- **WHEN** the checkpoint points to the initial model action and the current Run references multiple images
- **THEN** the request contains stable-rule, tool-directory, optional-summary and running-resource SYSTEM instruction blocks, persisted user text, and a complete typed reference for each selected resource in the running-resource block, but no image bytes

#### Scenario: Include earlier Session Runs and their resources
- **WHEN** the checkpoint points to a model action and the Session has earlier terminal Runs with referenced attachments and committed tool resources
- **THEN** the request represents covered history by its source-linked summary and uncovered closed history in ascending Run ordinal, preserves raw input attachment identities and abnormal contexts, indexes selected resources once by exact typed reference and does not attach historical image bytes

#### Scenario: Keep full results in chronological tool history
- **WHEN** a committed OCR, measurement, Figure assembly, or render interaction is retained in raw Session history
- **THEN** its complete committed tool result appears in its original tool message and the textual resource index contains only a concise reference and summary, without a duplicate full result payload

#### Scenario: Rebuild a completed tool round with explicitly loaded images
- **WHEN** the checkpoint points to a model action after a fully resolved tool batch containing one or more successful `load_image` calls
- **THEN** the request contains the ordered assistant/tool interaction and includes each call's original image inside its own tool-result content in persisted call order

#### Scenario: Include visual feedback for the latest observation batch
- **WHEN** the immediately preceding fully committed tool batch contains successful `extract_text` or `measure_chart` calls for any supported family
- **THEN** the request contains each corresponding JSON tool result and one matching saved annotated image within each successful call's tool result in tool-call order, with the tool name and call ID identified

#### Scenario: Include a rendered Figure in the next model action
- **WHEN** the immediately preceding fully committed tool batch contains one or more successful `render_chart_figure` calls
- **THEN** the next Provider request contains each corresponding JSON tool result and one matching stored PNG inside each successful render call's tool result in call order

#### Scenario: Do not repeat images from an older tool batch
- **WHEN** the latest completed tool batch has no successful result with image attachments
- **THEN** the request contains no image bytes from earlier batches or Runs

#### Scenario: Preserve completed prior-version calls as inert history
- **WHEN** an earlier Run or a completed interaction in the current Run contains a fully paired assistant tool call and result recorded under a prior registry version
- **THEN** Figura retains the interaction in original order when raw or represents it through authorized summary coverage, and never invokes its historical handler

#### Scenario: Fail closed on a prior-version unresolved tool call
- **WHEN** a tool call from a prior registry version is unresolved in the current Run, or belongs to an incomplete completed historical Run
- **THEN** Figura does not construct or dispatch a Provider request and does not execute the old call under the current registry

#### Scenario: Replay only compatible source continuation
- **WHEN** an earlier Run has a compatible private continuation for an assistant response retained in role history
- **THEN** Figura attaches that unchanged continuation to its exact source response while keeping it out of neutral Memory and abnormal outcome data

#### Scenario: Include abnormal tail observations without duplicate payloads
- **WHEN** an earlier interrupted Run has a partly completed tool batch
- **THEN** the running-resource instruction block contains its source-linked outcome context, role history contains only its closed interactions, and the resource index contains only eligible references and summaries

#### Scenario: Do not create a second result for image content
- **WHEN** one successful call returns business data and image attachments
- **THEN** Figura emits a single native tool-result message containing both rather than a text result followed by another message using the same tool_call_id

#### Scenario: Keep shared images associated with each caller
- **WHEN** two successful calls in one batch load the same authorized resource
- **THEN** each result retains its own image and hint under its own call ID even when storage reuses the same bytes

#### Scenario: Compact active process and retain current input
- **WHEN** a summary covers earlier complete interactions of the current Run
- **THEN** Figura sends their source-linked summary, recent complete raw interactions and the full current user input exactly once

### Requirement: Referenced images are resolved and bounded before provider-attempt claim
Before claiming a durable Provider attempt, Figura SHALL resolve selected committed attachments from the full authorized resource catalog and verify image bytes against their descriptors. Attachment/Panel reads SHALL use their owning source services; OCR/measurement and render feedback SHALL read already saved media. Request construction SHALL NOT redraw annotations or infer attachments from tool names. Prompt-directory filtering SHALL NOT restrict the full server-side authorized lookup used to resolve a selected attachment.

Figura SHALL check each raw image size, aggregate bytes, source/descriptor integrity, shared structured-request guard and genuine selected-Provider limits without a generic image-count cap. With no selected attachments the request SHALL contain no image bytes. Missing, unreadable, differently owned, mismatched or unsupported media SHALL cause the existing safe preparation failure before claim or dispatch, never a replacement image or plain user fallback.

#### Scenario: Assemble a valid request after explicit image loads
- **WHEN** every attachment returned by the immediately preceding batch resolves from the authorized same-Session resource catalog and the assembled request is within Provider limits
- **THEN** Figura may claim the Provider attempt and dispatch the request with those original image bytes held only in memory

#### Scenario: Assemble a valid request after text extraction or measurement
- **WHEN** each successful text-extraction or chart-measurement resource in the immediately preceding batch has a matching committed result and its recorded annotation file matches the committed descriptor
- **THEN** Figura reads and validates the matching saved annotated images and may claim and dispatch the Provider request within Provider limits

#### Scenario: Assemble a valid request after Figure rendering
- **WHEN** each successful render resource in the immediately preceding batch has a matching committed render result and its private PNG matches the committed metadata
- **THEN** Figura assembles and validates the rendered images and may claim and dispatch the Provider request within Provider limits

#### Scenario: Assemble a request without a preceding image observation
- **WHEN** the current checkpoint follows Run creation or a complete batch whose results contain no image attachments
- **THEN** Figura assembles and validates the text and tool history without resolving Attachment, Panel, or render image bytes

#### Scenario: An image required for visual feedback cannot be resolved
- **WHEN** a successful `load_image`, text-extraction, chart-measurement, or chart-render resource refers to missing, unreadable, invalid, differently owned, or integrity-mismatched content needed by the next request
- **THEN** Figura fails the current Run before claiming a Provider attempt and sends no request

#### Scenario: Images exceed Provider bounds
- **WHEN** original, annotated, and rendered images for the immediately preceding tool batch exceed a genuine selected-Provider image restriction, retained per-image or aggregate byte guard, or the shared structured-request guard
- **THEN** Figura fails the current Run before claiming or dispatching a Provider attempt

#### Scenario: Resolve media using the full catalog after prompt filtering
- **WHEN** a selected committed attachment is authorized but its resource is omitted from the compact Prompt directory
- **THEN** the resolver uses the complete authorized catalog and does not falsely reject the attachment or load another image

### Requirement: Agent requests preserve complete Session history within Provider limits
Figura SHALL reconstruct ordinary requests from complete durable Session facts using the canonical streaming Provider path and ordered stable-rule, exact-tool, optional-summary and running-resource SYSTEM layers. Source-linked compaction SHALL replace eligible old history under the session-context-compaction contract, including prior user input only with input-aware coverage. Current user input SHALL remain complete. Resource filtering SHALL affect model-visible locator metadata without reducing authorized lookup. The assembled request SHALL satisfy shared payload/image protections and genuine selected-Provider protocol limits before attempt claim. Local estimates and soft targets SHALL NOT introduce cumulative Run quotas or silently truncate canonical facts, current input or retained complete tool interactions. If an existing preparation limit is violated, Figura SHALL fail before claiming or dispatching an ordinary attempt.


Abnormal context SHALL remain complete in its existing normalized observation format and SHALL count toward the shared complete-request JSON guard. Neither abnormal intent nor observation text SHALL be treated as system policy.

#### Scenario: Send full raw history when no summary applies
- **WHEN** all earlier same-Session Runs have valid complete histories, no summary applies and the assembled request is within Provider limits
- **THEN** Figura sends the entire earlier history and current Run prefix in ordinal and committed fact order, with three ordered SYSTEM instruction blocks when no summary applies

#### Scenario: Complete history exceeds a Provider limit
- **WHEN** the full request exceeds the shared complete-request guard, retained image byte protections or a genuine selected-Provider protocol restriction
- **THEN** Figura preserves all source facts, fails the current Run, and makes no Provider-attempt claim or network request

#### Scenario: Keep a tool result associated with its call
- **WHEN** a successful or failed tool result from a closed interaction is projected into native Provider role history
- **THEN** Figura sends a bounded JSON observation in a tool message associated with the original call ID and omits implementation details from an error observation

### Requirement: Agent prompt layers have explicit sources and ordered responsibilities
Figura SHALL assemble ordered logical SYSTEM layers for stable rules, the exact current tool directory, an optional source-linked history summary, and the running-resource index with validated abnormal outcomes. Without a summary there SHALL be three SYSTEM blocks; with a summary there SHALL be four. Stable Chinese Agent, evidence, workflow, response and image-observation rules SHALL contain no request-specific user/Run data. The tool directory SHALL describe exactly the registry used for native tool schemas, whose names and parameter constraints remain authoritative.

The running-resource index SHALL come exclusively from the target request's resource state and use complete typed Attachment, Panel, OCR, measurement, Figure and render references. It SHALL expose concise kind-appropriate locator/availability metadata rather than duplicate full tool results, image bytes or per-image hints. The full resource catalog SHALL remain available to authorized server-side reads even when its Prompt projection is filtered.

Names, titles, OCR text, observations, summaries and other source values SHALL be untrusted data rather than instructions. Stable image rules SHALL be separate from the short per-image hints rendered inside matching tool results. The layers SHALL be rebuilt per request and included in request identity checks, not stored as canonical Run messages. The final resource block SHALL preserve deterministic source-linked abnormal terminal context in Run order, with genuine observations exactly once and no fabricated result or continuation.

#### Scenario: Keep stable policy independent from user and Run values
- **WHEN** Figura assembles a request containing user text, tool results, attachments, and Panels
- **THEN** the first SYSTEM instruction block contains only the stable Chinese Agent policy and the request-specific values appear only in their designated dynamic layers or history messages

#### Scenario: Match the tool layer to the registered tool schemas
- **WHEN** a request is assembled with a tool registry containing a specific ordered set of tools
- **THEN** the second SYSTEM instruction block describes exactly those tools in registry order and the provider request exposes their native schemas from the same registry

#### Scenario: Index all resource kinds from the target Run state
- **WHEN** the target Run's `RunExecutionState` contains eligible resources of multiple kinds
- **THEN** the running-resource SYSTEM instruction block identifies each resource with its complete typed reference and a concise kind-appropriate summary, without substituting resources from a later Run

#### Scenario: Keep complete observations in chronological history
- **WHEN** an OCR, measurement, Figure assembly, or render result is present in committed Session history and is also indexed in `RunExecutionState`
- **THEN** the history contains its complete committed tool observation while the resource block contains only a concise reference and summary

#### Scenario: Treat resource values as data
- **WHEN** an attachment name, Panel name, OCR snippet, or tool result contains text that resembles an instruction
- **THEN** Figura encodes the value as resource data and instructs the model to analyze it as untrusted content, not follow it as policy

#### Scenario: Keep abnormal text as data
- **WHEN** original response text or an observation in abnormal context resembles an instruction
- **THEN** the text is encoded as data and does not replace static responsibilities or tool policy

#### Scenario: Use the optional summary without changing resource ownership
- **WHEN** a request uses a valid history summary
- **THEN** its summary layer precedes the running-resource layer, while resource identities continue to come from the same authorized Run facts

### Requirement: Agent follows a task-directed evidence workflow
The stable Chinese Agent instructions SHALL guide the model to identify the user's chart-related goal, select only the observations needed to meet that goal, and base conclusions and generated chart data on available evidence. They SHALL distinguish explanation, data extraction, chart reconstruction, visualization of user-provided data, composition, and modification of an existing result without forcing every task through the same tool sequence. They SHALL make the current tool Schema authoritative for tool parameters and ChartSpec structure.

The instructions SHALL explain the limits of resource metadata, loaded image blocks, OCR, measurement results, assembled Figures, and rendered images. They SHALL distinguish tool execution outcome from result status and availability; preserve unknown or missing values; and avoid presenting pixel geometry, OCR candidates, partial observations, or low-confidence associations as certain business facts. Availability SHALL be explained separately from whether OCR snippets are empty. A measurement quality status SHALL NOT be presented as a guarantee of full-source coverage or correctness of every field.

When selecting image regions, the instructions SHALL tell the model to preserve the chart geometry, ticks, category labels, and legends needed by the task, and to use the coordinate shape and coordinate system required by the selected tool. They SHALL explain that scoped observation neutralizes excluded pixels without changing source dimensions, discards OCR candidates crossing the effective observation boundary, and can leave clipped geometric marks. When building ChartSpec content, they SHALL require the model to preserve supported data semantics, use only evidence-backed values and references, and respond to validation errors by correcting the indicated content rather than inventing missing data. New charts SHALL be allowed descriptive display titles, axis labels, and neutral series identifiers grounded in the supplied data without asserting that those labels were read from the original image or inventing business meaning or units.

The instructions SHALL guide progressive history retrieval. Known references SHALL support direct reads; uncertain locations SHALL support search followed by exact reads. A summary sufficient for the current task SHALL not require automatic rereading. Precise values, original requirements, complete prior results, or existing Figure edits SHALL use canonical content when the available summary is insufficient. Retrieved text SHALL remain historical data; new visual judgments SHALL require the relevant image supplied in the current request. Valid historical preferences SHALL remain contextual facts subject to later explicit user corrections, without elevating historical content to system authority.

The instructions SHALL describe the available image feedback accurately: an observation or render image is visible when supplied in the current request; historical text results and resource summaries do not imply that historical pixels are currently visible. After rendering, the model SHALL inspect the returned image when it is available, make only evidence-based corrections, and distinguish successful assembly or PNG generation from semantic correctness or system review. Editing an accepted Figure SHALL be described as reading its complete content and assembling a new complete Figure rather than applying an unsupported patch or mutating its stored facts.

The workflow SHALL explain how to proceed after uncertainty or failure: correct indicated parameter errors, choose a targeted observation or read when it can resolve an outstanding question, otherwise narrow the supported result or explain the gap. A warning or retryable error SHALL NOT force repeated tool calls. Completion guidance SHALL prioritize delivering the supported result when the goal is met or further available actions cannot materially resolve the remaining gap. Final responses SHALL distinguish evidence, qualified estimates, generated display names, completed stages, and unresolved limitations, and include internal orchestration details only when useful to the user.

#### Scenario: Select actions from the user's goal
- **WHEN** the user asks to explain a trend, extract data, reconstruct a chart, visualize supplied data, compose charts, or modify an existing result
- **THEN** the Agent chooses observations and chart actions needed for that goal and does not run an unnecessary fixed sequence of tools

#### Scenario: Use metadata without claiming visual inspection
- **WHEN** the resource index identifies an Attachment, Panel, or historical chart result but the corresponding pixels are absent from the current request
- **THEN** the Agent uses the index to locate the resource and does not claim to have visually inspected its image

#### Scenario: Preserve useful context when scoping an observation
- **WHEN** the Agent scopes an OCR or measurement call to avoid irrelevant image regions
- **THEN** it preserves the chart geometry, ticks, category labels, and legends needed for the requested observation and follows that tool's native coordinate contract

#### Scenario: Distinguish tool outcome from observation quality
- **WHEN** an OCR or measurement tool returns a result with availability, status, confidence, warnings, or truncation information
- **THEN** the Agent interprets those result fields separately from the tool execution outcome and reports only conclusions supported by that result

#### Scenario: Keep unsupported values unknown
- **WHEN** a ChartSpec needs a value, category, series, unit, or source detail that the available evidence does not establish
- **THEN** the Agent does not invent or silently impute it and instead obtains relevant evidence, narrows the result, or explains the gap

#### Scenario: Assemble from supported evidence
- **WHEN** the user requests a generated chart and the Agent has enough evidence to construct it
- **THEN** the Agent creates ChartSpec data according to the current chart type and native Schema, references only successful measurement resources it actually uses, and treats successful assembly as structural acceptance only

#### Scenario: Correct a rejected assembly
- **WHEN** Figure assembly returns a validation error with a field path
- **THEN** the Agent uses that path and error to correct the affected content and does not fill missing evidence with fabricated values

#### Scenario: Inspect generated image feedback
- **WHEN** a chart render succeeds and its image is attached to the next model request
- **THEN** the Agent checks the visible image against the task and supporting data, corrects only observed mismatches, and does not describe render success as semantic approval or system review

#### Scenario: Compare a generated chart with its source
- **WHEN** the user's task requires checking a generated chart against an Attachment or Panel
- **THEN** the Agent ensures both relevant images are supplied to the same model request before making a visual comparison

#### Scenario: Explain partial or unresolved results
- **WHEN** available evidence or tool capability cannot fully satisfy the request
- **THEN** the final response distinguishes supported facts, estimates, warnings, and unresolved gaps without presenting an incomplete result as complete

#### Scenario: Retrieve details without unnecessary searching
- **WHEN** a summary gives an exact source reference but lacks a value needed for the current task
- **THEN** the instructions direct an exact content read rather than requiring another search or inventing the missing value

#### Scenario: Modify a prior Figure from its full content
- **WHEN** the user requests a change to an earlier accepted Figure
- **THEN** the instructions direct retrieval of its complete structured content, preservation of supported unchanged data, and assembly of a new full Figure followed by rendering when needed

#### Scenario: Assign a descriptive label to supplied data
- **WHEN** the user supplies data whose meaning is established but no original chart title or axis display label
- **THEN** guidance permits an appropriate descriptive display label without representing it as a recovered source label or inventing units

#### Scenario: Avoid unproductive repeated observations
- **WHEN** an observation has warnings but no available follow-up can resolve a material remaining question
- **THEN** guidance directs delivery of the supported result with the relevant limitation rather than repeating the same call solely because a warning exists

### Requirement: Identify repeated successful visual observations within the current Run
For ordinary Agent requests, Figura SHALL identify repeated observations using only successful, committed `extract_text` and `measure_chart` calls in the authorized current Run prefix. Calls SHALL represent the same action only when tool name, registry version and complete normalized JSON arguments match. Normalization SHALL ignore object-key order and insignificant JSON formatting, preserve array order and values, and SHALL NOT infer geometric equivalence, approximate matches, or equivalence between different source IDs. Observations SHALL match only when their complete normalized structured results match, excluding the execution envelope and image attachment identities. Result status, availability, empty observations, warnings, confidence, coverage, evidence and calibration fields SHALL remain part of comparison when present.

For each action, Figura SHALL compare its latest eligible result with earlier eligible results for that action. If at least two results match that latest observation, it SHALL produce one grouped reminder with the matching successful-call count and references to the latest two matching committed results. Intervening actions SHALL NOT prevent matching. A different latest observation SHALL NOT inherit a reminder for an older observation that it does not match. Failed or unresolved calls, other tools and earlier Runs SHALL NOT contribute; replay attempts of one logical call SHALL count as one call.

#### Scenario: Second identical observation produces one reminder
- **WHEN** two distinct successful calls in the current Run use the same eligible tool, registry version and arguments and return identical structured results with different annotated-image attachments
- **THEN** the next ordinary model request includes one reminder counting two matching calls and referencing both results

#### Scenario: Interleaved actions and larger repeated groups
- **WHEN** three matching successful observations of one action are separated by history reads or other actions
- **THEN** the request includes one reminder for that action with count three and references to the latest two matching results

#### Scenario: Meaningful differences do not match
- **WHEN** source identity, scope, chart family, registry version, array order or any structured observation value differs
- **THEN** those calls do not count as identical action-observation pairs, and a latest changed observation has no reminder unless it independently matches another earlier result of its action

#### Scenario: Preserve partial and empty observations
- **WHEN** successful eligible calls repeatedly return the same partial, unsupported, unavailable or empty structured observation
- **THEN** the repeated observation is eligible for a reminder without being represented as a failed call or a confirmed business fact

#### Scenario: Exclude retries and unrelated history
- **WHEN** an attempt is replayed for the same logical call, a call fails or remains unresolved, another tool repeats, or a matching result exists only in an earlier Run
- **THEN** it does not increase the current Run's matching successful-call count

### Requirement: Repeated observation reminders preserve model autonomy and factual boundaries
Figura SHALL place grouped repetition reminders in the dynamic running-state SYSTEM instruction of the next ordinary model request after the tool batch is resolved. Each reminder SHALL state the observed repetition, matching count and latest two source references, and guide the model to consider changing scope or method or delivering supported results with limitations when further observation has no effective path. Reminders SHALL NOT assert correctness, goal completion, impossibility of future improvement or mandatory stopping. They SHALL NOT include full observations, raw tool parameters, images or source text in their repetition metadata. Referenced source values SHALL remain untrusted data.

Figura SHALL preserve original tool results and attachments, SHALL NOT add a user message for the reminder, and SHALL NOT suppress calls, reuse cached results, automatically retry tools, restrict tool permissions or introduce cumulative Run quotas as a consequence of repetition. Multiple reminders SHALL use deterministic ordering and one entry per eligible action, rather than append-only warning history.

#### Scenario: Model can choose a third identical call
- **WHEN** the model receives a repetition reminder and requests another otherwise valid identical call
- **THEN** the existing execution path executes and records that new logical call normally

#### Scenario: Batch-local repetition is observed after completion
- **WHEN** repeated eligible calls are present in one accepted tool batch
- **THEN** Figura resolves the batch normally and includes reminders in the following ordinary model request without intercepting a pending call

#### Scenario: Reminders remain separate from observations
- **WHEN** a reminder is rendered into a request
- **THEN** tool result bodies and attachments remain unchanged and no synthetic user input or tool result is created

### Requirement: Repetition reminders are reproducible from durable facts
Figura SHALL derive reminders from the same authorized committed current Run prefix used to prepare the ordinary model request, independent of summary coverage or retained raw-message tails. It SHALL NOT require a new durable repetition counter, special measurement decision state, database migration or public API field. Restarting execution with the same prefix SHALL produce the same reminder content and ordering. Existing frozen Provider request bindings SHALL remain authoritative for retries; a retry SHALL reproduce the bound request rather than recompute a different reminder from a later prefix or changed prompt assets. Summary requests SHALL NOT receive repetition reminders.

#### Scenario: Restart and compaction preserve reminders
- **WHEN** an executor restarts or raw interactions are covered by a context summary while the underlying committed current Run prefix is unchanged
- **THEN** the next newly prepared ordinary request derives the same repetition metadata and source references

#### Scenario: Retry preserves bound reminder content
- **WHEN** a logical Provider request containing repetition reminders undergoes a transport retry
- **THEN** the retry reproduces its frozen request contract including reminder content and existing fingerprint checks

#### Scenario: Summary request remains dedicated to compaction
- **WHEN** Figura prepares a context-compaction request for a Run with repeated observations
- **THEN** it uses the existing summary contract without adding the ordinary repetition reminder block

### Requirement: Agent periodically rechecks task direction
For an ordinary model request, Figura SHALL count committed ordinary model responses in the authorized current Run. When that count is a positive multiple of 20 and another ordinary model request is prepared, the dynamic running-state SYSTEM instruction SHALL include one `task_reflection` entry with `completed_rounds` set to the committed response count and `interval_rounds` set to 20. The entry SHALL appear in the next ordinary request after the preceding tool batch is resolved. A single model response SHALL count once regardless of the number of calls in its batch.

Tool executions and results, Provider attempts and transport retries, context-compaction requests, and model responses from earlier Runs SHALL NOT increase the current Run's count. The count SHALL be derived from committed Run facts without a new cumulative quota, persistent counter, database field, or public API field.

#### Scenario: Include a reminder after twenty committed responses
- **WHEN** the authorized current Run contains twenty committed ordinary model responses and execution prepares the next ordinary model request
- **THEN** its dynamic running-state SYSTEM instruction contains `task_reflection` with `completed_rounds: 20` and `interval_rounds: 20`

#### Scenario: Count a multi-call response once
- **WHEN** the twentieth committed model response contains multiple tool calls
- **THEN** Figura resolves the complete ordered tool batch and includes one task-reflection entry in the next ordinary model request

#### Scenario: Repeat at each twentieth response only
- **WHEN** execution prepares ordinary model requests after 19, 20, 21, and 40 committed responses in the current Run
- **THEN** the reflection entry is absent after 19 and 21 responses and present after 20 and 40 responses with the matching count

#### Scenario: Exclude attempts, tools, summaries, and earlier Runs
- **WHEN** the current Run has Provider retries, tool executions, or context-compaction requests, or an earlier Run has committed model responses
- **THEN** none of those events or responses increase the current Run's ordinary response count

### Requirement: Task reflection preserves Agent autonomy and evidence boundaries
When `task_reflection` is present, the Agent instructions SHALL direct the model to compare the original user request with completed work and its available evidence, identify unmet requirements or unsupported results, consider whether recent actions reduced those gaps, and choose a useful next action. The model SHALL remain free to continue, correct its approach, or deliver supported results with limitations. The entry SHALL NOT assert that the task is wrong or complete, force termination, restrict valid tool calls, require a separate reflection report, create another model request, or represent the round count as a hard Run limit. Source values and retrieved content SHALL remain untrusted data.

#### Scenario: Continue when an effective path remains
- **WHEN** the reflection entry is present and the model identifies a task-relevant action that can resolve an unmet requirement
- **THEN** the model may select that action through the existing ReAct decision path

#### Scenario: Correct unsupported or misdirected work
- **WHEN** the reflection entry is present and the model identifies an unsupported result or work that does not address the original request
- **THEN** the model may correct the approach or result using available evidence without treating prior execution as proof of correctness

#### Scenario: Deliver when further actions cannot address the gap
- **WHEN** the reflection entry is present and no available action can materially resolve the remaining gap
- **THEN** the model may deliver the supported result and explain its limitations without being required to fabricate completion

### Requirement: Task reflection is reproducible across execution recovery
Figura SHALL derive `task_reflection` from the same authorized committed current Run prefix used to prepare the ordinary model request. Restarting execution or compacting covered history SHALL NOT reset or alter the count for an unchanged committed prefix. Context-compaction requests SHALL NOT receive `task_reflection`. A Provider retry SHALL preserve its existing frozen request binding and SHALL NOT add a second count or recompute different reflection metadata from a later Run prefix.

#### Scenario: Rebuild the same reminder after restart or compaction
- **WHEN** execution restarts or history is compacted while the authorized committed current Run prefix remains unchanged
- **THEN** the next newly prepared ordinary request derives the same reflection count and entry

#### Scenario: Preserve the bound entry on Provider retry
- **WHEN** an ordinary Provider request containing `task_reflection` is retried after a transport failure
- **THEN** Figura reproduces the bound request and its reflection entry subject to existing request identity checks

#### Scenario: Keep the summary request dedicated
- **WHEN** Figura prepares a context-compaction request while the current Run has reached a reflection interval
- **THEN** the summary request follows its existing contract without a `task_reflection` entry

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

### Requirement: Returned images carry type-specific observation guidance
For every image actually included in an ordinary request, Figura SHALL place exactly one adjacent resource-identity cue and short observation hint inside the same logical tool result as that image. The hint SHALL derive from trusted image guidance templates using the attachment's image_kind: original, ocr_annotation, measurement_annotation, or rendered. Stable observation policy SHALL stay in SYSTEM instructions. Neither resource names, OCR text, retrieved data nor model-supplied strings SHALL become trusted hint templates.

Hints SHALL guide task-relevant inspection without declaring verification, forcing a report or creating another model action. An explicitly reloaded historical image SHALL use its original resource type and provenance while the surrounding result retains the current read call's ID. Attachment and call order SHALL be preserved; every different call's image occurrence SHALL remain associated with that call. No actual image means no per-image hint, including text-only history, errors, resource indexes and summary requests. Hint/template changes SHALL participate in the existing request fingerprint and Prompt identity checks and SHALL NOT silently replace a bound request.

#### Scenario: Observe an original image
- **WHEN** an authorized Attachment or Panel image is appended after loading
- **THEN** its cue identifies the original resource and guides task-relevant inspection of chart family, layout, axes, labels, and legends without forcing measurement

#### Scenario: Inspect OCR annotations
- **WHEN** an OCR annotation image is appended
- **THEN** its cue identifies the OCR resource and guides comparison with its structured observation for missing text, misplaced boxes, and incorrect associations, without treating recognized text as certain truth

#### Scenario: Inspect measurement annotations
- **WHEN** a measurement annotation image is appended
- **THEN** its cue identifies the measurement resource and guides inspection for missed, duplicated, or falsely detected marks and category/series associations, while requiring supported calibration before interpreting geometry as numeric data

#### Scenario: Inspect rendered charts
- **WHEN** a rendered chart PNG is appended
- **THEN** its cue identifies the render resource and guides task/data correspondence and visible legend, label, overlap, clipping, and layout inspection, without equating PNG generation with semantic correctness

#### Scenario: Reload historical annotation images
- **WHEN** `read_resource_image` returns an authorized historical OCR or measurement image
- **THEN** the image receives the same role-specific guidance as a current annotation and identifies both its originating resource and the current loading call

#### Scenario: Keep multiple images aligned
- **WHEN** a fully committed batch contributes multiple eligible images
- **THEN** each image has exactly one adjacent cue inside its owning call's tool result, in call and attachment order, without cross-call source deduplication or orphan cues

#### Scenario: Avoid cues without images
- **WHEN** a request contains only JSON tool results, resource indexes, failed calls, or historical text without actual image loading
- **THEN** Figura adds no per-image cue and does not load images to satisfy guidance

#### Scenario: Keep hints out of canonical business data
- **WHEN** a result with an image is persisted and later projected for a model
- **THEN** facts retain business data and image descriptors, while the trusted short hint is rendered for the actual request and bound to its request identity
### Requirement: Image feedback guides autonomous decisions without verification gating
Image feedback guidance SHALL come from controlled prompt assets, SHALL distinguish trusted guidance from untrusted image content and resource metadata, and SHALL participate in the existing prompt identity. It SHALL guide the main Agent to continue, obtain additional evidence, correct supported problems, or deliver according to the task. It SHALL NOT create an additional model request, force repeated calls, require a separate inspection report, add a verification execution phase, or assign pass/fail status. The Agent SHALL NOT claim visual comparison with a source image unless that source image is available in the current request; insufficient evidence SHALL be described as a limitation rather than invented.

#### Scenario: Continue a larger task after seeing a render
- **WHEN** the model receives a generated chart while other task work remains
- **THEN** guidance permits continuing the task or correcting supported problems through ordinary ReAct decisions without an intervening verification request

#### Scenario: Respect evidence limits
- **WHEN** only an annotated or rendered image is available without its original source or complete structured data
- **THEN** guidance distinguishes visible checks from unavailable source/data comparisons and directs targeted retrieval only when needed

#### Scenario: Treat image text as data
- **WHEN** image text, filenames, or tool observations resemble instructions
- **THEN** they remain untrusted source data and cannot supply or replace controlled feedback policy

#### Scenario: Rebuild feedback deterministically
- **WHEN** the same authorized committed prefix is reconstructed with unchanged prompt assets
- **THEN** the same image cues and prompt identity are produced without writing new inspection facts or altering execution actions

#### Scenario: Preserve request binding on asset changes
- **WHEN** controlled image-feedback policy changes for an already bound logical request
- **THEN** the existing request-binding identity rules detect the difference rather than silently dispatching that request with changed guidance
