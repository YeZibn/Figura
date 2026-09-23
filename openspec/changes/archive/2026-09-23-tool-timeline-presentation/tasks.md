## 1. Unify tool identity and status projection

- [x] 1.1 Make every tool-backed timeline headline prefer the existing bilingual `tool_label`, including distinct assembly and rendering tools, while keeping phase as secondary context.
- [x] 1.2 Map recognized tool-call, tool-result, skipped-tool, and generated-chart states by event kind; represent missing or unrecognized states explicitly as unknown.
- [x] 1.3 Localize concise status summaries without changing review or publication semantics; retain raw status values only in technical details.

## 2. Make tool details opt-in

- [x] 2.1 Initialize tool-step disclosures as collapsed for every lifecycle state and preserve the user's manual disclosure choice as correlated events update the step.
- [x] 2.2 Keep the collapsed summary informative with tool name, timestamp, localized status, truncation indicator, and bounded failure reason when present.
- [x] 2.3 Keep bounded arguments, results, observations, and technical events available after expansion; keep generated charts visible in the separate result area.
- [x] 2.4 Verify evaluation history uses the same timeline presentation without adding duplicate tool-call/result entries or evaluation-specific status inference.

## 3. Add frontend regression coverage

- [x] 3.1 Cover assembly versus render headlines and known, missing, and unrecognized status values in timeline projection tests.
- [x] 3.2 Cover default-collapsed details for running, completed, blocked, and failed steps, including visible failure summaries and manual expansion.
- [x] 3.3 Cover ordinary run and evaluation history parity, truncated tool results, and independent generated-chart visibility.
- [x] 3.4 Run `npm run build` and `npm run smoke` from `frontend/`.
