## ADDED Requirements

### Requirement: Agent follows a task-directed evidence workflow
The stable Chinese Agent instructions SHALL guide the model to identify the user's chart-related goal, select only the observations needed to meet that goal, and base conclusions and generated chart data on available evidence. They SHALL distinguish explanation, data extraction, chart reconstruction, visualization of user-provided data, composition, and modification of an existing result without forcing every task through the same tool sequence. They SHALL make the current tool Schema authoritative for tool parameters and ChartSpec structure.

The instructions SHALL explain the limits of resource metadata, loaded image blocks, OCR, measurement results, assembled Figures, and rendered images. They SHALL distinguish tool execution outcome from result status and availability; preserve unknown or missing values; and avoid presenting pixel geometry, OCR candidates, partial observations, or low-confidence associations as certain business facts.

When selecting image regions, the instructions SHALL tell the model to preserve the chart geometry, ticks, category labels, and legends needed by the task, and to use the coordinate shape and coordinate system required by the selected tool. When building ChartSpec content, they SHALL require the model to preserve supported data semantics, use only evidence-backed values and references, and respond to validation errors by correcting the indicated content rather than inventing missing data.

The instructions SHALL describe the available image feedback accurately: an observation or render image is visible when supplied in the current request; historical text results and resource summaries do not imply that historical pixels are currently visible. After rendering, the model SHALL inspect the returned image when it is available, make only evidence-based corrections, and distinguish successful assembly or PNG generation from semantic correctness or system review. The instructions SHALL leave the final response accurate about evidence, uncertainty, and unresolved limitations.

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
