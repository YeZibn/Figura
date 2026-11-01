## Why

The runtime already preserves complete OCR and measurement results and exposes them through typed resource references, while the Prompt catalog is intended to stay small. Its OCR entries currently expose only availability and snippet count, and measurement entries recompute candidate counts while omitting useful committed quality and coverage details. The Agent therefore has too little information to decide which resource to read and which gaps matter.

## What Changes

- Define a compact, deterministic Prompt summary for OCR and measurement resources, retaining their existing typed references and keeping full observations in Runtime facts and `RunExecutionState`.
- Include bounded OCR text previews and measurement coverage, confidence, calibration, issue, and warning summaries sourced from committed results.
- State explicitly in the Prompt that the catalog is an index, and that exact text, coordinates, values, or calibration evidence must be fetched through `read_history` using the listed reference.
- Keep current tool-result messages, persistence records, resource IDs, image attachments, and history-reader behavior unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `run-execution-resources`: Specify compact, decision-useful OCR and measurement summaries in the Prompt catalog while retaining complete typed resource contents in `RunExecutionState` and authoritative Runtime facts.
- `session-context-retrieval`: Specify how an Agent uses a catalog reference to retrieve full OCR or measurement content with the existing `read_history` tool.

## Impact

- Prompt resource projection in `src/figura/agent/prompting/execution.py` and its instructions/assets.
- Existing `read_history` descriptions and workflow guidance only where needed to make the reference-to-full-content path explicit.
- Focused Agent resource and request tests, plus the two OpenSpec capability specs and Agent implementation documentation.
- No database/schema migration, new resource ID, new retrieval tool, API change, or change to the immediate full tool result.
