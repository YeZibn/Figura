## Why

当前测量质量链路把“发现证据不确定”和“决定自动重测”耦合在代码审核器中，导致主 Agent 看不到完整候选关系，也可能重复执行相同或过大的 panel 测量。需要让主 Agent/VLM 直接负责测量证据的选择、语义判断和是否补充观测，同时保留代码侧的来源、范围、幂等和装配安全门禁。

## What Changes

- **BREAKING** 将测量后的语义判断收回主 Agent，不再由独立测量审核器自动触发 `repair_action` 或重复重测。
- 为柱状图、折线图、散点图和饼图测量工具统一支持可选的局部目标参数；局部重测仍调用原图表测量工具，不新增通用 `remeasure` 工具。
- 为测量候选提供轻量、稳定的证据引用标签（例如 `B1`、`S1`），并在 overlay 与结构化结果之间保持一致，供 VLM 选择候选和请求局部重测。
- 允许 VLM 通过候选引用请求 `include` 或 `exclude` mask/区域；控制层负责解析当前 attempt 的几何、补全 lineage，并拒绝跨附件、跨 panel、重复或越界目标。
- 将测量质量审计调整为证据观测和硬性安全校验：warning、置信度和冲突不再自动决定重测；未被 VLM 选择的 provisional/partial 证据不得进入装配。
- 保留装配前的防御性门禁，要求 `assemble_spec` 只能引用当前 panel 中被主 Agent 选择且通过必要硬校验的测量证据。
- 定向测量必须真正限制搜索范围；不得在局部目标无结果时静默回退到整个 panel。
- 保留最终生成图的独立 VLM 审核与发布门禁；本变更只重构测量阶段的决策权和证据恢复流程。

## Capabilities

### New Capabilities

无。本变更是在现有测量质量、证据融合、Agent 主循环和工具参数契约上增加主链路证据决策能力。

### Modified Capabilities

- `measurement-quality-gate`: 将测量审核从自动修复决策调整为 VLM 驱动的证据状态、局部目标和硬性门禁。
- `chart-evidence-fusion`: 增加带引用标签的候选选择、主 Agent 主动局部观测以及证据引用装配规则。
- `agent-loop`: 移除自动测量修复消息和测量重试分支，允许主 Agent 在同一主链路中自主选择接受、舍弃或定向重测。
- `tool-system`: 扩展图表测量工具的统一 `measurement_target` 参数和轻量证据引用输出契约。

## Impact

- 影响 `src/chartagent/measurement.py`、`src/chartagent/agent/loop.py`、`src/chartagent/review/adapters.py`、`src/chartagent/review/gates.py` 以及四类图表测量工具。
- 影响主流程静态提示词、动态测量观察结果、工具 JSON Schema、`assemble_spec` 的测量证据校验和运行恢复状态。
- 需要更新测量质量、主循环、工具 schema、局部 mask、幂等恢复和图表理解相关测试。
- 不新增外部依赖，不改变最终生成图 VLM 审核的职责；继续使用 `agent` Conda 环境运行 Python 测试。
