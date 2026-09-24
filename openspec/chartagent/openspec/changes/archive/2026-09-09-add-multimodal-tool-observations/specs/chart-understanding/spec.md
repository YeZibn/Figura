## MODIFIED Requirements

### Requirement: Whole-image text extraction tool

The system SHALL provide an `extract_text` tool that runs deterministic OCR on
a whole local image and returns every detected text snippet with its bounding
box and confidence score. The tool takes no region arguments and SHALL also
produce a generated overlay image that identifies the detected text regions so
the multimodal model can inspect their placement.

#### Scenario: Annotations and labels are returned with visual evidence

- **WHEN** `extract_text` is called with a synthetic bar chart image whose value
  annotations are known
- **THEN** the structured result contains one entry per printed text with
  `text`, `bbox` (`[x, y, width, height]`), and `confidence` in `[0, 1]`
- **AND** the value annotations appear as their exact printed strings
- **AND** a generated overlay with the source image dimensions visibly marks
  and identifies each returned text region

#### Scenario: Unreadable image reports a structured error

- **WHEN** `extract_text` is called with a path that does not exist
- **THEN** the tool returns `{"error": ...}` naming the path, produces no
  visual artifact, and never raises an uncaught exception into the agent loop

#### Scenario: No detected text still produces inspectable evidence

- **WHEN** OCR completes successfully but detects no text
- **THEN** the structured result is empty and the generated overlay preserves
  the source image so the model can inspect the absence of detections

### Requirement: Bar geometry measurement tool

The system SHALL provide a `measure_bars` tool that deterministically detects
bars in a clean bar-chart image and returns, per bar, its bounding box, stable
visual identifier, pixel height, and height ratio normalized to the shortest
bar. It SHALL also produce a generated overlay that marks each returned bar and
the detected baseline using the same identifiers as the structured result.

#### Scenario: Bar ratios and overlay track the detected bars

- **WHEN** `measure_bars` is called with a synthetic bar chart whose values are known
- **THEN** the number of detected bars equals the true count
- **AND** each bar's height ratio equals the true value ratio within 10%
  relative tolerance
- **AND** a generated overlay with the source image dimensions visibly marks
  every returned bar, its identifier, and the detected baseline

#### Scenario: Non-chart image remains inspectable

- **WHEN** `measure_bars` is called with an image containing no detectable bars
- **THEN** the structured result contains an empty bars list rather than an error
- **AND** the generated overlay preserves the source image and indicates that
  no baseline or bars were detected, so the agent can observe and re-plan

#### Scenario: Missing image reports a structured error

- **WHEN** `measure_bars` is called with a path that does not exist
- **THEN** the tool returns `{"error": ...}` naming the path, produces no
  visual artifact, and never raises an uncaught exception into the agent loop
