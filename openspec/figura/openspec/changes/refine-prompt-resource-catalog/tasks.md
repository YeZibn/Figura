## 1. Define compact catalog summaries

- [x] 1.1 Extend OCR Prompt projection with a bounded text preview and separate summary-preview truncation state.
- [x] 1.2 Extend measurement Prompt projection from committed coverage, confidence, calibration, issue, and warning fields; remove recomputed candidate counts and omit full observation scope.
- [x] 1.3 Clarify in the resource instruction and workflow that catalog entries are summaries and `read_history` retrieves exact content by typed reference.

## 2. Verify and document the resource boundary

- [x] 2.1 Add focused tests for summary fields, preview bounds, committed count fidelity, omission of full payloads, failed resources, and full-resource lookup.
- [x] 2.2 Update the Agent implementation documentation to distinguish the full persisted/runtime resource from its compact Prompt projection.
- [x] 2.3 Validate the OpenSpec change and run the focused Agent resource, request, retrieval, and prompting tests.
