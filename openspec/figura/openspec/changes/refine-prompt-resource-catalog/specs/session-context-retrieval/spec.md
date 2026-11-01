## ADDED Requirements

### Requirement: Resource summaries guide exact content retrieval
The Agent SHALL be able to use an OCR or measurement reference shown in the Prompt resource catalog with the existing `read_history` tool to retrieve the complete committed resource or a selected field or range. The tool SHALL preserve the reference's originating Run and call identity, enforce the existing same-Session authorized Run prefix, return historical content as untrusted data, and SHALL NOT rerun the OCR or measurement operation. The Prompt guidance SHALL explain when the compact summary is sufficient and when exact source content must be read.

#### Scenario: Read exact OCR snippets after inspecting a summary
- **WHEN** an Agent needs text, pixel bounds, or confidence values omitted from an OCR summary
- **THEN** it can call `read_history` with the OCR typed reference and receive the complete OCR result or a requested field/range

#### Scenario: Read exact measurement evidence after inspecting a summary
- **WHEN** an Agent needs coordinates, values, calibration parameters, issues, or value provenance omitted from a measurement summary
- **THEN** it can call `read_history` with the measurement typed reference and receive the complete committed result or a requested field/range

#### Scenario: Preserve authorization and read-only behavior
- **WHEN** a resource reference is outside the calling Run's authorized same-Session prefix or malformed
- **THEN** retrieval returns the existing bounded unavailable-reference error and does not expose or modify another resource

#### Scenario: Do not rerun a historical observation
- **WHEN** the Agent reads an OCR or measurement resource by reference
- **THEN** Figura returns the committed content and does not invoke OCR, measurement, or annotation generation again
