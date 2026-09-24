## 1. Resume Cursor Lineage

- [x] 1.1 Validate each Run's local entry count separately from the flattened parent prefix while preserving bounded lineage checks.
- [x] 1.2 Add recovery tests for `resume → child → resume`, including a valid three-Run lineage and an invalid or incomplete ancestor.

## 2. Final Answer Recovery

- [x] 2.1 Keep the cursor on the committed `final` action after writing a guarded final-answer entry, and resolve the answer from the entry referenced by that cursor.
- [x] 2.2 Make recovered finalization reuse the committed answer and converge through the existing per-Run event and terminal guards without a model request.
- [x] 2.3 Add interruption tests before final-answer commit, after final-answer commit, and before Gateway completion; assert committed responses are reused and finalization is idempotent.

## 3. Final Claim Scope

- [x] 3.1 Evaluate explicit artifact claims against their exact verification and promotion records, and generic chart claims against the current output scope rather than all historical statuses.
- [x] 3.2 Add fail-then-pass, pass-then-fail, exact failed-artifact reference, and mixed collection-child regression tests.

## 4. Tool Batch Artifact Context

- [x] 4.1 Apply the existing artifact-record bound in place so all tool calls update the shared Agent execution context.
- [x] 4.2 Add a multi-tool batch test that verifies the next model prompt receives all retained artifact records and that bound trimming keeps the shared list consistent.

## 5. Validation

- [x] 5.1 Run the focused execution-record, Agent, Gateway, and verification tests, then run the full Python test suite with `conda run -n agent python -m pytest -q`.
- [x] 5.2 Run `openspec validate repair-recovery-finalization --strict` and `git diff --check`.
