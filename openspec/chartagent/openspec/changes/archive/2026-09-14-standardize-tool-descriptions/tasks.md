## 1. Tool Metadata and Export Contracts

- [x] 1.1 Extend the lightweight `Tool` definition with bounded optional
  display-name and group metadata while preserving the existing four-field
  construction path and stable tool names.
- [x] 1.2 Add one canonical description/schema export path that passes through
  the complete one-paragraph description and preserves the authoritative JSON
  Schema without appending separate guidance fields.
- [x] 1.3 Add validation or normalization for tool metadata, including bounded
  description text, valid group identifiers, complete parameter property
  descriptions, explicit required fields, and safe `additionalProperties`
  behavior.
- [x] 1.4 Add a lightweight tool presentation catalog with Chinese names,
  optional English names, groups, and an English-name fallback for unknown
  tools.

## 2. Registered Tool Definitions

- [x] 2.1 Rewrite built-in file and JSON tool descriptions and parameter
  schemas to state purpose, applicable inputs, returned data, path/error
  boundaries, and usage guidance consistently.
- [x] 2.2 Rewrite attachment and chart-observation tool metadata, expose only
  authorized `attachment_id` inputs, and document the evidence and limitations
  of OCR, bar, line, pie, and scatter sensors.
- [x] 2.3 Rewrite ChartSpec assembly and validation metadata with explicit
  chart-type enums, point-field descriptions, required fields, bounded arrays,
  and guidance about when to assemble versus validate.
- [x] 2.4 Rewrite chart-rendering and generated-chart-review metadata to explain
  candidate status, review identifiers, publication constraints, and the
  difference between tool completion and review or publication success.
- [x] 2.5 Ensure every currently registered tool has a non-empty description
  that explains purpose, applicable and inapplicable situations, outputs, and
  limitations, plus a group and presentation metadata without changing its
  callable behavior.

## 3. Registration and External Surfaces

- [x] 3.1 Update Agent/OpenAI tool schema generation to use the canonical
  description and normalized parameter schema for every registered tool.
- [x] 3.2 Update authorized attachment adapters to derive their public
  identity and guidance from the source definition while replacing only the
  authorized input contract and bound callable.
- [x] 3.3 Update MCP-shaped manifest generation to use the same canonical name,
  description, and input schema as the Agent surface while retaining local
  presentation metadata where supported.
- [x] 3.4 Preserve compatibility for existing function-calling names,
  snake_case parameters, tool dispatch behavior, and legacy JSON result
  handling.

## 4. Contract and Regression Tests

- [x] 4.1 Add unit tests for optional metadata defaults, complete description
  export, presentation fallback, and invalid metadata.
- [x] 4.2 Add coverage that every built-in and chart tool has complete,
  actionable descriptions and explicit parameter schemas.
- [x] 4.3 Add parity tests proving Agent/OpenAI and MCP manifests use the same
  name, canonical description, and parameter contract.
- [x] 4.4 Add authorized-adapter tests proving image tools expose only
  `attachment_id`, keep their stable identity, and do not leak local paths.
- [x] 4.5 Add regression tests proving dispatch, structured results, visual
  evidence, generated-chart review calls, and existing tool names remain
  compatible.

## 5. Verification

- [x] 5.1 Run the focused tool-system, chart-tool, agent, review, and Gateway
  tests in the `agent` Conda environment.
- [x] 5.2 Run the complete Python test suite with `conda run -n agent python
  -m pytest -q` and resolve regressions.
- [x] 5.3 Run strict OpenSpec validation for the change and main specs, then
  run `git diff --check`.
