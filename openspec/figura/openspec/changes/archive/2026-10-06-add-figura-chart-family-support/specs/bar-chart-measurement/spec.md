## REMOVED Requirements

### Requirement: Measure bars from an authorized Attachment or Panel
**Reason**: New Runs use the single `measure_chart` contract with `chart_type: bar`; the standalone `measure_bars` API is removed.
**Migration**: Call `measure_chart` with the authorized source reference, `chart_type: bar`, and optional `observation_scope`.

### Requirement: Return pixel-based bar geometry and measurements
**Reason**: Bar observations now use the versioned family branch of the unified `measure_chart` result.
**Migration**: Read the v2 `observations` branch for `bar`; old standalone result shapes are not adapted by the new contract.
