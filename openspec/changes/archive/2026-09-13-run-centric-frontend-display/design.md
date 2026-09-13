## Context

See `proposal.md` for the motivation. The frontend receives session messages
and persisted/live Run timelines as separate collections. The observed defect
is that the Gateway creates one Run ID while the Agent Memory creates another;
the projection therefore emits message IDs that the frontend cannot match to
the Run timeline. Python commands and tests continue to use the Conda `agent`
environment when applicable.

## Goals / Non-Goals

**Goals:**

- Establish the Gateway-created Run ID as the canonical identity for one
  operation across the runtime, memory, trace, projection, and artifacts.
- Keep the three visual stages in a predictable order: user request,
  expandable execution process, and final result.
- Preserve all execution events and tool evidence while moving generated chart
  previews to the final result section.
- Make live submission, mock data, reload, and legacy unassociated messages
  follow the same rendering contract.
- Add regression coverage for both the identity contract and the visible
  conversation order.

**Non-Goals:**

- No new Tauri integration or native-window behavior.
- No replacement of the existing safe Markdown renderer, event schema, or
  artifact retention policy.
- No requirement to rewrite historical records when they have no reliable
  mapping; those records remain visible through an explicit compatibility
  path.

## Decisions

### 1. Gateway owns the canonical Run identity

The Run created at Gateway admission is the authoritative identity. The
Gateway worker passes that identity into the Agent runtime, and the runtime
uses it when creating the durable Agent Memory run and emitting trace events.
Command-line callers that do not provide an external identity retain the
existing generated-ID behavior.

This is preferable to making the frontend guess associations from timestamps
or answer text. Those heuristics can attach a message to the wrong Run when
multiple requests finish close together.

### 2. Memory accepts an optional externally supplied Run ID

The durable memory layer will accept the canonical ID for Gateway-backed
runs and still generate an ID for standalone callers. It will reject a
collision that belongs to another session rather than silently reusing a
record. The Run's event records, attachments, and final answer consequently
share one identity without changing the public Gateway route shape.

### 3. Keep Run blocks as a derived frontend view

The conversation panel will sort Run timelines by creation time and derive
one block per Run. Each block resolves user and assistant messages through
the canonical `${runId}:user` and `${runId}:assistant` IDs. Messages that
cannot be resolved remain visible through a clearly defined legacy fallback;
new server-backed data must not enter that fallback due to an identity split.

### 4. Keep event normalization separate from result extraction

Existing normalization continues to correlate tool calls, results, and
observations by call identifier. A separate selector extracts
`generated_chart` artifacts for the final result area. The timeline keeps the
generation event and a bounded label, but does not duplicate the chart
preview. Filtering the event out was rejected because the persisted trace
would no longer describe the actual process.

### 5. Preserve independent disclosure state

Run expansion remains controlled by the Run state set, while the final
assistant message keeps its Markdown/source disclosure. The new identity
flow does not change event ordering, streaming recovery, or the safe Markdown
renderer.

## Risks / Trade-offs

- [Risk] Existing records created with split identities have no stored
  cross-reference → Mitigation: preserve them in a visible compatibility
  state and avoid claiming a complete association; new data uses the
  canonical identity.
- [Risk] An externally supplied ID could collide with a persisted memory run
  → Mitigation: validate ownership and fail before creating or mutating a
  conflicting record.
- [Risk] A Run timeline can temporarily exist without messages during live
  startup → Mitigation: render the Run process immediately and attach the
  pending request as soon as the canonical ID is returned.
- [Risk] Moving previews changes visual density and may expose narrow-layout
  issues → Mitigation: constrain the result artifact area and run frontend
  build, smoke, and browser checks.

## Migration Plan

No route or database schema migration is required for new runs. Deploy the
runtime identity propagation, projection behavior, and frontend together so
new Gateway runs use one ID end to end. Existing split-identity data remains
readable through the compatibility path; it is not silently merged. To roll
back, revert the runtime identity propagation and frontend grouping changes;
the existing persisted records and event schema remain usable.
