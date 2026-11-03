## ADDED Requirements

### Requirement: Retrieval guidance distinguishes summary and resource references
Model-visible retrieval guidance SHALL distinguish `source_refs` in a compacted context summary from typed `ref` values in the current resource catalog. When the current request requires exact structured content from a listed OCR, measurement, or ChartFigure resource, the Agent SHALL copy that resource entry's complete typed reference unchanged into `read_history` and SHALL use it before searching or reading a different source reference. Summary `source_refs` SHALL remain available for retrieving the original supporting message or tool result when that source itself is relevant. The Agent SHALL use `search_history` to locate a resource or history source when no matching reference is present in the current catalog or summary.

#### Scenario: Prefer a listed typed resource over its summary provenance
- **WHEN** a compacted summary and the current resource catalog both identify the same OCR, measurement, or ChartFigure, but the summary cites a message or tool result
- **THEN** guidance directs the Agent to copy the matching typed resource `ref` into `read_history` for exact structured content

#### Scenario: Search when the resource is not in the current catalog
- **WHEN** the Agent needs an older structured resource that has no matching typed reference in the current resource catalog or summary
- **THEN** guidance directs it to search the authorized history and read the exact reference returned by search

#### Scenario: Read the original source behind a summary
- **WHEN** the Agent needs the original user message or tool-result record supporting a summary item rather than the structured resource itself
- **THEN** guidance directs it to use that summary item's `source_refs` with `read_history`

### Requirement: Selector guidance uses known paths and a safe full-read fallback
Model-visible `read_history` guidance SHALL explain that selector paths are relative to the referenced source's returned `content`, and that omitting `selector` reads the complete source. Guidance SHALL provide the known typed-resource paths `/result/snippets` for OCR snippets, `/result/warnings` for measurement warnings, and `/figure` for a complete ChartFigure. When the desired path is not known, the Agent SHALL omit `selector` rather than guess a path. If a field-selected read using a reference copied from the current resource catalog fails, the Agent SHALL retry once with the same reference and no selector before searching for an alternate source.

#### Scenario: Select a known OCR field
- **WHEN** the Agent needs only OCR text snippets from a typed OCR resource
- **THEN** guidance identifies `/result/snippets` as the content-relative path, with array ranges applied after field selection when needed

#### Scenario: Select a known measurement field
- **WHEN** the Agent needs only warning text from a typed measurement resource
- **THEN** guidance identifies `/result/warnings` as the content-relative path

#### Scenario: Read a ChartFigure or unknown path
- **WHEN** the Agent needs a complete ChartFigure or cannot determine a content-relative path
- **THEN** guidance identifies `/figure` for ChartFigure and otherwise directs the Agent to omit `selector` to read the complete source

#### Scenario: Recover from a failed selector path
- **WHEN** a `read_history` call using a listed typed resource reference and a field selector fails
- **THEN** the Agent retries once with the same reference and no selector before searching for another source
