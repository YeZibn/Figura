## MODIFIED Requirements

### Requirement: Bound OCR output and preserve source coordinates
Figura SHALL assign snippet IDs unique within a result, retain recognized text up to the declared per-snippet bound and set truncated when snippet count or text length is cut off. All boxes SHALL remain integer pixels in the complete selected source frame, regardless of observation scope.

The business result SHALL contain only the existing OCR observation fields, without image bytes, overlay pixels, local paths or unbounded OCR data. Each new successful OCR call SHALL additionally provide one validated saved ocr_annotation attachment in its outer tool-result envelope, pointing to that OCR call's resource. Empty or unavailable OCR observations SHALL retain their existing available/snippets semantics and SHALL NOT imply successful recognition merely because an annotation image exists. Image preparation failures SHALL follow the unified tool-error contract before success publication.

#### Scenario: Truncate excessive OCR output
- **WHEN** OCR produces more than 512 snippets or a text snippet longer than 128 characters
- **THEN** Figura returns no more than 512 snippets, limits each text value to 128 characters, and sets `truncated: true`

#### Scenario: Keep OCR boxes in selected-source coordinates
- **WHEN** OCR runs on a Panel or on a scoped portion of an Attachment
- **THEN** every `bbox_px` remains relative to the complete selected Panel or Attachment image

#### Scenario: Keep image payloads outside the OCR result
- **WHEN** the OCR tool returns a result
- **THEN** the durable business result contains the existing snippet observation fields, the outer envelope contains only the annotation descriptor, and neither contains image bytes, overlay pixels or local paths

#### Scenario: Deliver a saved annotation without changing OCR business fields
- **WHEN** an OCR call completes and its annotation is saved and validated
- **THEN** the business result preserves its existing schema and the outer tool result supplies the annotation descriptor for multimodal delivery
