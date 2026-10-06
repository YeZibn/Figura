## REMOVED Requirements

### Requirement: Measure pie sectors from an authorized Attachment or Panel
**Reason**: New Runs use the single `measure_chart` contract with `chart_type: pie`, which also supports donut geometry.
**Migration**: Call `measure_chart` with the authorized source reference, `chart_type: pie`, and optional `observation_scope`; read the v2 `pie` observation branch.

### Requirement: Apply a validated observation scope to pie measurement
**Reason**: Observation scope is now defined once for all families by `chart-family-measurement`.
**Migration**: Pass the unchanged source-relative `observation_scope` to `measure_chart`.
