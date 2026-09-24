## MODIFIED Requirements

### Requirement: SAM refinement is optional and deterministic panel bounds are the default

The system SHALL validate each VLM-proposed semantic region and use its
validated rectangular bbox, with bounded padding, as the default panel and
analysis scope. A SAM-family backend MAY refine boundary evidence only when an
explicit segmentation mode requests it; SAM availability, checkpoints, or
mask quality MUST NOT be required for a usable decomposition result. Any
optional boundary refinement SHALL preserve the VLM-provided identity, role,
chart-type hint, and rectangular analysis scope unless a separate validated
scope decision is produced.

#### Scenario: Valid VLM proposal produces a panel without SAM

- **WHEN** the Agent provides a valid semantic region and the default
  segmentation mode is used
- **THEN** the tool returns an accepted panel using deterministic rectangular
  bounds and a bounded crop
- **AND** the result does not load or require a SAM checkpoint

#### Scenario: Explicit SAM refinement remains available

- **WHEN** an explicit segmentation mode requests SAM and the optional backend
  returns a valid compatible mask
- **THEN** the panel records the mask-derived boundary as auxiliary evidence
  while preserving the VLM identity and analysis scope

#### Scenario: Optional backend is unavailable

- **WHEN** SAM is not installed, not configured, times out, or returns an
  invalid mask
- **THEN** the tool keeps the validated VLM rectangular panel as a partial or
  accepted result with a bounded warning
- **AND** downstream analysis remains usable without SAM

### Requirement: Named crops and panel scopes are persisted as reusable visual resources

For every accepted or partial panel with a valid rectangular analysis scope,
the system SHALL generate a bounded crop from the validated VLM bbox and
padding, and SHALL retain its source origin, dimensions, panel identifier,
display name, and opaque resource reference when the managed visual boundary
persists it. Optional segmentation boundaries SHALL be retained as provenance
evidence and SHALL NOT silently replace the crop frame or remove edge titles,
axes, legends, or annotations.

#### Scenario: A panel crop and scope are available downstream

- **WHEN** a panel has a valid scope and crop generation succeeds
- **THEN** the result exposes a stable panel identifier, a source-coordinate
  scope, and a bounded crop reference or visual artifact
- **AND** a later chart sensor can resolve the panel identifier to the same
  local analysis scope without using a local filesystem path

#### Scenario: One crop cannot be persisted

- **WHEN** a crop is too large, undecodable, or exceeds the run resource budget
- **THEN** the panel scope and source provenance remain available
- **AND** the result reports a bounded persistence warning without discarding
  other valid panels or preventing source-ROI analysis

### Requirement: Panel handoff scopes later chart analysis

The decomposition result SHALL expose an executable panel handoff for later
bar, line, pie, or scatter observations. The handoff SHALL resolve a stable
panel identifier to a bounded local analysis scope and its source-image
transform. A downstream sensor SHALL be able to consume that scope while
retaining source-image coordinates for attribution and conflict reporting. The
decomposition tool SHALL NOT fabricate chart values, calibrated axes, complete
series data, or a valid ChartSpec.

#### Scenario: A chart sensor consumes a panel scope

- **WHEN** a panel has a valid scope and an advisory chart-type hint
- **THEN** the Agent routes the panel identifier to the corresponding
  specialized sensor
- **AND** the sensor analyzes the bounded local scope and reports the source
  origin and transform used for its measurements

#### Scenario: A sensor determines the inner measurement frame

- **WHEN** a panel scope contains a title, legend, annotations, and a chart
  plot
- **THEN** the sensor uses the panel scope as its search boundary and
  independently determines the chart-specific measurement frame
- **AND** the panel scope is not presented as proof that it is the calibrated
  plot frame

#### Scenario: Panel routing is unavailable

- **WHEN** a requested panel identifier is unknown, stale, or not associated
  with the source attachment
- **THEN** the sensor returns a bounded routing error or an explicitly warned
  source-image fallback according to its contract
- **AND** it does not silently analyze an unrelated panel

#### Scenario: A panel is only partially segmented

- **WHEN** a panel is returned with partial status or unresolved boundary
  warnings
- **THEN** downstream analysis receives the uncertainty and source evidence
- **AND** the system does not present the panel as a fully verified chart
