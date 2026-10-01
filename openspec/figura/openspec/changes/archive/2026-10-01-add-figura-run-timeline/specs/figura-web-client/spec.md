## ADDED Requirements

### Requirement: Figura displays a concise per-Run tool execution timeline
Figura mode SHALL display a chronological user-facing timeline derived from the selected Run's Figura timeline projection. Each tool call, its attempts, and its result SHALL appear as one logical step, with a localized tool name when known, stable tool identifier, localized status, and a bounded failure summary when present. Tool-specific details SHALL be safe, allowlisted summaries rather than raw arguments or result payloads; they SHALL be collapsed by default in every state and SHALL load only when the user expands the step. Missing or unrecognized status SHALL be shown as unknown or reconciliation-required and SHALL NOT be inferred as success. Model-start/completion events SHALL NOT appear as ordinary timeline rows. Existing Panel and ChartRender galleries SHALL remain separate Run outputs. Timeline refreshes SHALL follow replayable `run_progress` events and durable event cursors; reload and reconnect SHALL restore committed steps without duplication or re-executing tools. Observation previews SHALL load on demand through the Figura client. The timeline SHALL NOT add manual tool invocation, measurement-scope selection, retry, resume, or interruption controls, and SHALL NOT change ChartAgent or mock behavior.

#### Scenario: Restore a completed Run timeline
- **WHEN** a user opens a Figura Session containing a completed Run with tool calls
- **THEN** the workspace displays its committed steps in tool-call order and keeps the final answer, Panel gallery, and ChartRender gallery in their existing areas

#### Scenario: Group a tool call and result into one step
- **WHEN** a Run has a tool-call fact, one or more attempt facts, and a matching result fact
- **THEN** the timeline presents one logical step with the current committed status rather than separate call and result rows

#### Scenario: Keep step details collapsed
- **WHEN** a tool step is pending, running, completed, failed, or reconciliation-required
- **THEN** its safe details and attempt history remain collapsed while the summary name, status, time, and necessary failure explanation remain visible

#### Scenario: Inspect a step on demand
- **WHEN** a user expands a tool step
- **THEN** the Figura client loads its bounded safe summaries and any authorized observation preview without loading those details for every timeline item in advance

#### Scenario: Refresh after a live tool-fact commit
- **WHEN** the active Run emits a replayable `run_progress` event
- **THEN** the client refreshes the durable timeline snapshot, merges by Run and call identity, and preserves the Run event cursor without duplicating a step

#### Scenario: Show unknown or unresolved status explicitly
- **WHEN** a call has no committed result or the result status is unsupported
- **THEN** the timeline displays a pending, running, unknown, or reconciliation-required state supported by the durable facts and never presents the call as successful

#### Scenario: Keep generated chart output separate
- **WHEN** a tool timeline contains `assemble_chart_figure` or `render_chart_figure`
- **THEN** those actions appear as tool steps while committed rendered PNGs remain visible in the separate ChartRender gallery

#### Scenario: Preserve other frontend modes
- **WHEN** the frontend runs in mock or ChartAgent mode
- **THEN** it continues to use its existing event contract and timeline behavior without calling Figura timeline routes
