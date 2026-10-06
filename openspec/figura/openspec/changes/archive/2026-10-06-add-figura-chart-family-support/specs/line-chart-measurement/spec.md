## REMOVED Requirements

### Requirement: Measure lines from an authorized Attachment or Panel
**Reason**: New Runs use the single `measure_chart` contract with `chart_type: line`; the standalone `measure_lines` API is removed.
**Migration**: Call `measure_chart` with the authorized source reference, `chart_type: line`, and optional `observation_scope`.

### Requirement: Return line geometry and supported point observations
**Reason**: Line observations now use the versioned family branch of the unified `measure_chart` result.
**Migration**: Read the v2 `observations` branch for `line`; old standalone result shapes are not adapted by the new contract.
