## ADDED Requirements

### Requirement: Common chart observation envelope

The bar, line, scatter, and pie observation tools SHALL expose a common
evidence envelope alongside their chart-specific measurements. The envelope
SHALL contain source-image size, a coordinate-system-aware frame, legend and
series association evidence when available, bounded confidence, and
warnings. Source-image geometry SHALL use one coordinate convention across
all four tools. Missing or ambiguous evidence SHALL remain null, partial, or
uncertain rather than being fabricated.

The envelope SHALL distinguish common evidence from chart-specific geometry.
Bar geometry, line traces, scatter markers, and pie sectors MAY retain their
specialized fields, but those fields SHALL reference stable evidence and
series identifiers from the common envelope when applicable.

#### Scenario: All supported chart tools expose common evidence

- **WHEN** the Agent invokes a successful bar, line, scatter, or pie
  observation tool
- **THEN** the result contains the common source-image, frame, association,
  confidence, and warning evidence
- **AND** the result retains the chart-specific measurements needed for the
  corresponding chart type
- **AND** the result remains valid JSON suitable for another Agent action

#### Scenario: Partial common evidence remains inspectable

- **WHEN** a chart has detectable geometry but its frame, legend, OCR, or
  series association is incomplete
- **THEN** the result preserves the reliable chart-specific geometry
- **AND** the missing evidence is represented as null, partial, or uncertain
- **AND** the result reports the affected uncertainty in warnings or confidence

#### Scenario: Source geometry is consistent across chart types

- **WHEN** a supported chart is translated, resized, or subjected to a
  supported flat-image rotation
- **THEN** all serialized points, lines, polygons, frames, and labels remain
  in the original source-image coordinate system
- **AND** the generated visual evidence uses the same coordinates

### Requirement: Coordinate models are pluggable and explicit

The observation infrastructure SHALL represent the coordinate model used by a
chart explicitly without forcing every chart into one coordinate system.
Bar, line, and scatter observations SHALL use a Cartesian two-dimensional
model when their axes are supported. Pie observations SHALL use a polar
two-dimensional model with circular or angular evidence. A result with no
reliable coordinate model SHALL remain inspectable with pixel geometry and a
bounded unknown status.

Coordinate evidence SHALL separate source-image geometry from semantic value
calibration. Numeric values SHALL be emitted only when the selected model's
axis or angular calibration satisfies its support, residual, and confidence
thresholds. Unsupported perspective, 3D, elliptical, or otherwise invalid
geometry SHALL be reported as partial or unsupported rather than silently
normalized into a different model.

#### Scenario: Cartesian and polar charts retain different semantics

- **WHEN** the tools process a clean bar, line, scatter, and ordinary pie
  fixture
- **THEN** the first three results identify Cartesian axes and transforms
- **AND** the pie result identifies polar center, radius, and angular evidence
- **AND** the pie result does not fail because Cartesian axes are absent

#### Scenario: Calibration failure does not erase geometry

- **WHEN** a coordinate model is detected but one or more numeric transforms
  cannot be calibrated reliably
- **THEN** the result preserves source-image geometry and model evidence
- **AND** it omits unsupported semantic values
- **AND** it reports the failed calibration through bounded warnings or
  confidence metadata

#### Scenario: Unsupported geometry remains bounded

- **WHEN** an image contains strong perspective, 3D styling, or a coordinate
  shape outside the supported model
- **THEN** the tool returns reliable partial evidence or an empty chart-specific
  collection
- **AND** it identifies the unsupported condition
- **AND** it does not fabricate a complete coordinate transform or dataset

### Requirement: Chart marks remain independently specialized

The infrastructure SHALL keep chart-mark extraction independent from the
shared evidence and coordinate layers. Bar, line, scatter, and pie detectors
SHALL consume common frame, color, text, and quality evidence without
depending on one another or importing another chart detector's private
helpers. The common layer SHALL NOT require a fixed Agent-facing tool order.

Each detector SHALL preserve its own observable semantics: bar baselines and
stacks, line traces and anchored points, scatter marker and overlap evidence,
or pie sectors and label associations. Shared series and legend identifiers
SHALL be usable by these specialized measurements without converting one
mark type into another.

#### Scenario: A detector can operate with partial shared evidence

- **WHEN** a mark detector receives a frame, OCR, color, or legend result that
  is incomplete
- **THEN** it returns the reliable mark evidence it can establish
- **AND** it does not require another chart detector to complete its result
- **AND** the result marks the missing dependency as uncertainty rather than
  raising an uncaught exception

#### Scenario: Series identity survives specialized geometry

- **WHEN** multiple color-distinguished series are present in a bar, line, or
  scatter chart
- **THEN** each specialized geometry item retains a stable series identifier
- **AND** crossing, overlap, grouping, or stacking does not merge series solely
  because their pixels are close
- **AND** unresolved labels remain explicit rather than invented

#### Scenario: Agent planning remains free

- **WHEN** the user asks for chart restoration or only a descriptive answer
- **THEN** the Agent can choose OCR, visual inspection, a specialized chart
  sensor, assembly, and validation in an order it determines
- **AND** the shared infrastructure does not force every tool or require a
  ChartSpec for descriptive questions

### Requirement: Shared chart quality and visual evidence

Every successful chart observation SHALL expose bounded confidence and
warnings through the common evidence envelope. Confidence values SHALL stay
within `[0, 1]`, and warnings SHALL identify material uncertainty such as
frame ambiguity, calibration failure, unresolved association, merged
geometry, unsupported styling, or incomplete totals. A low-confidence result
SHALL remain usable partial evidence.

The observation infrastructure SHALL provide a source-sized visual evidence
layer for the common frame, coordinate evidence, stable IDs, and material
uncertainty. Chart-specific overlays MAY add bars, traces, markers, sectors,
labels, and baselines, but they SHALL draw from the same serialized source
coordinates instead of re-detecting geometry.

#### Scenario: Complete evidence reports bounded quality

- **WHEN** a clean fixture has complete geometry, coordinate, and association
  evidence
- **THEN** all confidence values are within `[0, 1]`
- **AND** the result includes the common frame and chart-specific overlay
- **AND** the overlay dimensions match the source image

#### Scenario: Ambiguity is visible in data and overlay

- **WHEN** an axis, baseline, legend association, sector boundary, marker
  count, or calibration is ambiguous
- **THEN** the result preserves reliable evidence and emits a material warning
- **AND** confidence is reduced or the affected semantic field is omitted
- **AND** the overlay marks the relevant uncertainty without changing source
  dimensions

#### Scenario: Observation transport remains unchanged

- **WHEN** a sensor returns the common envelope and its source-sized overlay
- **THEN** the existing Agent visual-observation path presents the overlay
  while keeping structured evidence available
- **AND** no new Gateway route or frontend preview protocol is required

