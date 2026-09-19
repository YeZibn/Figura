## MODIFIED Requirements

### Requirement: Agent uses a layered behavior prompt and automatic review obligations

The Agent SHALL assemble a stable static responsibility layer together with a
runtime-derived tool surface, attributable process artifacts, and dynamic
Run/Turn state. The static layer SHALL define evidence discipline,
model-led semantic interpretation, adaptive tool-selection principles, atomic
ChartSpec assembly and validation, generated chart review rules, and
final-answer boundaries without encoding mutable analysis, generation, or
review state. The dynamic layers SHALL identify the current source, panel,
available tools, produced observations or candidates, publication state, and
bounded next action. The Agent SHALL allow the model to use multimodal visual
understanding as a first-pass hypothesis, select OCR, geometry, or layout tools
for unresolved source evidence, and use `assemble_spec` as the
model-facing construction-and-validation gate when a structured ChartSpec is
needed; it SHALL NOT require a separate `validate_spec` tool call, prescribe
`inspect_chart_layout` as a universal precondition, or ask the model to call a
chart-review tool. When a generated chart creates an automatic review
obligation, the model-visible dynamic context SHALL identify candidate
references, review result, publication state, and bounded required next action
as structured data. The prompt SHALL describe normalized review fields
(`decision`, `confidence`, `checks`, and `issues`) as system-provided evidence
to consume, not as a JSON decision that the main Agent may generate or
override.

#### Scenario: Ordinary turn uses the layered behavior contract

- **WHEN** the Agent requests a model turn before any generated chart review is pending
- **THEN** the model receives the static responsibility layer, the current registered tool surface, and the current Run/Turn context
- **AND** the context explains that visual understanding is a hypothesis, auxiliary tool observations are attributable evidence, `assemble_spec` performs the construction-and-validation gate, and tool success, review completion, and publication are distinct outcomes

#### Scenario: Model chooses targeted evidence

- **WHEN** a chart restoration turn contains uncertainty about text, geometry, orientation, or series association
- **THEN** the model can choose the corresponding OCR, chart sensor, or layout tool without following a fixed phase order
- **AND** the Agent keeps the resulting observations available as attributable process artifacts for the next model turn

#### Scenario: Clear chart does not require layout preflight

- **WHEN** the model has sufficient multimodal evidence to construct a valid ChartSpec for a clear chart
- **THEN** it can request `assemble_spec` without first requesting `inspect_chart_layout`
- **AND** the Agent does not inject an implicit layout requirement that blocks the assembly

#### Scenario: Structured output uses the atomic assembly gate

- **WHEN** the model has gathered enough evidence to return structured chart data or invoke `render_chart`
- **THEN** it requests `assemble_spec` before that downstream action
- **AND** a successful assembly is the only model-facing construction and validation step required for the ChartSpec
- **AND** an assembly error causes the model to revise, re-observe, or reassemble instead of returning or rendering the invalid candidate

#### Scenario: Runtime context exposes existing panel reuse

- **WHEN** a named session already contains a valid panel handoff for the current source
- **THEN** the next model turn receives the panel inventory and can use the stable `panel_id`
- **AND** the Agent does not require the model to rediscover the panel from incomplete prior history

#### Scenario: Pending review is added as dynamic context

- **WHEN** a generated chart creates an unresolved review obligation
- **THEN** the next model-visible context includes the candidate ID, review ID, candidate status, review status, publication status, and required review action
- **AND** the Agent does not replace the static responsibility layer with a phase-specific system prompt

#### Scenario: Publication state controls the final claim

- **WHEN** the model prepares a final response after a generated chart candidate has been reviewed
- **THEN** it may call the chart published only when `publicationStatus` is `published` or `published_with_warning`
- **AND** it preserves the warning for `published_with_warning`
- **AND** it describes pending, rejected, failed, timed-out, or retry-exhausted candidates as not published

#### Scenario: Source evidence scope is explicit

- **WHEN** a source-linked candidate lacks authorized source evidence
- **THEN** the Agent does not claim that source-fidelity review completed
- **AND** a direct-data candidate without a source-fidelity obligation is not described as equivalent to a source image
