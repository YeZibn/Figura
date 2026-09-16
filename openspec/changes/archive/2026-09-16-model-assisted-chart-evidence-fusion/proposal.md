## Why

当前图表 Agent 已经具备 OCR、柱状图、折线图、饼图和散点图的像素观测能力，但主链路仍容易把布局预检理解成固定前置步骤。这样既没有充分发挥多模态模型的语义理解能力，也可能让模型给出的错误布局先验反过来限制独立 CV 检测。

需要建立“模型主导理解、OCR/CV 按需提供证据、模型融合后装配”的协作链路，使简单图表可以直接装配，复杂或有冲突的图表才触发针对性观测，并保留可解释的不确定性。

## What Changes

- 增加面向图表恢复的证据融合与动态工具编排能力。
- 更新 Agent Prompt：模型先形成视觉理解和不确定点，再按需调用 OCR、几何传感器或布局检查器。
- 允许模型在证据充分时直接调用 `assemble_spec`，不强制所有图表经过 `inspect_chart_layout`。
- 将 `inspect_chart_layout` 定位为可选的布局假设验证器；其结果是软证据，不能覆盖独立像素检测。
- 保留现有四类图表传感器的独立检测能力，并统一工具证据的来源、置信度、警告和冲突表达。
- 在模型融合和 ChartSpec 装配前增加冲突识别约束，避免 OCR、CV 或模型猜测被静默当成事实。
- 增加简单图表、中文密集标注、横向/旋转布局、基准线冲突和多系列图表的链路验收覆盖。

## Capabilities

### New Capabilities

- `chart-evidence-fusion`: 多模态模型与 OCR/CV 观测工具之间的证据协同、按需调用、冲突处理和最终装配规则。

### Modified Capabilities

- `chart-understanding`: 图表恢复从固定或隐式预检转为模型主导、工具辅助的动态证据链路。
- `chart-layout-context`: 布局上下文从测量前置条件调整为可选、可验证、不可覆盖独立像素证据的软布局先验。
- `agent-loop`: Agent 需要维护工具证据和不确定性，支持按需观测后再装配，而不是隐藏地为每个几何调用自动运行布局预检。

## Impact

- 主要影响 `src/chartagent/runtime/prompts.py`、`src/chartagent/agent/loop.py`、图表工具的统一结果表达和布局上下文使用方式。
- 不改变附件授权边界、工具调用协议、现有 ChartSpec 基本字段、生成图表的 review/publication 规则。
- 不替换 rapidocr 或现有 CV 算法；需要在 `agent` Conda 环境中运行现有及新增测试。
- 需要更新 Python Agent 测试、真实图表链路测试和必要的 OpenSpec 主规格。
