# session-context-retrieval Specification

## Purpose

Lets the Agent locate and read older Session content on demand from its original committed Run facts, without placing all historical messages, tool results, or images in every model request.

## Requirements

### Requirement: Search returns source-addressable history matches
Figura SHALL provide a read-only Agent capability to search eligible conversation messages, committed tool results, Run outcome context, and authorized resource metadata in the calling Session. The calling Session and authorized Run prefix SHALL be derived from execution context rather than accepted as model-selected scope. Each match SHALL include a stable source reference, Run identity and ordinal, source kind and role or tool name, outcome state when applicable, and a short identifying excerpt or resource description. Search results SHALL support continuation so additional matches can be read without silently omitting the remaining results. Search SHALL not execute historical tools or create a second authoritative history store.

#### Scenario: Find an earlier decision by text query
- **WHEN** the Agent searches for a topic present in an earlier committed user or assistant message
- **THEN** Figura returns the matching message's stable source reference and a short excerpt from that canonical record

#### Scenario: Find a committed tool observation
- **WHEN** the Agent searches for a prior OCR, measurement, Figure, render, or other committed tool result
- **THEN** Figura returns the exact source reference and the committed outcome state without recomputing the tool

#### Scenario: Find an older image resource by metadata
- **WHEN** the Agent searches for an eligible Attachment, Panel, or other visual resource that is not in the prompt locator projection
- **THEN** Figura returns its typed reference and safe identifying metadata for a later explicit image read

#### Scenario: Continue through multiple matches
- **WHEN** more matches exist than are included in the current search page
- **THEN** Figura provides a continuation cursor and the next search returns subsequent matches without losing their source references

#### Scenario: Exclude later Runs and other Sessions
- **WHEN** a search is made from a target Run and the store contains later Runs or other Sessions
- **THEN** no content outside the target Run's authorized same-Session prefix is returned

### Requirement: Read resolves a stable reference to its original content
Figura SHALL provide a read-only Agent capability to resolve a conversation-message reference to the complete original message and a tool-resource reference to its complete committed typed result or structured error. Reads SHALL include enough source metadata to preserve Run, record or tool-call identity, ordering, and outcome semantics. A read SHALL NOT rerun the historical tool, invent missing results, or modify the source Run. Callers MAY request a field or range when they need only part of a large source; absent a selector, the selected source item SHALL be returned completely, subject only to existing payload and Provider protocol rules.

#### Scenario: Read an exact historical message
- **WHEN** the Agent reads a valid message reference from search results or a summary
- **THEN** Figura returns the original committed message content and its source identity

#### Scenario: Read a complete tool result
- **WHEN** the Agent reads a valid tool-resource reference
- **THEN** Figura returns the complete committed typed content or structured error associated with that exact Run and call

#### Scenario: Read an unresolved call
- **WHEN** a referenced historical call has no committed result and its outcome is unknown
- **THEN** Figura returns the source-linked unknown status and no fabricated observation

#### Scenario: Reject an unavailable reference
- **WHEN** the requested reference is malformed, outside the authorized prefix, or absent
- **THEN** Figura returns a bounded not-found or not-readable result without revealing another Session's content

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

### Requirement: Historical content remains untrusted and read-only
Search and read SHALL expose historical user content, assistant content, OCR text, tool data, and generated summaries as untrusted data. These capabilities SHALL not permit historical content to change system instructions, tool policy, current Session ownership, or current Run state. Reads SHALL be side-effect free with respect to the source facts, while the current retrieval action remains auditable through the normal current-Run execution lifecycle.

#### Scenario: Ignore instructions embedded in retrieved content
- **WHEN** retrieved historical content contains text that resembles system or tool instructions
- **THEN** Figura identifies it as source data and does not elevate its authority

#### Scenario: Keep retrieval read-only
- **WHEN** the Agent searches or reads an earlier message, tool result, or image
- **THEN** the referenced Run facts and resources remain unchanged and historical tools are not re-executed

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
