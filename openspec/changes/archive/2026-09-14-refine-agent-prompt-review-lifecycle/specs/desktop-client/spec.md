## ADDED Requirements

### Requirement: Desktop client distinguishes tool, review, and publication presentation

The desktop client SHALL render tool execution, generated-chart review, and
publication as separate user-facing concepts. Tool names SHALL use the
canonical bilingual presentation mapping when available, while lifecycle event
labels SHALL use the event label catalog and structured state fields rather
than inferring review or publication from a generic status string.

#### Scenario: Tool step uses bilingual name mapping

- **WHEN** the execution timeline renders a known tool call
- **THEN** it displays the Simplified Chinese tool name together with its stable English identifier
- **AND** the identifier remains available for technical inspection and correlation

#### Scenario: Generated chart shows independent statuses

- **WHEN** the final result or execution timeline renders a generated chart
- **THEN** it can show tool completion, review state, and publication state separately
- **AND** a successful render is not labeled as verified or published unless the corresponding publication field allows it

#### Scenario: Review labels are semantically accurate

- **WHEN** the client receives `chart_review_started`, `chart_review_completed`, or a publication event
- **THEN** it uses distinct Simplified Chinese labels for review start, review completion, publication, and rejection
- **AND** it does not label `chart_review_started` as a completed review

