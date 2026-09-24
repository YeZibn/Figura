## Context

See `proposal.md` for the motivation. 当前 Agent 注册了 `assemble_spec` 与
`validate_spec` 两个 ChartSpec 工具；assembly 代码实际上已经复用共享的
生成校验，但模型仍然可以忽略外置 validator。图表生成和审核边界也需要
继续独立校验，不能依赖模型是否按顺序调用工具。

## Goals / Non-Goals

**Goals:**

- 让模型侧的 ChartSpec 构造成为单一、原子、不可跳过的 assembly 校验入口。
- 让失败结果携带有界且可定位的诊断，使模型能够修正输入后重新 assembly。
- 让 assembly、render、review 和非模型调用复用同一套语义约束。
- 保持图表取证阶段的自适应顺序，并明确结构校验不等于视觉真实性验证。

**Non-Goals:**

- 不把 OCR、CV、布局观测强制改成固定顺序。
- 不让 assembly 负责判断 ChartSpec 数值是否真的匹配源图像。
- 不删除代码侧的校验能力或 render/review 边界校验。
- 不在本 change 中扩展 ChartSpec 的字段模型或新增外部依赖。

## Decisions

### 1. Agent-facing surface has one atomic assembly tool

`assemble_spec` remains the only model-facing ChartSpec construction tool. It
normalizes typed inputs, constructs the IR, runs the shared semantic
validation, and returns either a valid ChartSpec dictionary or a bounded error
with located issues. The model never needs to remember a second validation
call.

**Alternative considered:** Keep `validate_spec` in the model tool list and
make the prompt require it after assembly. Rejected because prompt compliance
cannot guarantee that the critic is called, and it adds a mandatory tool-turn
dependency without improving the atomic assembly result.

### 2. Keep validation logic internal and reusable

The shared semantic validation remains a code-side capability used by assembly,
rendering, review, tests, and other non-model callers. Removing the Agent-facing
tool does not remove the safety checks at downstream boundaries. `render_chart`
must continue to reject invalid specs even when a caller bypasses assembly.

**Alternative considered:** Make `assemble_spec` call the `validate_spec` tool
through the registry. Rejected because tool-to-tool dispatch would couple the
builder to the Agent registry and make error handling harder; both operations
should call the same internal validator instead.

### 3. Treat assembly as transactional

An assembly attempt either returns a generation-ready ChartSpec or returns no
usable spec. All relevant semantic issues remain bounded and located in the
failure response. A successful response retains the existing ChartSpec
dictionary shape for compatibility, while its tool description states that
construction and validation have both completed.

**Alternative considered:** Return a partial spec plus validation warnings.
Rejected because downstream callers could mistake a partial candidate for a
safe generation input, and the existing generation boundary treats blocking
semantic issues as errors.

### 4. Prompt policy is conditional on structured output

The stable prompt SHALL require `assemble_spec` before the model returns a
structured recovered dataset or invokes chart generation. It SHALL continue to
allow descriptive image answers without ChartSpec assembly and SHALL continue
to let the model choose OCR, geometry, and layout evidence adaptively. The
prompt SHALL state that successful assembly proves structural/generation
validity only, not visual fidelity to the source image.

### 5. Remove the obsolete model-facing validation contract

The chart catalog and model-facing registry no longer include `validate_spec`.
Tests and tool-surface expectations are updated accordingly. The Python
function may remain importable for internal callers and compatibility, but it
is not presented as an Agent action.

## Risks / Trade-offs

- **[Risk]** Removing the visible critic reduces the model's ability to inspect a
  separately supplied spec. → **Mitigation:** require model-created structured
  results to pass through `assemble_spec`; keep the shared validator at render
  and review boundaries and retain internal callers for diagnostics.
- **[Risk]** Existing clients or tests may expect `validate_spec` in the tool
  list. → **Mitigation:** treat the registry change as an explicit breaking
  contract, update end-to-end expectations, and keep the internal Python
  validator available during migration.
- **[Risk]** The model may still infer incorrect values that are structurally
  valid. → **Mitigation:** preserve the evidence-fusion prompt, OCR/CV/layout
  warnings, and the rule that validation success is not visual verification.
- **[Risk]** Duplicated tool schemas can drift even after the tool is unified. →
  **Mitigation:** align shared schema constants and add tests that exercise the
  same invalid inputs through assembly and downstream validation paths.

## Migration Plan

1. Update the ChartSpec assembly contract, prompt, and tool descriptions.
2. Remove `VALIDATE_SPEC` from the Agent-facing chart catalog while retaining
   internal validation imports used by render/review/tests.
3. Update registry, loop, and end-to-end tests to expect one assembly gate and
   no separate validation turn.
4. Run the focused suite, full pytest suite, frontend checks when affected,
   `git diff --check`, and strict OpenSpec validation.

Rollback consists of restoring the prior catalog registration and tests; the
shared validator and downstream boundary checks remain compatible with either
tool surface.

## Open Questions

无。
