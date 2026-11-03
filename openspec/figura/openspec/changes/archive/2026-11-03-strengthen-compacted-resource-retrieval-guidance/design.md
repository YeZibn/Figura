## Context

See proposal.md for the experiment and motivation. `AgentRequestBuilder` emits the compacted context summary and the current typed resource catalog as separate system instructions. The current guidance says to use a catalog `ref`, but it does not explain how that differs from summary `source_refs`. The `read_history` schema also documents only generic selector examples, while the resource shapes nest OCR and measurement results under `result` and ChartFigure under `figure`.

The current retrieval implementation already accepts a typed resource reference, returns its complete content when `selector` is omitted, and enforces the authorized Session/Run prefix. A selector with an unknown path can surface as `history_reference_unavailable`, the same public error used for an unavailable reference; this change therefore keeps selector recovery bounded and does not alter error contracts.

## Goals / Non-Goals

**Goals:**

- Make the difference between summary provenance references and resource-catalog references clear at the point where the model sees each.
- Give the Agent a deterministic choice: read the listed typed resource for exact structured data; search only when the matching reference is absent.
- Reduce selector mistakes through content-relative examples and a one-time no-selector recovery.
- Validate the wording with prompt-contract tests and the existing isolated resource-read pilot.

**Non-Goals:**

- Changing the catalog's projected fields, context compaction, canonical resource records, or resource authorization.
- Changing `read_history` selector semantics or error response shapes.
- Reading every catalog resource automatically, removing summary citations, or treating retrieved content as trusted instructions.
- Removing full tool results from ordinary uncompressed history.

## Decisions

### Put contextual reference priority beside the dynamic resource catalog

Extend the dynamic resource-catalog instruction in `execution.py` with the distinction between summary `source_refs` and catalog typed `ref` values. When a listed OCR, measurement, or ChartFigure is the source of exact requested data, the model should copy that complete `ref` object unchanged to `read_history`. Explain that summary refs still serve to retrieve the original supporting message or tool-result record.

Keep the general decision flow in `workflow.md`: matching resource in the current catalog means direct read; missing or unidentified resource means search. This places the context-specific rule beside its actual IDs while keeping the general fallback behavior in one stable workflow.

Alternative considered: place the entire rule only in `workflow.md`. That would make it available on every turn but separate it from the request-specific catalog and its references. Repeating the rule in both locations is justified because the dynamic instruction binds the rule to the visible `ref`, while the workflow defines when to search.

### Make selector examples reflect the returned resource shape

Update `read_history` parameter guidance with concrete content-relative paths: OCR snippets at `/result/snippets`, measurement warnings at `/result/warnings`, and ChartFigure data at `/figure`. State that omitted `selector` returns the complete referenced source and is the safe choice when a path is uncertain. Do not invent a compact projection or change the JSON Pointer implementation.

Alternative considered: require full reads for every resource. That would avoid path errors but could return unnecessary OCR or measurement data and increase prompt size. Known path examples preserve selective reads; full reads remain the fallback when the desired path is unknown.

### Bound selector recovery to one read of the same reference

If a selector call using a reference copied from the current catalog fails, retry once with the exact same reference and omit `selector`. Do not switch to a summary `source_ref` or start a search solely because a selected path failed. The retry remains within the same existing authorization check and cannot reveal content outside the caller's authorized prefix.

Alternative considered: change `read_history` errors to distinguish an unknown field path from an unavailable reference. That would require a runtime error-contract change and is not needed for the prompt-level recovery rule; keep it out of scope.

### Evaluate both natural choice and guided retrieval

Extend the existing isolated pilot with the same task prompts in the unprompted-choice and typed-reference-guided conditions. Record whether the first read uses the exact catalog ref, whether the read succeeds, selector failures/retries, and exact answer correctness. Preserve the existing three-resource targeted checks. Treat the 6-task natural-choice subset as descriptive rather than as a general reliability estimate.

Alternative considered: rely only on text assertions in unit tests. Those can verify the instruction contract but cannot show whether the model uses the reference distinction; keep both prompt tests and the small live-model pilot.

## Risks / Trade-offs

- **The model may over-read resources when compact summaries are sufficient** → Make direct reads conditional on needing exact content, bounds, provenance, or omitted values.
- **No-selector fallback may return large content** → Use it only after a field-selected read fails; prefer known selectors when the target path is explicit.
- **A field path example may drift when resource shapes change** → Keep examples covered by prompt/schema tests and update the OpenSpec contract with the implementation.
- **Summary source references still have legitimate uses** → State that they remain the path to original messages and tool-result records; do not demote them globally.
- **A tiny live-model sample can fluctuate** → Report per-case counts and compare descriptively with the saved baseline, without claiming statistical significance.

## Migration Plan

No stored data or runtime migration is required. The change affects only model-visible instruction text and selector descriptions. Existing Sessions and resource references remain valid. If the prompt causes extra reads or degrades task behavior, revert the instruction and tool-description edits; no historical data needs conversion.
