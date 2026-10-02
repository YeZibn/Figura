## ADDED Requirements

### Requirement: Model-facing assembly guidance describes pie constraints
The registered `assemble_chart_figure` tool description and relevant input-field descriptions SHALL explain that pie dataset points use `category` and `value`, that `series` and Cartesian `axes` must be absent or null, and that separate series intended as separate pies belong in distinct ChartFigure children. Guidance SHALL use the existing ChartSpec and ChartFigure fields and SHALL NOT add alternate schema fields, relax semantic validation, or silently repair invalid content.

#### Scenario: Inspect the assembly tool contract
- **WHEN** an Agent receives the registered assembly tool definition
- **THEN** its model-visible description and schema communicate the pie dataset and axis constraints and the separate-child approach

#### Scenario: Reject and correct a pie series
- **WHEN** a submitted pie point contains a non-null `series`
- **THEN** assembly returns its bounded field-specific validation failure without accepting a partial Figure
- **AND** a later valid submission using separate pie children can succeed through the same tool
