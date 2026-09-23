## MODIFIED Requirements

### Requirement: Desktop client distinguishes tool, review, and publication presentation

The desktop client SHALL render tool execution, generated-chart review, and
publication as separate user-facing concepts. Tool names SHALL use the
canonical bilingual presentation mapping when available, while lifecycle event
labels SHALL use the event label catalog and structured state fields rather
than inferring review or publication from a generic status string.

#### Scenario: Tool step uses bilingual name mapping

- **WHEN** the execution timeline renders a known tool call
- **THEN** it displays the Simplified Chinese tool name together with its stable
  English identifier
- **AND** the identifier remains available for technical inspection and
  correlation

#### Scenario: Assembly and rendering have distinct tool headlines

- **WHEN** the execution timeline contains a ChartSpec assembly step and a
  chart rendering step
- **THEN** their headlines identify the respective tools as
  `组装图表规格 (assemble_spec)` and `生成图表 (render_chart)`
- **AND** a broad phase or unit category does not replace the specific tool
  name

#### Scenario: Unknown tool state is not inferred as success

- **WHEN** a tool result omits its status or supplies an unrecognized status
- **THEN** the timeline displays an explicit localized unknown state
- **AND** it does not label the tool as completed, the review as passed, or the
  chart as published based only on that result

#### Scenario: Generated chart shows independent statuses

- **WHEN** the final result or execution timeline renders a generated chart
- **THEN** it can show tool completion, review state, and publication state
  separately
- **AND** a successful render is not labeled as verified or published unless
  the corresponding publication field allows it

#### Scenario: Review labels are semantically accurate

- **WHEN** the client receives `chart_review_started`,
  `chart_review_completed`, or a publication event
- **THEN** it uses distinct Simplified Chinese labels for review start, review
  completion, publication, and rejection
- **AND** it does not label `chart_review_started` as a completed review

#### Scenario: Generated chart survives an ordinary reload

- **WHEN** the user reopens a session containing a generated chart within the
  configured retention policy
- **THEN** the run history restores its metadata and the preview or download
  action can request the authorized artifact again

#### Scenario: Generated chart is unavailable

- **WHEN** the artifact is expired, missing, unauthorized, or the run reports a
  rendering failure
- **THEN** the workspace shows an explicit bounded unavailable or failed state
- **AND** it does not render a broken image or claim that generation succeeded

### Requirement: User can inspect persisted Agent runs

The desktop workspace SHALL display each Agent run as a compact execution
group with its status, timestamps when available, and expand/collapse control.
Inside the group it SHALL render a chronological user-facing timeline
containing meaningful tool, observation, measurement, generation, review,
recovery, and failure steps. A tool call and its result SHALL be represented as
one logical step, while model-start, model-completion, operation-save, run-start,
and resume-start lifecycle events SHALL remain available in the persisted
history but SHALL NOT appear as ordinary visible timeline rows. A bounded or
truncated tool result SHALL remain part of the corresponding tool step and
SHALL NOT become an unknown standalone step when the outer tool identity is
available. Tool arguments, full results, and technical event details SHALL be
collapsed by default regardless of the tool step's running or terminal status;
the collapsed summary SHALL retain the tool name, timestamp, localized status,
and any necessary bounded failure reason. Users SHALL be able to expand the
step to inspect its bounded details.

#### Scenario: Completed run remains visible after reload

- **WHEN** the user reloads a session containing completed runs
- **THEN** the client restores their run summaries and can expand each one to
  inspect its persisted user-facing timeline

#### Scenario: Tool status is correlated

- **WHEN** a tool call and its result share a call identifier
- **THEN** the UI shows one logical tool step whose status changes from running
  to success or failure
- **AND** its arguments, bounded result, and visual evidence are available
  behind the step disclosure control

#### Scenario: Tool details start collapsed without hiding the summary

- **WHEN** a tool step is displayed while running, completed, blocked, or failed
- **THEN** its arguments, full result, and technical event details are initially
  collapsed
- **AND** its name, timestamp, localized status, and necessary bounded failure
  reason remain visible
- **AND** an available generated chart remains visible in the separate result
  area

#### Scenario: Technical lifecycle events stay hidden

- **WHEN** a run history contains model-start, model-completion, or operation-save
  events
- **THEN** the ordinary timeline does not render separate rows or cards for
  those events
- **AND** the run status, tool steps, domain milestones, and terminal error
  remain understandable without opening raw history

#### Scenario: Truncated result remains in its tool step

- **WHEN** the Gateway marks a tool result body as truncated but preserves the
  originating tool name and call identifier
- **THEN** the UI keeps the result under the originating tool step
- **AND** it shows an explicit bounded or truncated-state indicator
- **AND** it does not render a separate “unknown tool” step

#### Scenario: Legacy or incomplete history is explicit

- **WHEN** a run has no recoverable events, has an event-history gap, or was
  interrupted by a Gateway restart
- **THEN** the UI shows an explicit unavailable, incomplete, or interrupted
  state
- **AND** it does not fabricate missing execution steps or expose a technical
  lifecycle bucket as the main user-facing process
