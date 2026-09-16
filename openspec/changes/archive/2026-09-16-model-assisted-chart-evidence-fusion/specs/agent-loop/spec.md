## MODIFIED Requirements

### Requirement: Agent uses a static behavior prompt and review obligations

The Agent SHALL use one stable system prompt for the lifetime of a run. The
prompt SHALL define evidence discipline, model-led semantic interpretation,
adaptive tool-selection principles, generated chart review rules, and
final-answer boundaries without encoding a mutable analysis, generation, or
review phase. The prompt SHALL allow the model to use multimodal visual
understanding as a first-pass hypothesis, select OCR, geometry, or layout tools
for unresolved evidence, and request ChartSpec assembly when the evidence is
sufficient; it SHALL NOT prescribe `inspect_chart_layout` as a universal
precondition. When a generated chart creates a pending review obligation, the
model-visible context SHALL identify the candidate references and required next
action as bounded structured data.

#### Scenario: Ordinary turn uses the stable behavior contract

- **WHEN** the Agent requests a model turn before any generated chart review is
  pending
- **THEN** the model receives the configured system prompt and the normal
  registered tool surface
- **AND** the prompt explains that visual understanding is a hypothesis,
  auxiliary tool observations are attributable evidence, and tool success,
  review completion, and publication are distinct outcomes

#### Scenario: Model chooses targeted evidence

- **WHEN** a chart restoration turn contains uncertainty about text, geometry,
  orientation, or series association
- **THEN** the model can choose the corresponding OCR, chart sensor, or layout
  tool without following a fixed phase order
- **AND** the Agent keeps the resulting observations available for the next
  model turn

#### Scenario: Clear chart does not require layout preflight

- **WHEN** the model has sufficient multimodal evidence to construct a valid
  ChartSpec for a clear chart
- **THEN** it can request `assemble_spec` without first requesting
  `inspect_chart_layout`
- **AND** the Agent does not inject an implicit layout requirement that blocks
  the assembly

#### Scenario: Pending review is added as structured context

- **WHEN** a generated chart creates an unresolved review obligation
- **THEN** the next model-visible observation includes the candidate ID, review
  ID, candidate status, review status, publication status, and required review
  action
- **AND** the Agent does not replace the stable system prompt with a
  phase-specific prompt
