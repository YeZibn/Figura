## Context

See `proposal.md` for motivation and `specs/` for the changed behavior contract. Current implementation still has decision-shaped state in measurement lifecycle, assembly compatibility/schema, Agent loop context, checkpoint recovery, trace projection and frontend event interpretation. These layers must move together so that `assemble_spec` is the only place where downstream evidence use becomes observable.

## Goals / Non-Goals

**Goals:**

- Establish one authoritative measurement record per session: the current attempt and its measurement/evidence refs, source scope, quality metadata and series metadata.
- Let the main model decide through ordinary tool calls: either reference candidates in assembly or invoke a scoped measurement tool again.
- Make persistence, recovery, events, prompts, tool schemas and frontend projections agree on that contract.
- Remove obsolete decision lifecycle and compatibility paths rather than maintaining dual models.

**Non-Goals:**

- Changing chart detection algorithms, quality scoring, evidence geometry or the available chart measurement tools.
- Removing source/panel authorization, ref integrity checks, ChartSpec validation, generated-chart review or publication gates.
- Removing generation-level source coverage semantics or changing which series a ChartSpec represents; this change only removes measurement-candidate selected/discarded state.
- Deleting existing on-disk run history or measurement artifacts.

## Decisions

### 1. The session owns only the current measurement attempt

Represent the recoverable measurement state as a session bound to one attachment and panel, with one current attempt containing its stable attempt identity, optional parent attempt, `measurement_ref`, `evidence_refs`, effective scope, quality facts and series metadata. Each explicit remeasurement call replaces the session's current attempt while preserving the call/attempt relationship in the ordinary execution trace where that history is available. Do not persist `selected_refs`, `discarded_refs`, `decision_status`, a `measurement_decision` object or an additional list of pending repairs.

This avoids the existing duplication between session state, per-attempt state, ChartSpec provenance, gate state, checkpoint and timeline. Keeping only a current attempt is preferable to preserving an adopted/discarded attempt registry: the model already sees prior tool outputs in the run conversation, while the trace records actual calls and assembly records actual downstream use.

### 2. The model expresses evidence use through the next real action

The main Agent receives candidate refs and their scope/quality/series context. It may call `assemble_spec` with the actual `measurement_ref` and `evidence_refs`, or make another explicit call to the existing measurement tool with a bounded `measurement_target`/scope. Warnings and suggestions remain observations; they do not enqueue work, force a retry, or gate unrelated actions. Tool calls remain constrained to the authorized attachment/panel and never widen silently.

Keep validation at the assembly boundary for the refs the model actually supplies: existence, measurement/session identity, attachment/panel/effective scope and ChartSpec structure. Quality metadata remains visible evidence, not an acceptance/selection status. Invalid referenced evidence still returns a field-local error; unused candidates do not need to be enumerated.

Generation-level `source_scope` and existing coverage semantics remain intact. They describe which source/chart content a generated candidate represents, rather than which measurement candidates the model used, so they are not substitutes for or part of the removed measurement decision state.

### 3. Scope and result are atomic for each measurement call

An initial observation or a local remeasurement is one ordinary tool invocation. Its result contains the requested/effective scope, current attempt identity, candidate refs, quality/series metadata and any bounded diagnostic. Remove the separate `focus_applied`-then-observation obligation and pending-measurement unit. A local measurement failure is a completed tool result with a bounded failure/insufficient-evidence status; the model can then choose its next action.

Use the existing tool-call idempotency, scope validation and shared Agent/run execution budget rather than adding a measurement-specific retry budget, exhaustion state, scheduler or repair queue. Preserve whatever request/attempt identity is needed to safely correlate an explicit repeated call, without storing a parallel repair workflow state machine.

### 4. Recovery derives context from the session and current attempt

Checkpoint serialization stores only the measurement session/current attempt facts necessary to continue the model turn. Recovery rebuilds the bounded measurement context from those facts; it does not persist or merge `pending_measurement_repairs`, selected/discarded refs, or an independent measurement gate. A completed tool result is not replayed as a new measurement call.

Generated-chart review remains an independent blocking lifecycle and retains its current review checkpoint, repair budget and publication semantics. Measurement-state simplification must not weaken that gate.

### 5. Trace and UI show calls/results, not hidden model choices

New runs retain ordinary measurement tool-call/result events and any required observation artifact/reference. The trace does not emit measurement decision-required/selected/discarded events or a separate pending focus/repair lifecycle. The frontend groups the actual tool call and result into one measurement step, renders the result's scope/refs/quality/overlay, and shows another measurement step only when the model actually called a measurement tool again. Actual downstream refs can be inspected in the assembly tool details.

Remove client-side event normalization and labels for the obsolete measurement decision lifecycle. Generated-chart review and publication continue to use their existing canonical events.

### 6. Treat old measurement-decision records as unsupported, without deleting stored data

Do not migrate old run payloads or preserve aliases for removed measurement-decision fields. Existing stored files/rows are not proactively deleted, but the new application contract makes no promise to reconstruct or display those legacy decision details. Do not add a reader-boundary converter unless an implementation dependency proves it necessary; if needed, keep any conversion outside session and ChartSpec models and document its narrow scope.

This is a breaking contract change chosen over dual-read/dual-write compatibility because old runs are not required to remain loadable and retaining adapters would recreate the redundant protocol being removed.

## Risks / Trade-offs

- [Existing stored runs may contain fields or events no longer understood by the new client] → Do not delete their storage, but explicitly accept that legacy measurement-decision details are unsupported; verify new runs and current-run reconnect/recovery instead of adding compatibility adapters.
- [Keeping only the current attempt can make an older result unavailable as a session-level candidate after a retest] → Preserve prior tool outputs in ordinary conversation/trace history when available; each current result carries parent-attempt lineage, and the model may reference only evidence still available and valid at assembly time.
- [A model may request too many focused measurements] → Rely on shared Agent/run execution limits and idempotency, return explicit local errors, and do not create a separate measurement repair budget or silently schedule further calls.
- [Removing decision events changes frontend and evaluation projections] → Update live, replay and evaluation readers together and verify they all project the same actual tool-call/result contract.

## Migration Plan

1. Replace the measurement session/attempt and serialization contract; remove decision fields, automatic decision updates and pending-repair derivation.
2. Simplify assembly inputs, validation and ChartSpec provenance to use actual measurement/evidence refs only; remove schema and prompt compatibility fields.
3. Update checkpoint/recovery and trace/event production so only session/current attempt and actual tool calls/results drive measurement state.
4. Update frontend and evaluation projections to remove obsolete decision lifecycle states and present tool result details in the measurement step.
5. Remove stale tests/fixtures for old decision behavior; add regression coverage for scoped remeasurement, assembly refs, interruption/recovery, live/replay projection and absence of old events.
6. Run focused Python tests, the full Python suite in the `agent` Conda environment, frontend build and smoke checks. No database deletion or legacy data migration is performed.

Rollback, if required before releasing the incompatible contract, is a code rollback only. Do not rewrite or delete persisted run history as part of rollback.
