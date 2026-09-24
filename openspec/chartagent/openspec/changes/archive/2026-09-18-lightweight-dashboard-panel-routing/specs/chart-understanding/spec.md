## ADDED Requirements

### Requirement: Chart sensors consume bounded dashboard panel scopes

The bar, line, scatter, and pie observation tools SHALL accept a stable panel
handoff from dashboard decomposition and use its bounded local analysis scope
when one is available. The handoff SHALL preserve the source attachment,
source-image origin, local-to-source transform, panel identity, and uncertainty.
The panel scope SHALL constrain the search area but SHALL NOT replace the
chart-specific sensor's independent detection of plot frame, axes, marks,
baseline, center, or calibration.

#### Scenario: Bar sensor uses the selected panel scope

- **WHEN** the Agent invokes the bar sensor with a valid panel identifier
- **THEN** bar geometry detection is limited to the corresponding panel scope
- **AND** each returned bar and baseline remains attributable to the source
  image and panel identity

#### Scenario: All chart types share the same handoff

- **WHEN** a valid panel identifier targets a line, scatter, or pie chart
- **THEN** the corresponding sensor consumes the same panel handoff contract
- **AND** it preserves chart-specific Cartesian or polar evidence without
  depending on another chart detector

#### Scenario: Panel scope is coarser than the plot

- **WHEN** the selected panel includes titles, legends, labels, and a plot
- **THEN** the sensor searches within the panel scope but independently resolves
  its chart-specific measurement frame
- **AND** surrounding annotations are not automatically emitted as marks or
  calibrated geometry

#### Scenario: Panel handoff is missing or invalid

- **WHEN** a panel identifier cannot be resolved for the requested attachment
- **THEN** the sensor returns a bounded routing error or explicitly warned
  source-image fallback
- **AND** it does not claim that an unrelated full-dashboard measurement is a
  panel-local result

#### Scenario: Local results preserve source coordinates

- **WHEN** a sensor measures geometry within a local panel scope
- **THEN** its structured result and visual overlay use the shared source-image
  coordinate convention
- **AND** the local origin and transform remain available for downstream
  evidence fusion
