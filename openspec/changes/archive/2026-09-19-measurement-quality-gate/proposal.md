## Why

当前图表测量工具虽然返回 `confidence`、`warnings` 和 overlay，但这些结果仍可能被模型直接用于 `assemble_spec`。系统缺少统一的测量生命周期、质量状态和使用门禁，导致基准线、坐标标定、系列关联或局部几何不可靠时，错误证据可能继续流入 ChartSpec 和生成流程。

现在需要先建立测量质量基础设施，让初次测量成为可追踪的候选证据，只有通过质量检查和必要复核的结果才能被当作确定性数据使用；具体的局部区域重测策略留给后续 change。

## What Changes

- 新增统一的测量证据生命周期，区分 `provisional`、`accepted`、`remeasure_required`、`partial`、`unsupported` 和 `failed` 状态。
- 为同一 `attachment_id + panel_id` 维护可追踪的 MeasurementSession 和 MeasurementAttempt，记录测量来源、质量检查、问题和 lineage。
- 为柱状图、折线图、饼图和散点图定义共享的质量审计契约，覆盖范围、几何、标定、覆盖、关联和可视证据完整性。
- 将测量结果中的阻断性问题结构化返回，不再只依赖普通 warnings 或顶层工具成功状态。
- 在使用测量证据组装 ChartSpec 前增加代码拥有的 measurement gate；未接受的测量结果不得直接作为确定性 ChartSpec 数据来源。
- 保留未使用测量工具时的直接视觉组装兼容路径，以及现有单图和生成审核链路。
- 为后续局部 TargetRegion、策略化重测和 VLM measurement review 预留稳定的状态、attempt 和证据引用接口，但本 change 不实现具体重测算法。

## Capabilities

### New Capabilities

- `measurement-quality-gate`: 统一测量证据状态、质量审计、会话追踪和 ChartSpec 使用门禁。

### Modified Capabilities

- `chart-understanding`: 测量工具结果必须暴露统一质量状态和结构化问题，且保留可追踪的测量尝试与证据范围。
- `chart-evidence-fusion`: 证据融合和 ChartSpec 装配必须区分候选测量与已接受测量，阻止未复核测量结果被静默当作确定事实。
- `chartspec`: 源图恢复得到的 ChartSpec 需要能够关联已接受的测量证据摘要，同时保持无测量工具时的兼容输入。

## Impact

- 影响 `src/chartagent/tools/chart/observation/` 下的四类测量工具及共享结果封装。
- 影响 Agent run-scoped memory、tool observation artifact index 和恢复/重连时的证据状态保存。
- 影响 `assemble_spec` 的输入检查和错误返回，但不移除现有单 ChartSpec 调用方式。
- 影响静态 workflow、动态 artifact prompt 和测量相关测试。
- 不新增第三方依赖，不改变 OCR、SAM 或图表渲染算法本身；局部重测和具体 VLM 复核策略另行规划。
