## MODIFIED Requirements

### Requirement: Valid ChartSpec produces a bounded chart artifact

The system SHALL accept a semantically valid ChartSpec and produce a chart
artifact for bar, line, pie, and scatter chart types. The artifact SHALL
represent the supplied title, labels, series distinctions, and dataset without
inventing, silently dropping, or silently reclassifying semantic data. A
missing categorical value SHALL NOT be rendered as an actual zero. Declared
numeric axis ranges SHALL either be applied to the corresponding axis or be
rejected before rendering. User-visible text containing Chinese characters
SHALL be rendered with a compatible CJK font when one is available, and the
output SHALL use a supported image media type and remain within configured
size and dimension limits.

The generation-facing validation operation and rendering operation SHALL apply
the same structural and chart-type semantic rules. A successful rendering
result SHALL include bounded validation status for semantic, layout, and
artifact checks; a failed check that makes the chart unsafe or semantically
ambiguous SHALL prevent publication of the chart artifact.

#### Scenario: Cartesian ChartSpec is rendered with faithful data

- **WHEN** a valid bar, line, or scatter ChartSpec is submitted for rendering
- **THEN** the system produces an image artifact with the declared chart type,
  title and available axis labels
- **AND** the plotted values, point count, category order, and series
  distinctions correspond to the ChartSpec dataset
- **AND** any declared numeric axis ranges are reflected in the rendered axes
- **AND** Chinese titles, axis labels, tick labels, legends, and data labels
  remain visibly renderable when a compatible CJK font is available

#### Scenario: Missing grouped-bar data is not treated as zero

- **WHEN** a grouped bar ChartSpec declares a category set but a series has no
  value for one of those categories
- **THEN** the system returns a located semantic validation issue and produces
  no chart artifact unless the missing value is explicitly represented by a
  supported missing-data convention
- **AND** it does not publish a zero-height bar that implies an observed zero

#### Scenario: Pie ChartSpec is rendered without axes

- **WHEN** a valid pie ChartSpec contains non-negative categorical values and
  no axes
- **THEN** the system produces an image artifact whose sectors correspond to
  the categories and values
- **AND** the artifact exposes enough legend or label metadata to associate
  each sector with its category
- **AND** Chinese category labels and percentages remain visibly renderable
  when a compatible CJK font is available

#### Scenario: Multi-series data remains distinct

- **WHEN** a valid ChartSpec contains points assigned to multiple series
- **THEN** the generated chart preserves the series distinction in its visual
  encoding and bounded artifact metadata
- **AND** points are not merged solely because they share a category or axis

#### Scenario: Invalid ChartSpec is rejected before rendering

- **WHEN** a ChartSpec is missing required axes, contains invalid points,
  unsupported values, an invalid pie dataset, duplicate categorical points, or
  an invalid numeric axis range
- **THEN** the system returns a bounded structured validation error
- **AND** it produces no chart artifact

#### Scenario: Validation tools agree on generation eligibility

- **WHEN** the same ChartSpec is passed to the generation-facing validation
  operation and the rendering operation
- **THEN** both operations apply the same semantic eligibility rules
- **AND** a spec accepted for rendering is not rejected later for a rule that
  the standalone validation operation omitted

### Requirement: Generated chart output is bounded and attributable

Every successful generated chart SHALL expose an opaque artifact reference,
media type, byte count, dimensions, chart type, bounded caption or title, and
bounded validation diagnostics. Artifact metadata SHALL NOT contain local
source paths, credentials, raw provider payloads, or embedded image bytes.
Generated output SHALL be distinguishable from temporary model-observation
images.

#### Scenario: Generated output metadata is safe

- **WHEN** a rendering operation succeeds
- **THEN** its structured result contains bounded metadata and an opaque
  reference suitable for Gateway and desktop-client retrieval
- **AND** the JSON result contains no raw image bytes or local filesystem path
- **AND** the validation diagnostics identify whether semantic, layout, and
  artifact checks passed or produced bounded warnings

#### Scenario: Output limits and artifact validity are enforced

- **WHEN** the rendered image exceeds the configured byte or dimension limit,
  cannot be fully decoded as the declared image type, or fails an artifact
  integrity check
- **THEN** the system rejects or bounds the output with an explicit reason
- **AND** it does not publish a partial, malformed, or unverified artifact

## ADDED Requirements

### Requirement: Rendered chart undergoes a deterministic quality audit

After a ChartSpec has been rendered and before the generated artifact is
returned, the system SHALL audit the in-memory chart and encoded image. The
audit SHALL check that the rendered artists cover the requested data and that
visible titles, labels, tick labels, annotations, legends, and chart content
fit within the fixed output canvas. Layout-only findings MAY be returned as
bounded warnings when the chart remains usable; semantic fidelity failures,
severe clipping, or unreadable output SHALL fail the generation.

#### Scenario: Rendered artists cover the ChartSpec

- **WHEN** a ChartSpec passes pre-render validation and the renderer creates a
  figure
- **THEN** the audit verifies chart-type-specific artist counts and values,
  including bars, line or scatter points, pie sectors, categories, and series
- **AND** a mismatch produces a located validation failure and no published
  chart artifact

#### Scenario: Visible content stays within the canvas

- **WHEN** the renderer has laid out a chart containing titles, axes, labels,
  annotations, or legends
- **THEN** the audit measures their final rendered bounds after a canvas draw
- **AND** content that is clipped or materially outside the fixed canvas
  produces a structured layout failure or warning according to configured
  severity

#### Scenario: Usable layout warning remains explicit

- **WHEN** a chart is renderable but has dense labels, a crowded legend, or
  another bounded readability concern that does not invalidate its data
- **THEN** the system returns the chart with validation status `warning`
- **AND** the result identifies the concern without claiming an unqualified
  validation pass
