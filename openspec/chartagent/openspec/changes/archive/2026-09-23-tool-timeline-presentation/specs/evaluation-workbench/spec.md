## ADDED Requirements

### Requirement: Evaluation tool steps use the shared default-collapsed presentation

The evaluation workbench SHALL present persisted tool steps using the same
canonical bilingual tool names, localized status semantics, and default
collapsed detail behavior as ordinary run timelines. Evaluation-specific
presentation MUST NOT independently infer tool completion, review success, or
chart publication from an unknown tool result status.

#### Scenario: Evaluation tool details are opt-in

- **WHEN** a persisted evaluation run contains a tool call and result
- **THEN** the unified timeline initially shows one collapsed tool step with
  its bilingual name, timestamp, localized status, and necessary bounded
  failure reason
- **AND** expanding the step reveals the available bounded arguments, result,
  and visual evidence without re-running the tool
- **AND** an available generated chart remains visible in the separate result
  area
