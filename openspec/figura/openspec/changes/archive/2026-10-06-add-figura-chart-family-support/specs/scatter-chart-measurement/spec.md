## REMOVED Requirements

### Requirement: Measure scatter points from an authorized Attachment or Panel
**Reason**: New Runs use the single `measure_chart` contract with `chart_type: scatter`; the standalone `measure_scatter` API is removed.
**Migration**: Call `measure_chart` with the authorized source reference, `chart_type: scatter`, and optional `observation_scope`.

### Requirement: Return scatter geometry and calibrated coordinates
**Reason**: Scatter and bubble observations now use the versioned family branch of the unified `measure_chart` result.
**Migration**: Read the v2 `observations` branch for `scatter`; old standalone result shapes are not adapted by the new contract.
