## REMOVED Requirements

### Requirement: Versioned ChartFigure content model
**Reason**: The new contract is ChartFigure v2 and explicitly does not read or convert v1 Figures or v1 child ChartSpecs.
**Migration**: Submit a new Figure containing only ChartSpec v2 children under `schema_version: 2`.

### Requirement: Assemble a Figure only from valid content and committed measurement references
**Reason**: New Figure assembly uses ChartSpec v2 and the unified measurement tool; legacy measurement references are outside the new Registry contract.
**Migration**: Assemble v2 children and reference successful committed `measure_chart` calls.

### Requirement: Model-facing assembly guidance describes pie constraints
**Reason**: Assembly guidance must cover the complete ten-family v2 dataset contract rather than the four-family v1 point model.
**Migration**: Follow the v2 `coordinate_system` and family-specific `dataset` descriptions exposed by the new tool schema.

## ADDED Requirements

### Requirement: Provide a version 2 ChartFigure content model
Figura SHALL provide an immutable `ChartFigure` version 2 with exactly `schema_version`, `title`, `layout`, and ordered `charts`. `schema_version` SHALL equal 2. `title` SHALL be text of at most 160 Unicode code points and SHALL default to an empty string when omitted. `layout` SHALL contain exactly `columns`, an integer from 1 through 2 and no greater than the child count; row count SHALL be derived as the ceiling of child count divided by columns. `charts` SHALL contain 1 through 4 items. Each item SHALL contain exactly a unique `chart_id`, a complete ChartSpec v2, and optional `measurement_refs`; omitted references SHALL normalize to an empty array. A reference SHALL contain exactly nonempty opaque `run_id` and `call_id` and SHALL identify a successful committed `measure_chart` call in the same Session. The new Figure contract SHALL NOT parse or convert ChartFigure v1 or ChartSpec v1.

Parsing SHALL reject duplicate keys, unknown fields, invalid values, booleans used as numbers, non-finite numbers, and payloads exceeding the existing 64 KiB complete-Figure bound. Canonical serialization SHALL preserve chart and reference order and be deterministic. Figure content SHALL NOT include generated IDs, Run state, file locations, publication state, source authorization, or embedded image bytes; measurement references SHALL NOT certify value-by-value consistency.

#### Scenario: Accept a v2 Figure with multiple supported families
- **WHEN** a v2 Figure contains valid v2 bar and heatmap children and a valid two-column layout
- **THEN** Figura accepts both ordered children and derives the row count

#### Scenario: Reject v1 Figure or child ChartSpec
- **WHEN** the new parser receives a Figure with `schema_version: 1` or a v1 child ChartSpec
- **THEN** it returns a bounded unsupported-version issue and produces no accepted Figure

#### Scenario: Reject duplicate identities or invalid layout
- **WHEN** chart IDs repeat, references repeat, columns exceed bounds, or a child ChartSpec is invalid
- **THEN** the whole Figure is rejected without accepting valid siblings

### Requirement: Assemble a Figure from v2 content and committed unified measurements
Figura SHALL register `assemble_chart_figure` for one complete ChartFigure v2. It SHALL strictly parse the full Figure, validate every ChartSpec v2 child, and resolve every supplied measurement reference to a successful committed `measure_chart` result in the same Session, either in an earlier terminal Run or in the committed prefix of the target Run. Unknown, failed, uncommitted, or cross-Session references SHALL reject the entire Figure. Empty references SHALL mean no measurement was selected; Figura SHALL NOT infer references or assert that selected evidence proves every child value. The tool SHALL NOT repair content, accept v1 values, render the Figure, or create separate domain storage.

#### Scenario: Assemble children backed by successful measurements
- **WHEN** every child is valid v2 content and every supplied reference names a successful same-Session `measure_chart` call
- **THEN** assembly succeeds with the complete ordered Figure summary

#### Scenario: Reject an old or unresolved measurement reference
- **WHEN** a reference names a legacy measurement tool, failed call, uncommitted call, unknown call, or another Session
- **THEN** assembly fails with a bounded field-specific error and accepts no child chart

#### Scenario: Assemble content without measurement references
- **WHEN** a valid child has an omitted or empty `measurement_refs`
- **THEN** the Figure may be accepted without claiming that the child is measurement-backed

#### Scenario: Reject the entire Figure when one child is invalid
- **WHEN** any child ChartSpec or reference fails validation
- **THEN** no child is separately accepted and the tool returns a bounded failure

### Requirement: Describe all v2 chart data to the model
The `assemble_chart_figure` description and native parameter schema SHALL communicate that Figure children use ChartSpec v2 and that `dataset` shape depends on `metadata.chart_type`. Guidance SHALL describe the ten supported types and the basic bubble/scatter and donut/pie variants, distinguish numeric, categorical, polar, matrix, and hierarchical coordinates, explain nullable gaps/cells, and state that evidence references are selected observations rather than value verification. The schema SHALL reject unknown fields and SHALL NOT add alternate v1 shapes or automatic repair.

#### Scenario: Inspect the v2 assembly contract
- **WHEN** the Agent receives the registered assembly tool definition
- **THEN** its name, description, and native schema describe v2 family-specific data and valid references

#### Scenario: Reject an old point shape
- **WHEN** a v2 child uses v1 categorical or coordinate points instead of the selected family dataset
- **THEN** assembly returns a bounded field-path validation failure without accepting the Figure
