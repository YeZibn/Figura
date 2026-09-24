## MODIFIED Requirements

### Requirement: Evaluation run transcript matches ordinary session trace

The evaluation workspace SHALL render a selected case as a read-only equivalent of the ordinary session user-facing timeline. It SHALL use the same tool-call/result correlation, expandable result behavior, visual-observation attachment behavior, domain-step labels, terminal/error presentation, and technical-lifecycle filtering, while preserving evaluation-specific case, report, and evidence context. Model-start, model-completion, and operation-save events SHALL remain available as persisted history but SHALL NOT be rendered as separate visible transcript rows.

#### Scenario: User reviews a selected case like a normal conversation run

- **WHEN** the user opens a case with a persisted run
- **THEN** the evaluation workspace shows the same flat chronological timeline used by an ordinary run
- **AND** tool calls, tool results, observations, repair events, review events, and terminal events appear in their original meaningful order

#### Scenario: Evaluation hides technical lifecycle noise

- **WHEN** a case history contains model-start, model-completion, or operation-save events
- **THEN** the case timeline does not create separate cards or rows for those events
- **AND** their failure context, when relevant, is surfaced through the associated visible error or terminal step

#### Scenario: Evaluation transcript remains read-only

- **WHEN** the user expands or refreshes an evaluation transcript
- **THEN** the client never submits a new model/tool operation or mutates the evaluation bundle
- **AND** the ordinary session workspace retains its existing run, retry, resume, and interruption behavior
