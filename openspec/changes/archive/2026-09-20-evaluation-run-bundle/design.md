# Design: Evaluation Run Bundle

## Context

The current real-chart evaluation path produces bounded per-case reports in
`.chartagent/diagnostics/`, while the Gateway writes its SQLite history,
uploaded attachments, and run artifacts into the shared `.chartagent` data
root. A single evaluation can therefore be reconstructed only by joining
several directories and a database that also contains older runs. The
evaluation command also depends on a separately started Gateway, so the
evaluation output directory and the Gateway data directory can accidentally
diverge.

The change introduces an evaluation-level bundle. One invocation gets one
stable `evaluation_id` and one isolated data root. Every case report and every
Gateway-owned durable record produced by that invocation is traceable from a
small batch index and remains under that root.

## Goals / Non-Goals

### Goals

- Create the evaluation root before the first case is submitted.
- Keep the existing public HTTP Gateway boundary and provider selection rules.
- Make the normal executable evaluation path self-contained: start a local
  loopback Gateway with the evaluation root, run cases, and stop it reliably.
- Persist enough metadata to resume diagnosis of a completed, partial, or
  interrupted evaluation without scanning unrelated runs.
- Keep raw database contents and binary artifacts local while keeping the
  bounded reports safe to inspect or share.
- Preserve the existing report shape and case-level diagnostic behavior,
  changing the default location and adding batch-level aggregation.

### Non-Goals

- This change does not alter chart extraction, measurement, review, or
  rendering semantics.
- This change does not introduce accuracy scoring or a new benchmark dataset.
- This change does not copy the original source image twice. The uploaded
  attachment stored by the Gateway is the authoritative input bytes for the
  run; the manifest snapshot retains the original relative asset reference
  and hash.
- This change does not make the raw SQLite database or run artifacts a
  shareable report format.

## Decisions

### 1. Use an evaluation root under the canonical data root

The evaluation command creates:

```text
.chartagent/evaluations/<evaluation_id>/
```

The `evaluation_id` is generated once per invocation and is safe for use as a
directory name. The root is never reused for another evaluation. The existing
storage resolver remains the source of the canonical parent directory, so an
explicit `CHARTAGENT_DATA_DIR` or data-directory option still controls where
the bundle is placed.

The layout is:

```text
<evaluation_root>/
├── evaluation.json
├── manifest.json
├── summary.json
├── summary.md
├── sessions.db
├── attachments/
├── run-artifacts/
└── diagnostics/
    ├── <case_id>.json
    └── <case_id>.md
```

`evaluation.json` is the bounded batch index and lifecycle record. The
manifest snapshot and batch summaries are regular files so the bundle can be
inspected without knowing the repository's original absolute paths.

### 2. Managed Gateway is the default for a complete bundle

When the evaluation is executed as a real run, the evaluation coordinator
starts a Gateway subprocess on a free loopback port with
`--data-dir <evaluation_root>`. It waits for the existing health/readiness
endpoint, then uses the current `GatewayDiagnosticClient` over HTTP. This
keeps the same session/upload/run/poll path used in production-like testing;
the coordinator never calls the Agent or chart tools directly.

The coordinator owns the child process and always attempts graceful shutdown
in a `finally` path, with a bounded wait and a kill fallback. It records the
Gateway startup or shutdown error in `evaluation.json` if lifecycle handling
fails.

The existing explicit `--base-url` workflow remains available as a legacy
report-only mode for developers who already manage a Gateway. It is not
advertised as a complete isolated bundle unless the caller explicitly opts
into a matching evaluation data root. The default complete-evaluation path
must use the managed Gateway so the database and artifacts cannot silently
remain in the shared root.

### 3. Write a small, atomically updated batch index

At creation time the coordinator writes `evaluation.json` with status
`running`, provider/model metadata, manifest metadata, and an empty case map.
After each case reaches a terminal or interrupted state, it updates the index
through a temporary file followed by an atomic replace. Each case entry
contains only bounded metadata and relative paths:

- case id and source asset reference/hash;
- case status and timestamps;
- session id and run id when available;
- relative diagnostic report paths;
- first failure category/stage and a bounded error summary when available.

The final status is `completed` only when all selected cases finish normally.
An interrupted or partially executed batch is `partial`; an evaluation that
cannot start its Gateway or validate its manifest is `blocked`. The index is
therefore useful even when no case reaches a model call.

### 4. Keep the database as the raw event source of truth

The managed Gateway receives the evaluation root as its data directory, so
its existing `sessions.db`, attachment store, and run-artifact store are
automatically colocated. The implementation should not create a second raw
event-history format or duplicate large images. Case reports continue to use
bounded references into the Gateway history, and `summary.json` aggregates
those references rather than embedding full event payloads.

### 5. Snapshot and redact at the evaluation boundary

`manifest.json` is a sanitized snapshot of the selected manifest. It may
contain relative fixture paths, hashes, case metadata, and expected panels,
but must not contain API keys, authorization headers, `.env` contents, or
unbounded prompt/tool payloads. `summary.json`, `summary.md`, and per-case
reports follow the existing bounded-report redaction rules.

The SQLite database, attachments, and run artifacts are forensic/local data.
The bundle documentation and CLI output must make that distinction clear and
must never print their raw contents by default.

### 6. Preserve partial results on interruption

The coordinator installs an interruption/error cleanup path after the
evaluation root is created. It updates the batch index to `partial` or
`blocked`, flushes the report already produced for the current case when
possible, writes a best-effort `summary.json`/`summary.md`, and then shuts
down the managed Gateway. It does not delete the bundle. A later invocation
gets a new evaluation id; resume/retry semantics are not part of this change.

## Risks / Trade-offs

- **Gateway startup overhead:** each complete evaluation pays for a local
  process and readiness wait. This is accepted because it guarantees storage
  isolation; the legacy external-Gateway mode remains for quick development
  checks.
- **Large local bundles:** attachments, SQLite history, and generated
  artifacts can be large. The implementation should reuse existing artifact
  limits and report the final bundle path, but should not silently discard
  files needed to diagnose a run.
- **Subprocess cleanup:** a crashed coordinator could leave a Gateway child
  alive. The launcher must use process-group-aware cleanup where supported,
  bounded waits, and a final fallback so ports and child processes are not
  leaked.
- **Compatibility with existing scripts:** scripts that only expect
  `.chartagent/diagnostics/<case>.{json,md}` will need to follow the new
  bundle path. The report-only output option remains during migration and
  existing HTTP endpoints are unchanged.
- **Raw-data sensitivity:** colocating everything makes forensic analysis
  easier but also makes accidental sharing easier. The summary/report layer
  must remain bounded and the bundle documentation must explicitly classify
  raw subdirectories as local-only.

## Migration Plan

1. Add the evaluation bundle coordinator, lifecycle metadata, manifest
   snapshot, batch summaries, and atomic index updates.
2. Route the managed Gateway's data directory to the newly created evaluation
   root and keep the current Gateway client/session/run protocol unchanged.
3. Update the real-chart evaluation documentation and tests to use the
   bundle path; retain the explicit external-Gateway report-only path for
   compatibility.
4. Do not migrate or rewrite existing `.chartagent/diagnostics` reports and
   do not merge old shared `sessions.db` records into new bundles. New runs
   use the new layout; old data remains where it is until explicitly cleaned
   up by a separate operation.

Rollback is operational: use the existing external Gateway plus the current
report output option. Since the change does not alter chart tools or Gateway
HTTP contracts, rolling back the coordinator does not require a data
migration.

## Open Questions

None for this scope. Resume/retry from a partial bundle, retention policies,
and benchmark scoring can be specified as separate changes after the bundle
boundary is in place.
