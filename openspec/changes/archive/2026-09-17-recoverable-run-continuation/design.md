## Context

See `proposal.md` for the motivation and behavior scope. The current Gateway
persists run summaries, bounded events, and chart artifacts, while active
workers and `ManagedRun` state remain in process memory. The Agent persists
conversation records, but ordinary context includes completed runs only. The
desktop client already reconnects to an active run by `run_id` and sequence;
that transport recovery must remain separate from execution continuation.

The implementation remains local and single-user, uses SQLite as the durable
store, and must preserve bounded payloads, attachment authorization, safe
redaction, and the existing terminal-run contract. Existing runs may not have
checkpoint data and must continue to be inspectable and retryable.

## Goals / Non-Goals

**Goals:**

- Make a completed execution boundary durable and expose whether an
  interrupted run can be continued safely.
- Continue committed Agent work without re-running completed model, tool,
  chart, review, or publication operations.
- Keep terminal parent runs immutable and make continuation lineage visible to
  Gateway consumers and the desktop client.
- Handle crash windows conservatively: an operation with an unknown outcome is
  blocked from automatic replay and has a clear retry fallback.
- Keep recovery state bounded, sanitized, versioned, and compatible with
  existing sessions and event history.

**Non-Goals:**

- Resuming provider streaming at an individual token or network packet.
- Restoring Python call stacks, threads, or arbitrary process memory.
- Automatically continuing work after Gateway startup or client reconnect.
- Turning a terminal run back into `running`, or appending new events to a
  terminal parent run.
- Distributed worker leasing, cross-machine execution, or a new queue system.
- Solving general conversation compression; context compaction may consume
  checkpoint references later but is not part of this change.

## Decisions

### 1. Keep lifecycle status and recovery status separate

The public run lifecycle remains `running`, `completed`, `failed`, and
`interrupted`. Recovery is additional metadata, such as checkpoint identity,
phase, availability, and a bounded blocked reason. This avoids overloading
`paused` or changing the meaning of a terminal state.

An explicit resume creates a new child run with a new idempotency identity and
`continuationKind: resume`; a fresh retry creates a child with
`continuationKind: retry`. A common parent/run-lineage representation is
preferred over adding unrelated fields for every future continuation mode.
Existing `retryOf` data may remain as a compatibility projection while the
internal and new protocol representation uses the normalized relation.

The alternative of mutating the original run was rejected because it breaks
the one-terminal-outcome rule, event replay, and auditability. The alternative
of always resubmitting the original prompt was rejected because it silently
repeats completed work and is a retry, not a resume.

### 2. Use a recovery journal, not the SSE event stream, as the checkpoint source

The Gateway history layer will own a bounded recovery journal in the same
SQLite database. Conceptually it contains:

- one or more versioned checkpoints per run, including phase, next action,
  safe context references, digest, expiry, and recovery status;
- operation records keyed by run/operation identity, with kind, request
  fingerprint, `not_started`/`in_flight`/`completed` state, and a bounded
  result or artifact reference;
- parent/continuation metadata for resume and retry children.

The event stream remains a client-facing projection. Checkpoint publication
occurs only after the operation result and required artifact/review metadata
are durably committed. Events may announce the checkpoint afterward, but a
missing event must not erase a durable checkpoint.

The journal uses additive schema migration, bounded JSON, expiry cleanup, and
stable schema versions. It stores attachment, observation, candidate, and
artifact references rather than binary content, credentials, raw provider
responses, data URLs, or local paths.

### 3. Treat operation uncertainty as a first-class state

Every resumable work unit receives a stable operation identity. Recovery uses
the following policy:

```text
not_started  ──resume──▶ execute
completed    ──resume──▶ reuse durable result
in_flight    ──resume──▶ blocked unless replay is explicitly safe
unknown      ──resume──▶ blocked; offer fresh retry
```

Model responses are committed before their tool calls are dispatched. Tool,
render, review, and publication results are committed with their call or
candidate identity before the next Agent action is checkpointed. Candidate
publication remains idempotent by candidate/spec identity. If a crash occurs
between an operation start and its durable result, the system does not guess
whether an external side effect happened.

This conservative behavior gives up some automatic recovery in exchange for
avoiding duplicate chart generation, duplicate VLM calls, or misleading
publication state. A later change may add replay-safe contracts for individual
tools.

### 4. Rehydrate a continuation through an explicit Agent recovery input

The resumed Agent receives a validated recovery state rather than a synthetic
user prompt. It reconstructs bounded model messages from the parent’s safe
records, restores completed tool results and authorized visual references,
restores the layout context needed by geometry tools, and restores candidate,
review, and publication references when those records are durable.

The child gets its own Agent-memory run and event sequence. The interrupted
parent remains excluded from ordinary new-turn context, while only an
explicitly authorized resume can read its recovery context. If review state or
visual evidence cannot be rehydrated safely, the checkpoint is marked blocked
and the client is directed to retry.

### 5. Make resume explicit and user-controlled

The Gateway exposes recovery metadata through the existing run inspection
surface and adds an authorized resume operation with a required new
idempotency key. It validates session ownership, parent terminal state,
checkpoint version/expiry, and recovery status before creating a child.

Gateway startup still terminalizes previously active runs as interrupted, but
it preserves or derives recovery metadata. It does not start workers
automatically. The desktop client shows `继续执行` only for an available
checkpoint, keeps `重新尝试` as the from-scratch fallback, and continues to
use `重连` for transport-only recovery.

### 6. Prevent duplicate resume workers

Resume acceptance binds the new idempotency key to the parent checkpoint before
worker submission. A serialized session operation and the existing run
manager's active-run guard prevent concurrent conflicting continuations. If
worker submission fails, the child is terminalized with a durable reason while
its idempotency binding remains replayable, matching the existing run
reliability contract.

## Risks / Trade-offs

- **External call crash window** → Do not automatically replay `in_flight` or
  unknown operations; expose a bounded blocked reason and a fresh retry path.
- **Checkpoint and conversation records can diverge** → Make the recovery
  journal authoritative for resume eligibility, commit checkpoints only after
  required references exist, and mark the checkpoint unavailable on persistence
  failure.
- **Review manager state is currently process-local** → Persist enough
  candidate/review/publication metadata to rehydrate it; otherwise block
  recovery at that phase instead of claiming that a chart is publishable.
- **Checkpoint payloads can grow with tool traces** → store bounded sanitized
  messages and references, retain digests and operation summaries, and apply
  existing expiry limits.
- **Schema evolution can invalidate old checkpoints** → version every
  checkpoint, validate on resume, and fall back to retry for unsupported
  versions; old runs without checkpoints remain valid but non-resumable.
- **Parent/child runs may confuse the timeline** → expose an explicit relation
  and root grouping in the trace while preserving independent run sequences
  and terminal summaries.
- **User cancellation may occur during an operation** → record the last
  committed checkpoint, wait only for bounded cooperative cleanup, and mark
  recovery blocked when the operation outcome cannot be confirmed.

## Migration Plan

1. Add nullable lineage/recovery fields and additive checkpoint/operation
   tables without changing existing run or session records.
2. Deploy readers that treat missing checkpoint data as
   `recovery unavailable`, while existing reconnect, retry, and restart
   behavior continues to work.
3. Enable checkpoint writes and operation journaling for new runs, then expose
   resume only when a validated checkpoint is available.
4. Add the desktop controls and refresh the Gateway/client contracts after the
   server can return recovery metadata.
5. Validate restart, crash-window, duplicate-resume, chart publication, review,
   and legacy-run behavior before enabling the feature by default.

Rollback is additive: older code can ignore the new tables and fields, and
existing runs remain terminal or retryable. Checkpoint rows must not be
deleted during rollback because they are independent recovery metadata; a
future compatible version can consume them again.
