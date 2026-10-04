## MODIFIED Requirements

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
