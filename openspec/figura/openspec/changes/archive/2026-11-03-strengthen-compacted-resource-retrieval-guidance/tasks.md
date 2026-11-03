## 1. Clarify retrieval choices in model guidance

- [x] 1.1 Update the dynamic resource-catalog instruction to distinguish summary `source_refs` from typed resource `ref` values and prioritize the matching catalog reference for exact resource content.
- [x] 1.2 Update `workflow.md` to use `search_history` only when the current catalog or summary does not provide a suitable reference, while retaining summary references for original messages and tool-result records.
- [x] 1.3 Update `read_history` selector schema guidance with OCR, measurement, and ChartFigure paths; explain full-read behavior and the one-time retry with the same reference and no selector after a failed selected read.

## 2. Verify prompt and retrieval behavior

- [x] 2.1 Add focused Prompt/schema assertions for reference precedence, content-relative selector examples, and the no-selector fallback; run the focused Prompt and history-retrieval tests in the `agent` environment.
- [x] 2.2 Rerun the isolated resource-read pilot on the same OCR, measurement, and ChartFigure questions, recording exact typed-reference selection, search use, selector failures/retries, retrieved content, and answer correctness.
- [x] 2.3 Compare results with the saved pre-change batch and document per-case results and limits without presenting the small sample as a general reliability estimate.
