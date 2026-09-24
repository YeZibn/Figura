## Why

当前 `validate_spec` 作为独立 Agent 工具暴露，模型可能在完成 `assemble_spec` 后忘记调用它，导致流程依赖 prompt 遵循而不是工具契约保证。需要把 ChartSpec 的构造与语义校验收敛为一个不可跳过的原子操作，同时保留代码侧的共享校验能力，确保生成和审核边界仍然安全。

## What Changes

- 将 `assemble_spec` 定义为模型侧唯一的 ChartSpec 构造入口，并在返回结果前自动执行完整的共享语义校验。
- 校验失败时，`assemble_spec` 只返回有界、可定位的 issues，不返回可继续使用的 ChartSpec。
- **BREAKING** 从 Agent 的注册工具面中移除独立的 `validate_spec`；它不再要求模型额外记忆或调用第二个校验工具。
- 保留共享校验函数供 `render_chart`、生成审核、非模型调用和测试复用，避免校验逻辑分叉。
- 更新系统 prompt、工具描述、OpenSpec 契约和端到端测试，明确结构化恢复及图表生成必须经过 `assemble_spec`，但校验通过不等同于图像事实已被视觉验证。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-loop`: 更新模型行为契约和模型可见工具面，使结构化图表流程使用单一原子 assembly 校验入口。
- `chart-understanding`: 将 ChartSpec assembly 与语义校验合并为一个模型侧能力，并移除独立 `validate_spec` 工具契约。

## Impact

- 影响 `src/chartagent/tools/chart/specification.py`、图表工具注册 catalog、Agent runtime prompt，以及生成/审核边界的校验调用。
- 影响 Agent-facing tool list 和相关端到端测试；直接使用 Python 校验函数的内部调用保持可用。
- 不新增依赖，不改变 OCR、CV、布局观测的自适应顺序，也不把结构校验误认为视觉真实性校验。
