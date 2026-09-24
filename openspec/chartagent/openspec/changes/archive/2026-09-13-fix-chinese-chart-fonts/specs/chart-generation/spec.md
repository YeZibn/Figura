## MODIFIED Requirements

### Requirement: Valid ChartSpec produces a bounded chart artifact

The system SHALL accept a structurally valid ChartSpec and produce a chart
artifact for bar, line, pie, and scatter chart types. The artifact SHALL
represent the supplied title, labels, series distinctions, and dataset without
inventing or silently dropping semantic data. User-visible text containing
Chinese characters SHALL be rendered with a compatible CJK font when one is
available, and the output SHALL use a supported image media type and remain
within configured size and dimension limits.

#### Scenario: Cartesian ChartSpec is rendered

- **WHEN** a valid bar, line, or scatter ChartSpec is submitted for rendering
- **THEN** the system produces an image artifact with the declared chart type,
  title and available axis labels
- **AND** the plotted values and series distinctions correspond to the
  ChartSpec dataset
- **AND** Chinese titles, axis labels, tick labels, legends, and data labels
  remain visibly renderable when a compatible CJK font is available

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

- **WHEN** a ChartSpec is missing required axes or contains invalid points,
  unsupported values, or an invalid pie dataset
- **THEN** the system returns a bounded structured validation error
- **AND** it produces no chart artifact

### Requirement: Chinese font availability is diagnosable

The rendering operation SHALL allow a caller to provide a font path override
and SHALL search supported system font families when no override is provided.
When no compatible CJK font can be resolved, the system SHALL still preserve
the existing bounded rendering behavior where possible, while returning an
explicit bounded warning or status that identifies the fallback condition.

#### Scenario: Configured font override is available

- **WHEN** a caller provides a readable supported font path
- **THEN** the renderer uses that font for all generated chart text
- **AND** the result metadata identifies the resolved font as configured

#### Scenario: System CJK font is resolved

- **WHEN** no font override is provided and a supported system CJK font exists
- **THEN** the renderer uses the discovered font for all generated chart text
- **AND** the result metadata identifies the resolved font as system-provided

#### Scenario: No CJK font is available

- **WHEN** neither the configured path nor supported system font families can
  provide a compatible CJK font
- **THEN** the renderer returns a bounded fallback warning or status
- **AND** it does not silently claim that Chinese text was rendered correctly
