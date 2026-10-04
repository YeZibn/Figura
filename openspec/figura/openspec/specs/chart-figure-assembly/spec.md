# chart-figure-assembly Specification

## Purpose

Defines how Figura combines validated single-chart content into one ordered canvas, records the measurements selected for each child chart, and makes accepted canvases addressable in later Run actions.

## Requirements

### Requirement: Versioned ChartFigure content model
Figura SHALL provide an immutable version 1 `ChartFigure` content value with exactly these top-level fields: `schema_version`, `title`, `layout`, and `charts`. `schema_version` SHALL equal 1. `title` SHALL be text of at most 160 Unicode code points and MAY be omitted on input, in which case it SHALL normalize to an empty string. `layout` SHALL contain exactly `columns`, an integer from 1 through 2 that is no greater than the number of child charts. The renderer-facing row count SHALL be derived as the ceiling of `chart_count / columns`; it SHALL NOT be stored as a second layout field.

`charts` SHALL be an ordered array of 1 through 4 `ChartFigureItem` values. Each item SHALL contain exactly `chart_id`, `chart_spec`, and `measurement_refs`. `chart_id` SHALL match `[A-Za-z0-9_-]{1,64}` and SHALL be unique within the Figure. `chart_spec` SHALL be a complete `ChartSpecData` value and SHALL pass the existing ChartSpec parser and semantic validator. `measurement_refs` MAY be omitted on input and SHALL normalize to an empty array; when present it SHALL contain at most 16 unique references. Each reference SHALL contain exactly a non-empty opaque `run_id` and `call_id` identifying one measurement tool call. Item order SHALL define canvas order and reference order SHALL be preserved.

ChartFigure parsing SHALL reject duplicate JSON keys, unknown fields at any nesting level, missing required fields, booleans used as numbers, invalid values, and non-finite numbers without coercion or silent repair. Canonical serialization SHALL preserve chart and reference order, normalize the documented optional fields, and be deterministic. A serialized ChartFigure SHALL not exceed 64 KiB, matching the existing model-tool argument bound. ChartFigure SHALL NOT add a generated Figure ID, render state, file location, publication state, or source authorization fields. Its `measurement_refs` identify selected observations but do not certify that the child data exactly matches those observations.

#### Scenario: Parse a Figure with multiple chart types
- **WHEN** a version 1 Figure contains valid bar and line ChartSpecData children with distinct chart IDs and a two-column layout
- **THEN** Figura accepts the ordered Figure and preserves both child specs and their order
- **AND** the layout row count is derived from the child count and column count

#### Scenario: Normalize optional Figure title and measurement references
- **WHEN** a valid Figure omits `title` and one child omits `measurement_refs`
- **THEN** canonical content contains an empty Figure title and an empty reference array for that child

#### Scenario: Reject invalid Figure structure atomically
- **WHEN** a Figure has an unsupported version, duplicate chart ID, invalid child ChartSpecData, invalid columns, more than four children, an unknown field, or serialized content over 64 KiB
- **THEN** Figura returns a bounded validation failure with the applicable field path
- **AND** no partially accepted Figure is produced

#### Scenario: Reject repeated measurement references
- **WHEN** one chart item lists the same `(run_id, call_id)` reference more than once
- **THEN** Figure validation rejects the duplicate reference at its field path

### Requirement: Assemble a Figure only from valid content and committed measurement references
Figura SHALL register a model-callable `assemble_chart_figure` tool whose input is one complete version 1 `ChartFigure` object. The tool SHALL run strict Figure parsing, each child's existing ChartSpec validation, and runtime reference resolution before returning success. Every supplied `measurement_refs` entry SHALL resolve to a successful committed `measure_bars`, `measure_lines`, `measure_scatter`, or `measure_pie` outcome in the same Session, either in an earlier terminal Run or in an already committed tool result in the target Run. A reference to an unknown, failed, not-yet-committed, or other-Session measurement SHALL reject the entire Figure. An omitted or empty `measurement_refs` array SHALL mean that no measurement is selected for that child; the tool SHALL NOT infer references from chart text or values.

The tool SHALL NOT determine whether a chart's data values are numerically faithful to its referenced measurement results, repair data, create a partial Figure, render an image, or write a second copy to domain storage. Validation failures SHALL return a bounded structured tool error and SHALL NOT return a Figure reference.

#### Scenario: Assemble a Figure using previously committed measurements
- **WHEN** every supplied measurement reference points to a successful same-Session measurement result and every child ChartSpecData is valid
- **THEN** `assemble_chart_figure` succeeds with the complete ordered Figure summary

#### Scenario: Reject an unresolved or unauthorized measurement reference
- **WHEN** any supplied reference points to a failed or uncommitted call, an unknown call, or a measurement in another Session
- **THEN** `assemble_chart_figure` fails with a bounded field-specific error
- **AND** Figura accepts none of the Figure's child charts

#### Scenario: Assemble a chart that has no selected measurement
- **WHEN** a valid child chart has an omitted or empty `measurement_refs` array
- **THEN** the Figure may be accepted with no measurement reference for that child
- **AND** the result does not claim that the child is measurement-backed

#### Scenario: Reject a Figure when one child is invalid
- **WHEN** one child ChartSpecData or one of its measurement references is invalid
- **THEN** the entire assembly fails
- **AND** no valid sibling child is separately accepted

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

### Requirement: Model-facing assembly guidance describes pie constraints
The registered `assemble_chart_figure` tool description and relevant input-field descriptions SHALL explain that pie dataset points use `category` and `value`, that `series` and Cartesian `axes` must be absent or null, and that separate series intended as separate pies belong in distinct ChartFigure children. Guidance SHALL use the existing ChartSpec and ChartFigure fields and SHALL NOT add alternate schema fields, relax semantic validation, or silently repair invalid content.

#### Scenario: Inspect the assembly tool contract
- **WHEN** an Agent receives the registered assembly tool definition
- **THEN** its model-visible description and schema communicate the pie dataset and axis constraints and the separate-child approach

#### Scenario: Reject and correct a pie series
- **WHEN** a submitted pie point contains a non-null `series`
- **THEN** assembly returns its bounded field-specific validation failure without accepting a partial Figure
- **AND** a later valid submission using separate pie children can succeed through the same tool
