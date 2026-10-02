## 1. Rewrite the four static prompt assets

- [x] 1.1 Clarify `agent.md` task intent categories, model/tool responsibilities, source selection, and when a task can finish without further observation or chart generation.
- [x] 1.2 Refine `evidence.md` to distinguish resource metadata, visible image blocks, OCR, measurement status, confidence, warnings, truncation, units, coordinates, partial coverage, and untrusted image text.
- [x] 1.3 Rewrite `workflow.md` as a conditional path from source selection through observation, evidence assessment, ChartSpec construction, Figure assembly, rendering, visual inspection, correction, and completion.
- [x] 1.4 Refine `response.md` with task-specific delivery rules for explanation, extraction, and chart generation, including estimates, missing evidence, failures, and unresolved limitations.

## 2. Align prompt rules with current Figura behavior

- [x] 2.1 Check the revised assets against the active tool descriptions, native Schemas, image-feedback lifecycle, and current ChartSpec/ChartFigure behavior; remove duplicated or contradictory instructions without changing those contracts.
- [x] 2.2 Review every scenario in the `agent-react-execution` delta against the four revised assets and confirm each describes behavior supportable by the current request and tool flow.
