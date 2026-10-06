## MODIFIED Requirements

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
