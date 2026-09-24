## 1. Evaluation bundle model and storage boundary

- [x] 1.1 Add an evaluation-bundle module that creates a unique safe `evaluation_id`, resolves `<canonical_data_root>/evaluations/<evaluation_id>/`, creates `diagnostics/`, and rejects reuse of an existing evaluation root.
- [x] 1.2 Implement the bounded `evaluation.json` lifecycle/index model with `running`, `completed`, `partial`, and `blocked` states, case records, relative artifact/report references, timestamps, and provider/model metadata.
- [x] 1.3 Implement sanitized manifest snapshotting and atomic JSON writes for the evaluation index and batch summary so interruption cannot leave a partially written metadata file.
- [x] 1.4 Add batch summary generation for `summary.json` and `summary.md`, aggregating per-case status, session/run references, first-failure facts, and bounded errors without embedding raw event history or secrets.

## 2. Managed Gateway execution

- [x] 2.1 Add a managed Gateway launcher for the evaluation path that selects a free loopback port, starts `python -m chartagent.gateway --data-dir <evaluation_root>`, and waits for the existing readiness endpoint.
- [x] 2.2 Integrate managed Gateway shutdown into normal completion, provider failure, exception, and interruption paths with bounded graceful waiting and a safe fallback cleanup; record lifecycle failures in the evaluation index.
- [x] 2.3 Route the existing `GatewayDiagnosticClient` through the managed Gateway URL while preserving the current HTTP upload/session/run/poll protocol, explicit provider requirement, and no-provider-fallback behavior.
- [x] 2.4 Preserve an explicit external-Gateway/report-only compatibility mode and make its limitations clear so it cannot be mistaken for an isolated evaluation bundle.

## 3. Case execution and persistence integration

- [x] 3.1 Update the evaluation CLI to create the bundle and manifest snapshot before the first selected case, associate every submitted session/run with the evaluation index, and write case reports under the bundle's `diagnostics/` directory.
- [x] 3.2 Ensure the managed Gateway receives the evaluation root so `sessions.db`, `attachments/`, and `run-artifacts/` are created in the same bundle without duplicating raw history or input bytes.
- [x] 3.3 Update the index and batch summaries after each case, including Gateway errors, timeouts, terminal failures, and cases that never reach submission; return a non-zero exit code when the batch is not fully completed.
- [x] 3.4 Preserve a usable partial bundle on SIGINT or unexpected exceptions, finalize best-effort summaries, and leave the root on disk for diagnosis without claiming successful completion.

## 4. Tests and verification

- [x] 4.1 Add unit coverage for evaluation-root isolation, safe identifiers, manifest snapshot redaction, atomic index updates, status transitions, relative path references, and rejection of root reuse.
- [x] 4.2 Add Gateway lifecycle integration coverage using a temporary evaluation root to verify readiness, `--data-dir` propagation, colocated database/attachments/artifacts, graceful shutdown, and cleanup after failure.
- [x] 4.3 Add evaluation CLI coverage for multiple cases, case-level report placement, batch summary contents, provider enforcement, external-Gateway compatibility, and partial/blocked outcomes.
- [x] 4.4 Run `git diff --check`, the focused evaluation/Gateway tests, and the full pytest suite with `conda run -n agent python -m pytest`; verify no generated evaluation bundle or secret is added to version control.

## 5. Documentation and rollout

- [x] 5.1 Update `docs/real-chart-diagnostic.md` with the one-command managed evaluation workflow, bundle layout, lifecycle statuses, and how to locate per-case reports and raw local forensic data.
- [x] 5.2 Document the legacy external-Gateway/report-only mode, its storage-isolation limitation, the canonical data-root override, and the fact that existing historical diagnostics are not migrated.
- [x] 5.3 Review CLI help and user-facing output to report the evaluation id/root and bounded completion status without printing absolute sensitive paths, prompts, API keys, or raw event payloads.
