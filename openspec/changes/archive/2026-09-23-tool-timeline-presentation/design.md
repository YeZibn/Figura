## Context

See `proposal.md` for motivation and `specs/desktop-client/spec.md` plus
`specs/evaluation-workbench/spec.md` for the user-facing contract.

The backend tool catalog already emits a bilingual `tool_label` on tool-call,
tool-result, and skipped-tool events, and the Gateway preserves it. The frontend
currently uses that label for measurement and observation units, but uses a
generic generation-unit label for both `assemble_spec` and `render_chart`.
Tool-result summaries can expose raw status tokens, and an unrecognized result
status currently falls through to the completed timeline state. Tool detail
cards also initialize as open for running, blocked, or failed states.

The evaluation history renders the same `RunTimeline` component as ordinary
runs. Its supplemental-record list intentionally excludes tool call/result
events, so there should be no second evaluation-specific tool timeline.

## Goals / Non-Goals

**Goals:**

- Make the actual tool identity the headline for every tool-backed timeline
  step, while keeping its phase as secondary context.
- Present recognized tool and artifact states in consistent Simplified Chinese
  without inferring success, review passage, or publication from unknown data.
- Keep tool details opt-in while retaining a useful collapsed summary and
  making ordinary runs and evaluation history behave identically.
- Preserve existing event correlation, bounded details, safe-resource loading,
  and independent final-chart presentation.

**Non-Goals:**

- Change Agent tool execution, Gateway event schemas, persistence, review gates,
  publication, or run lifecycle behavior.
- Add a frontend copy of the backend tool-name catalog or a second evaluation
  presentation implementation.
- Hide generated charts, user/assistant messages, or necessary failure
  summaries behind the tool-detail disclosure.
- Migrate or rewrite persisted run events.

## Decisions

### Use the per-tool presentation metadata for every tool-backed headline

The timeline projection SHALL prefer the existing `tool_label`, then use the
available display name and stable tool identifier as a bounded fallback. The
tool label SHALL take precedence over a broad unit category such as
`generation`; the phase remains a separate secondary label. This distinguishes
assembly from rendering without adding a frontend mapping table or changing
the event protocol.

An alternative was to expand the frontend's `nodeLabels` table with every tool
name. That is rejected because it duplicates the backend catalog and can drift
from event metadata. Another alternative was to change tool unit categories;
that would alter correlation semantics to solve a presentation-only problem.

### Normalize status by event kind and keep unknown explicit

User-facing status text SHALL be derived from the event's documented status
field, using an explicit mapping. Tool-call `running`, tool-result `success` or
`error`, and skipped-tool `not_started` represent running, completed, failed,
and not-executed states respectively. Missing or unrecognized values SHALL
remain `unknown` for display rather than falling through to completed. Raw
tokens remain available only inside technical details.

Tool completion, chart-render availability, review outcome, and publication
remain distinct. A successful `render_chart` tool result does not establish
that review passed or the chart was published; only the corresponding review
and publication evidence can show those states.

An alternative was to translate arbitrary status strings or infer success from
the event kind. That is rejected because it hides protocol drift and can
contradict the actual review/publication state.

### Collapse details independently of lifecycle status

Each tool-step disclosure SHALL start closed for running and terminal states.
The collapsed summary retains the bilingual tool name, timestamp, localized
status, and bounded failure reason when present. Expanding it reveals the
existing arguments, bounded result, observations, and technical event details.
The user's manual expansion state is not reset merely because a new event
updates the tool status.

An alternative was to keep failed or running cards automatically open. That is
rejected because it exposes large raw payloads precisely when users are
scanning a timeline. Essential state and failure information instead belongs
in the summary row.

### Reuse the same component and projection in evaluation history

The ordinary workspace and evaluation history SHALL continue to use the same
timeline projection and tool-step component. Evaluation-specific records remain
limited to supplemental conversation and review material; tool call/result
events are not duplicated there. This avoids divergent labels, status mapping,
or disclosure behavior.

### Keep generated chart artifacts outside tool disclosure

Generated-chart previews and downloads remain in the existing result area.
Collapsing the `render_chart` tool's raw result SHALL NOT hide the user-facing
chart, and tool success SHALL NOT be substituted for review or publication
status on that artifact.

## Risks / Trade-offs

- **A status emitted by the backend is not yet in the explicit map** → show
  `状态未知`, preserve the raw value in technical details, and add a focused
  mapping test before treating it as a recognized state.
- **Collapsing failure details makes a failure harder to notice** → keep the
  bounded failure reason and failed state in the summary independently of the
  disclosure.
- **Persisted events lack a bilingual label** → prefer available display-name
  and identifier fields without creating a second tool catalog; keep the raw
  event inspectable when presentation metadata is unavailable.
- **Timeline updates reopen details unexpectedly** → keep disclosure state
  local to the stable timeline item and test status updates while closed and
  while manually expanded.

## Migration Plan

No event or storage migration is needed. The client changes only how existing
bounded event fields are projected and displayed; persisted run history remains
read-only and final chart resources keep their current lifecycle.
