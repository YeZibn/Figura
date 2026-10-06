# chart-figure-assembly Specification

## Purpose

Defines how Figura combines validated single-chart content into one ordered canvas, records the measurements selected for each child chart, and makes accepted canvases addressable in later Run actions.

## Requirements

### Requirement: Accepted Figures have stable Run-scoped references and durable content
`assemble_chart_figure` SHALL be classified as `replay_safe` because it validates and summarizes content without creating an external side effect. On success, its result SHALL contain exactly `figure_ref`, `figure_digest`, `title`, and `charts`. `figure_ref` SHALL contain `run_id` and `call_id` from the executing Run and tool call. `figure_digest` SHALL be the lowercase hexadecimal SHA-256 digest of the canonical serialized ChartFigure. `charts` SHALL preserve Figure order and contain one summary per item with exactly `chart_id`, `chart_type`, and `title`, where type and title are read from the child `ChartSpecData.metadata`.

The complete submitted Figure SHALL remain available in the existing durable `ToolCallFact.arguments_json`; the successful result summary SHALL remain available in `ToolResultFact`. The identity of one accepted Figure SHALL be the `(run_id, call_id)` pair. Only a successful committed result for `assemble_chart_figure` SHALL make that reference an accepted Figure. Figura SHALL NOT create a separate Figure table, mutable Figure store, or independently generated ID in this change.

#### Scenario: Persist a successful Figure through Runtime facts
- **WHEN** an `assemble_chart_figure` call succeeds and its tool result commits
- **THEN** the complete Figure input is retained in the call fact
- **AND** its Run-scoped reference, digest, and ordered summary are retained in the result fact

#### Scenario: Keep failed Figure calls out of the accepted inventory
- **WHEN** an assembly call fails validation or its successful result does not commit
- **THEN** its call arguments may remain in Run history as an attempted tool call
- **AND** it is not exposed as an accepted Figure

#### Scenario: Recompute the same digest for the same canonical Figure
- **WHEN** the same canonical Figure content is assembled again in a different tool call
- **THEN** both results contain the same `figure_digest`
- **AND** each result has its own `(run_id, call_id)` reference

### Requirement: Expose accepted Figure summaries to later Agent actions
Figura SHALL expose each committed assemble_chart_figure outcome in the target Run's read-only RunExecutionState.resources catalog as a typed chart_figure resource, following the shared run-execution-resources contract. A successful resource SHALL retain the complete accepted ChartFigure and its verified digest in typed resource content, keyed by a reference containing the resource kind, originating run_id, and call_id. A committed failed assembly SHALL remain queryable as a failed resource with its structured error, but SHALL NOT be treated as an accepted Figure. Resources SHALL be reconstructed only from eligible same-Session Run history and the target Run's committed prefix, and SHALL exclude started attempts without committed results and facts owned by another Session.

Every Provider request SHALL include a compact text inventory projected from the resource catalog. For an accepted Figure, the inventory SHALL contain its typed reference, title, digest, and ordered chart summaries with chart_id, chart_type, and chart title. A failed assembly resource SHALL appear with its reference, failed outcome, and structured error, but SHALL NOT appear as an accepted Figure summary. The inventory SHALL NOT serialize the complete ChartFigure content; that content remains available through the typed resource content.

#### Scenario: Include a Figure from an earlier Run
- **WHEN** a target Run belongs to a Session with a successfully assembled Figure in an eligible earlier terminal Run
- **THEN** its resource catalog contains the Figure's typed reference and complete accepted content
- **AND** the Provider request includes the Figure's ordered summary

#### Scenario: Include a Figure assembled in the target Run
- **WHEN** the target Run has a successful committed assemble_chart_figure result in its authorized prefix
- **THEN** the resource catalog contains its accepted Figure resource
- **AND** the next Provider request includes its reference and summary

#### Scenario: Keep a committed failed assembly queryable but unaccepted
- **WHEN** an assembly call commits a structured failure
- **THEN** the resource catalog retains its typed reference, failed outcome, and error
- **AND** the Provider inventory does not present it as an accepted Figure

#### Scenario: Exclude incomplete and cross-Session Figures
- **WHEN** tool arguments exist without a committed result, or a Figure fact belongs to another Session or falls outside the target Run's authorized prefix
- **THEN** the target Run's resource catalog and Provider inventory omit that Figure fact

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
