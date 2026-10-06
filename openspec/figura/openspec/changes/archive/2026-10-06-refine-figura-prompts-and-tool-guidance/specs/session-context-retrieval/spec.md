## ADDED Requirements

### Requirement: Retrieval guidance describes exact search and selection behavior
Model-visible retrieval guidance SHALL identify search as case-insensitive textual matching of the complete query or all whitespace-separated query terms, without promising semantic search. It SHALL explain Run and source-kind filters, short excerpts, continued pages, and reuse of a cursor with its original query and filters. It SHALL explain that no match does not prove no relevant history exists. Read guidance SHALL describe complete canonical messages, tool results or errors, unresolved call states, and structured resource content including complete accepted Figures. Optional field selectors SHALL be described as JSON Pointers relative to returned `content`; optional range selectors SHALL use zero-based start-inclusive/end-exclusive string or array slicing after field selection. Reads SHALL remain source-authorized and SHALL NOT rerun tools or load image pixels implicitly.

#### Scenario: Search with practical query terms
- **WHEN** the Agent needs an old resource or decision whose exact phrase is uncertain
- **THEN** guidance directs it to use identifying keywords, names or IDs and refine a failed query without claiming semantic matching or historical absence

#### Scenario: Continue a filtered search
- **WHEN** a search page contains a continuation cursor
- **THEN** guidance requires the next page to reuse that cursor with the same query and filters and identify further matches through their original references

#### Scenario: Read an existing Figure for modification
- **WHEN** the Agent has an authorized `chart_figure` resource reference
- **THEN** read guidance explains how to retrieve the complete structured Figure, including selection at `/figure`, before submitting a new full assembly

#### Scenario: Select only part of a historical result
- **WHEN** the Agent needs a field or slice instead of the complete source
- **THEN** guidance makes the field path relative to `content` and the range relative to the selected string or array, without suggesting object slicing

## MODIFIED Requirements

### Requirement: Read authorized historical images through typed resource references
Figura SHALL let the Agent request visual content by an authorized typed resource reference for an Attachment, Panel, successful OCR or measurement observation, or successful ChartRender. The image-read native input Schema SHALL accept only `attachment`, `panel`, `ocr`, `measurement`, and `chart_render` references with their exact typed identities. It SHALL exclude `message`, `tool_result`, and `chart_figure` references; text and structured content SHALL remain readable through the historical content reader. It SHALL use the existing integrity and Session ownership checks, return image content through the Provider's image-input path, and SHALL NOT implicitly rerun OCR, measurement, decomposition, Figure assembly, or rendering. A ChartFigure without a successful render SHALL require an explicit render action; an already rendered Figure SHALL be read visually using its separate ChartRender reference. Failed and unresolved resources SHALL not produce an image.

#### Scenario: Read a prior Attachment or Panel image
- **WHEN** the Agent requests an Attachment or Panel reference present in the authorized resource catalog
- **THEN** Figura validates the owning Session and returns the image to the next Provider request

#### Scenario: Read a prior observation or render image
- **WHEN** the Agent requests a successful OCR or measurement annotation, or a successful ChartRender reference
- **THEN** Figura reconstructs or resolves the image and verifies it against the committed source result before returning it

#### Scenario: Require an explicit render for a Figure
- **WHEN** the Agent submits a ChartFigure reference to the image reader instead of an accepted image resource reference
- **THEN** the native input contract rejects it and guidance directs the Agent to explicitly render the Figure or read an existing ChartRender reference without rendering implicitly

#### Scenario: Reject unauthorized, failed, or corrupt image content
- **WHEN** a reference is cross-Session, outside the authorized Run prefix, failed, missing, or inconsistent with committed metadata
- **THEN** Figura returns no image bytes and reports a bounded failure

#### Scenario: Reject a nonvisual history reference before image dispatch
- **WHEN** the Agent supplies a message or tool-result reference to the image tool
- **THEN** native argument validation rejects the reference before its image handler runs and the historical content reader remains available for that reference
