## 1. Agent prompt and review obligation

- [x] 1.1 Refactor `src/chartagent/runtime/prompts.py` into static sections for role, evidence, tool choice, chart generation, review obligations, and final-answer claims without duplicating tool descriptions.
- [x] 1.2 Add bounded structured review-gate context containing the required action and pending candidate/review/publication fields.
- [x] 1.3 Update the final-answer gate to preserve the static prompt, inject the structured obligation, and return an explicit incomplete result when the budget ends.
- [x] 1.4 Register the existing `review_generated_chart` tool during normal runtime composition while preserving its current name, description, parameters, and callable behavior.

## 2. Existing lifecycle projection

- [x] 2.1 Correct `chart_review_started` emission and payload semantics without changing event names or review-manager transitions.
- [x] 2.2 Add independent tool, candidate, review, and publication fields to lifecycle projections where the existing domain data already provides them.
- [x] 2.3 Connect the existing bilingual tool catalog to the frontend execution timeline and add missing Simplified Chinese lifecycle labels with English fallbacks.
- [x] 2.4 Update generated-chart presentation to distinguish tool completion, review state, and publication state using existing fields.

## 3. Regression and verification

- [x] 3.1 Add focused Agent tests for static prompt behavior, stable review-tool availability, structured gate context, and final-answer blocking.
- [x] 3.2 Add trace and frontend/protocol regression coverage for review-start semantics, independent statuses, bilingual tool labels, lifecycle labels, and unknown fallbacks.
- [x] 3.3 Verify existing tool definitions, schemas, review algorithms, event names, artifact references, and compatibility paths remain unchanged.
- [x] 3.4 Run `conda run -n agent pytest -q`, frontend build/smoke checks, `git diff --check`, and strict OpenSpec validation.
