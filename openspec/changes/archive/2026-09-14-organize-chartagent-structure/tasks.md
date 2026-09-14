## 1. Establish Canonical Low-Level Boundaries

- [x] 1.1 Add `chartagent.spec.identity` and move the stable `chart_spec_digest` implementation there, retaining the existing review import as a re-export.
- [x] 1.2 Create `chartagent.tools.core` with canonical definition, registry/dispatch, result, and presentation modules; preserve the current `chartagent.tools` and direct module exports through thin shims.
- [x] 1.3 Create `chartagent.tools.integrations` and move OpenAI and MCP projection logic behind canonical integration modules, preserving current exporter behavior and import paths.
- [x] 1.4 Add focused unit coverage for canonical/compatibility imports and assert that tool schema normalization, dispatch, result serialization, and exporter output remain unchanged.

## 2. Reorganize Built-In and Chart Tools

- [x] 2.1 Rename the built-in implementation modules to capability-oriented `filesystem.py` and `json.py`, add `builtins/catalog.py`, and keep `tools.builtin.files`, `tools.builtin.data`, and `tools.builtin.register` as re-export shims.
- [x] 2.2 Create `tools.chart.observation` and move OCR, bar, line, pie, scatter, shared Cartesian helpers, and overlays into capability-oriented modules without changing sensor callable names or payloads.
- [x] 2.3 Move chart specification tools to `tools.chart.specification`, chart rendering/audit logic to `tools.chart.rendering`, and retain `tools.chart.spec_tools` and `tools.chart.generation` as compatibility exports.
- [x] 2.4 Add `tools.chart.catalog` as the single chart registration owner; retain `tools.chart.register` as a re-export and ensure each tool name is registered exactly once.
- [x] 2.5 Add `tools.adapters.chart` for attachment-authorized chart wrappers and update chart registration to depend on the adapter boundary rather than embedding authorization in catalog logic.
- [x] 2.6 Run the existing built-in and chart tool tests after this phase and compare registered tool names, canonical schemas, and serialized observations with the pre-migration behavior.

## 3. Split Attachment and Review Domains

- [x] 3.1 Convert `chartagent.attachments` into a package with registry, policy, and metadata modules; keep `AttachmentRegistry`, constants, and existing exports available from `chartagent.attachments`.
- [x] 3.2 Move the `load_image` Tool factory to `tools.adapters.attachment`, leaving `AttachmentRegistry` responsible only for registration, authorization, integrity validation, lookup, and metadata.
- [x] 3.3 Convert `chartagent.review` into a package with models, policy, evidence, evaluator, and manager modules; preserve all existing review enums, dataclasses, helpers, and manager exports.
- [x] 3.4 Move the `review_generated_chart` Tool factory to `tools.adapters.review`, keeping review lifecycle state and transitions owned by `ChartReviewManager`.
- [x] 3.5 Add a narrow evaluator sensor-provider boundary or lazy compatibility provider so review can collect chart evidence without importing the review manager from chart sensors.
- [x] 3.6 Add review and attachment regression tests covering candidate creation, mandatory review states, publication decisions, evidence limits, authorization, and compatibility imports.

## 4. Split Runtime and Agent Composition

- [x] 4.1 Convert `chartagent.runtime` into `factory`, `models`, `prompts`, and `readiness` modules; preserve `AgentRuntime`, `create_agent_runtime`, `probe_agent_readiness`, and `AGENT_SYSTEM_PROMPT` exports.
- [x] 4.2 Update the runtime composition root to register built-in tools, attachment/review adapters, and chart tools through the canonical catalogs in one deterministic order.
- [x] 4.3 Convert `chartagent.agent` into focused loop, message, observation, review-gate, and tool-schema modules while preserving the `Agent` constructor, turn behavior, tool-call protocol, and public helper exports.
- [x] 4.4 Update CLI, Gateway, multimodal, package-level exports, and internal imports to use canonical ownership modules while leaving compatibility paths intact.
- [x] 4.5 Verify a fresh interpreter can import canonical and compatibility paths without order-dependent circular-import failures, and verify runtime construction still works with injected test constructors.

## 5. Structural and Contract Validation

- [x] 5.1 Add structural import tests that exercise the package matrix, assert compatibility aliases resolve to canonical implementations, and check that domain services do not import model-facing adapter factories.
- [x] 5.2 Add registry contract tests for unique tool names, stable descriptions and parameter schemas, group/display metadata, OpenAI projection, and MCP manifests.
- [x] 5.3 Add lifecycle contract tests confirming generated-image review hooks, trace event names, candidate/review/publication states, and frontend-facing result fields are unchanged.
- [x] 5.4 Run focused Python tests for tools, chart generation, chart review, sessions, Gateway, CLI, and multimodal behavior; fix only migration regressions.
- [x] 5.5 Run `conda run -n agent pytest -q`, `git diff --check`, and the applicable frontend build/smoke checks; record any pre-existing unrelated failures separately.
- [x] 5.6 Validate the completed change with `openspec validate organize-chartagent-structure --type change --strict` and document the canonical-to-compatibility module map for future cleanup work.
