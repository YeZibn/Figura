## MODIFIED Requirements

### Requirement: Whole-image text extraction tool

The system SHALL provide an `extract_text` sensor that runs deterministic OCR
on a whole local image and returns every detected text snippet with its bounding
box and a confidence score. In the Agent tool registry, the sensor SHALL accept
an attachment ID resolved through the active session's authorized attachment
boundary and SHALL take no region arguments. The direct Python sensor MAY retain
a path-based compatibility entry. The sensor SHALL also produce a generated
overlay image identifying detected text regions for multimodal inspection.

#### Scenario: Annotations and labels are returned with visual evidence

- **WHEN** `extract_text` is called with an authorized synthetic bar-chart
  attachment whose value annotations are known
- **THEN** the result contains one entry per printed text with `text`, `bbox`
  (`[x, y, width, height]`), and `confidence` in `[0, 1]`
- **AND** the value annotations appear as their exact printed strings
- **AND** a generated overlay with the source image dimensions visibly marks
  and identifies each returned text region

#### Scenario: Unavailable attachment reports a structured error

- **WHEN** the registered tool receives an unknown, unauthorized, missing, or
  changed attachment
- **THEN** the tool returns a bounded structured error without revealing another
  session's path and never raises an uncaught exception into the agent loop
- **AND** the tool produces no visual artifact

#### Scenario: No detected text still produces inspectable evidence

- **WHEN** OCR completes successfully but detects no text
- **THEN** the structured result is empty and the generated overlay preserves
  the source image so the model can inspect the absence of detections

### Requirement: Bar geometry measurement tool

The system SHALL provide a `measure_bars` sensor that deterministically detects
bars in a clean bar-chart image and returns, per bar, its bounding box, pixel
height, stable visual identifier, and height ratio normalized to the shortest
bar. In the Agent tool registry, the sensor SHALL accept an authorized
attachment ID; its direct Python entry MAY retain path-based compatibility. It
SHALL also produce an overlay marking every returned bar and the baseline.

#### Scenario: Bar ratios and overlay track the detected bars

- **WHEN** `measure_bars` is called with an authorized synthetic bar-chart
  attachment whose values are known
- **THEN** the number of detected bars equals the true count
- **AND** each bar's height ratio equals the true value ratio within 10%
  relative tolerance
- **AND** a generated overlay with the source image dimensions visibly marks
  every returned bar, its identifier, and the detected baseline

#### Scenario: Non-chart image remains inspectable

- **WHEN** `measure_bars` is called with an authorized image containing no
  detectable bars
- **THEN** the tool returns an empty bars list rather than an error so the Agent
  can observe no bars found and re-plan
- **AND** the generated overlay preserves the source image and indicates that
  no baseline or bars were detected

#### Scenario: Unavailable attachment reports a structured error

- **WHEN** the registered tool receives an unknown, unauthorized, missing, or
  changed attachment
- **THEN** the tool returns a bounded structured error, produces no visual
  artifact, and never raises an uncaught exception into the agent loop

### Requirement: U0 end-to-end restoration through the ReAct loop

The system SHALL enable the Agent, given a clean annotated bar chart registered
through the normal attachment path and the registered chart tools, to produce a
ChartSpec whose dataset matches the chart's true values. The authorized
attachment ID needed by image tools SHALL be available without exposing or
repeating its local path. The infrastructure MUST NOT force a fixed tool
sequence, force an image load, or require ChartSpec output for every image turn.

#### Scenario: Freely planned annotated bar-chart restoration

- **WHEN** the user registers a synthetic bar chart through the standard Agent
  REPL and asks for its underlying data
- **THEN** the Agent can choose when to load the image and call relevant sensors,
  assembly, and validation tools without a caller-supplied workflow prompt
- **AND** the dataset values equal the ground-truth values used to draw the chart

#### Scenario: Image question does not require restoration

- **WHEN** the user asks a descriptive question that does not require
  structured chart data
- **THEN** the Agent can answer without assembling or validating a ChartSpec

#### Scenario: OCR misread is caught by geometric cross-check

- **WHEN** the Agent uses annotation values and bar-height ratios and those
  evidence channels disagree beyond tolerance
- **THEN** the Agent re-examines the evidence before assembling, and the final
  spec uses the values consistent with bar geometry
