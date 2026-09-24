## 1. Unify the assembly validation boundary

- [x] 1.1 Make `assemble_spec` treat construction and semantic validation as one atomic operation, returning a generation-ready ChartSpec only when all blocking constraints pass.
- [x] 1.2 Preserve bounded, located diagnostics for failed assembly and verify that no partial ChartSpec is exposed as downstream-valid output.
- [x] 1.3 Audit assembly, rendering, review, and non-model callers so they reuse the same semantic rules, limits, issue codes, and severity behavior.
- [x] 1.4 Align the model-facing ChartSpec input schemas and descriptions with the runtime validation contract to prevent schema drift.

## 2. Simplify the Agent-facing tool contract

- [x] 2.1 Remove `VALIDATE_SPEC` from the registered Agent chart-tool catalog while retaining the shared Python validation capability for internal callers.
- [x] 2.2 Update the stable Agent prompt to require `assemble_spec` before structured chart output or chart generation, while allowing descriptive image answers without assembly.
- [x] 2.3 Update `assemble_spec`, `render_chart`, and related tool descriptions so successful assembly means structural/generation validation only, not visual verification.
- [x] 2.4 Confirm render and review boundaries still revalidate incoming specs independently when a caller bypasses the Agent-facing assembly flow.

## 3. Update behavioral coverage

- [x] 3.1 Add focused tests proving valid bar, line, pie, and scatter inputs return already validated ChartSpecs through `assemble_spec`.
- [x] 3.2 Add focused tests proving malformed points, missing axes, invalid ranges, and other blocking issues return bounded located errors without partial specs.
- [x] 3.3 Update registry and CLI tests to assert that `assemble_spec` is present and `validate_spec` is absent from the model-facing tool surface.
- [x] 3.4 Update chart restoration end-to-end tests so the model completes through one assembly gate without a separate validation turn.
- [x] 3.5 Verify downstream render/review and internal Python callers continue to use the shared validator after the model tool is removed.

## 4. Validate and document the change

- [x] 4.1 Run focused ChartSpec and Agent-loop tests, then the full pytest suite in the `agent` Conda environment.
- [x] 4.2 Run affected frontend build/smoke checks, `git diff --check`, and strict OpenSpec validation.
- [x] 4.3 Synchronize the completed delta specs to the main OpenSpec specifications and confirm the archived contract no longer requires a separate Agent-facing validation tool.
