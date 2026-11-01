## ADDED Requirements

### Requirement: Prompt resource catalog provides compact, decision-useful summaries
The Agent SHALL project OCR and measurement resources into the Prompt catalog as compact summaries with their complete typed resource references. OCR summaries SHALL include source reference, scope kind, outcome, availability, truncation state, snippet count, and a bounded text preview. Measurement summaries SHALL include source reference, scope kind, outcome, chart type and status when available, committed structure status and detected counts, confidence, calibration counts, issue and warning counts, and bounded issue-code and warning previews. Failed resources SHALL expose their safe structured error without success-only fields. The projection SHALL NOT include the complete OCR snippets, measurement observations, evidence, calibrations, value provenance, image bytes, or local paths.

The summary SHALL be derived deterministically from the complete committed resource. Detected counts SHALL be copied from the committed measurement coverage rather than recomputed. Any preview omission or text shortening SHALL be marked separately from the source result's own truncation state. The Prompt SHALL direct the Agent to use the listed reference with `read_history` when exact text, coordinates, values, or evidence are needed. The full resource lookup and `RunExecutionState` SHALL continue to expose the complete committed content.

#### Scenario: Locate relevant OCR text from its summary
- **WHEN** a successful OCR resource contains text snippets
- **THEN** the Prompt catalog includes its typed reference, source, scope kind, availability, source truncation state, snippet count, and a bounded preview, with no full snippet coordinates or confidence values

#### Scenario: Preserve complete OCR content for explicit reading
- **WHEN** the Agent follows an OCR catalog reference with `read_history`
- **THEN** Figura returns the complete committed OCR content or the requested selector while the catalog itself remains compact

#### Scenario: Summarize measurement quality without changing evidence
- **WHEN** a successful measurement resource has coverage, confidence, calibrations, issues, warnings, and family observations
- **THEN** the Prompt catalog exposes the committed coverage counts and compact quality metadata without embedding the family observations, evidence, calibration parameters, or value provenance

#### Scenario: Distinguish preview omission from source truncation
- **WHEN** an OCR or measurement summary omits entries or shortens preview text
- **THEN** its summary preview state reports that omission separately and preserves the source result's original `truncated` value

#### Scenario: Keep failed resource summaries truthful
- **WHEN** an OCR or measurement call has a committed failure
- **THEN** the Prompt catalog exposes its typed reference, outcome, and safe structured error without manufacturing success metadata

#### Scenario: Rebuild the compact catalog from full resources
- **WHEN** a later Run reconstructs a supported resource from committed Runtime facts
- **THEN** the typed resource retains its complete content and the Prompt catalog derives the same bounded summary without adding a separate durable store
