## Why

The resource catalog already exposes typed references and the Prompt says to use them with `read_history`, but the pilot showed the Agent can still choose a summary `message` or `tool_result` reference instead of the matching resource reference, or guess an invalid selector path. Explicit retrieval priorities and safe selector guidance should make exact reads more reliable after compaction.

## What Changes

- Distinguish summary `source_refs`, which trace the summary's supporting messages or tool results, from typed resource-catalog `ref` values, which retrieve complete structured resources.
- When an exact OCR, measurement, or ChartFigure resource is listed, direct the Agent to copy its typed reference into `read_history`; reserve `search_history` for resources or history locations that are not present in the current catalog.
- Clarify known content-relative selector examples, the default full-read behavior when a path is uncertain, and a bounded fallback for selector-path failures.
- Add focused prompt-contract coverage and rerun the resource-reading pilot to compare reference selection, retrieval, and answer accuracy.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `session-context-retrieval`: specify how model-visible guidance chooses between summary source references, typed resource references, and search, and how it safely selects or retrieves full content.

## Impact

- Prompt guidance in `src/figura/agent/prompting/assets/workflow.md` and the dynamic resource instruction in `src/figura/agent/prompting/execution.py`.
- `read_history` selector examples in `src/figura/tools/implementations/history.py` if needed to keep tool-schema guidance aligned.
- Focused Prompt and retrieval tests, the `session-context-retrieval` OpenSpec delta, and the existing isolated resource-read pilot.
- No resource identity, persistence, API, selector behavior, or retrieval authorization changes.
