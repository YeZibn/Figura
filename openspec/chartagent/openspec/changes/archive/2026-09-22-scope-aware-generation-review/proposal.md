## Why

当前主链路已经能够拆解面板、测量证据、装配 ChartSpec 并触发生成图审核，但“用户要做什么”和“审核应当看什么”没有形成同一份任务合同。test4 暴露出两个直接问题：左侧面板转换成饼图时，审核仍把整张 dashboard 当作来源并要求右侧面板；测量观察、证据取舍和审核修复事件又缺少统一的候选上下文，导致过程看起来重复、失败后也无法安全地补证据。

现在需要把任务模式、来源范围、覆盖范围和修复权限绑定到同一个生成候选上，让主 Agent 负责选择与判断，工具负责提供受限证据，审核 VLM 只在正确的范围和语义模式下做一次无工具审核。

## What Changes

- 新增 source-linked generation context，明确任务是 `reconstruct`、`transform`、`summarize` 还是 `synthesize`，并绑定 `attachment_id`、`panel_id`、来源范围、代表系列和有意省略的系列。
- 让 `assemble_spec`、`render_chart`、候选元数据和审核链路传递同一份 generation context；同一面板的子集转换不再被误判为整张 dashboard 的完整重建。
- 将 VLM 审核改造成 scope-aware、mode-aware 的单次无工具审核：面板级候选只接收对应的局部来源图，审核规则根据任务模式判断来源保真度、类型转换和有意省略，而不是硬编码要求源图所有面板都出现在结果中。
- 明确审核结果的修复类型和门禁：`spec_only`、`evidence_needed`、`source_rebind`、`terminal`。只有 `evidence_needed` 才允许主 Agent 在同一 attachment/panel 范围内补充测量或 OCR 证据，然后重新装配并重新审核；未完成审核的候选不得发布。
- 收紧测量工具与 ChartSpec 装配的上下文契约，区分首次观察的 `observation_scope` 与已有 attempt 的 `measurement_target`，要求工具返回实际应用范围和可定位的证据引用，同时禁止静默跨 panel 或静默丢弃系列。
- 增强主流程和审核提示词，使模型先声明任务模式、来源范围和覆盖决策，再选择工具或装配；将动态工具约束、过程产物和 Run/Turn 状态注入现有四层提示词体系。
- 为候选、审核和证据修复补充稳定的 `candidate_id`、attempt、scope 和 repair kind 关联字段，保证后续前端可以把同一候选的过程聚合展示。

本 change 不包含完整的前端时间线重做、SAM/CV 架构替换、自动重复测量或新增审核工具；前端聚合展示可在后续 change 中基于本 change 的关联字段实现。

## Capabilities

### New Capabilities

- `scope-aware-generation-review`: 定义生成任务合同、面板范围、覆盖语义、模式化审核和有界修复门禁。

### Modified Capabilities

- `chart-generation`: 生成与审核候选必须携带任务上下文，按任务模式解释来源覆盖，并在审核修复期间保持发布门禁。
- `chartspec`: ChartSpec/装配请求需要能够表达来源范围、代表系列和有意省略，且保持单图与集合兼容。
- `chart-spec-figure-collections`: figure/collection 的来源和覆盖状态需要区分完整来源与用户请求子集。
- `review-gates`: 审核失败不再只有终止或 spec 重试；新增同范围证据补充的受限修复路径。
- `vlm-chart-review`: 审核输入使用精确来源面板和不可变任务合同，依据任务模式执行一次无工具判断。
- `measurement-quality-gate`: 测量质量结果与 scope/target 绑定，补测只能由主 Agent 按需决定且必须受来源范围约束。
- `layered-prompt-assembly`: 在现有四层提示词体系内注入 generation context、证据决策和审核修复状态。
- `execution-trace`: 为候选、测量 attempt、scope 和 repair kind 提供稳定关联，区分观察、证据决策、审核和发布状态。
- `panel-handoff-registry`: 审核和补测复用已持久化的 panel handoff/坐标范围，而不是回退到整张附件。
- `tool-system`: 测量、装配和渲染工具的 JSON Schema 与中文描述显式表达 scope、coverage 和修复上下文。

## Impact

- 主要影响 `src/chartagent/agent/loop.py`、`src/chartagent/review/`、`src/chartagent/tools/`、ChartSpec/figure 数据模型、提示词资源和执行事件协议。
- 需要调整 `assemble_spec`、`render_chart`、图表测量工具、候选审核管理器以及 VLM reviewer 的输入/输出序列化；兼容不带新上下文的直接 ChartSpec，但对 source-linked 生成采用保守的未知模式处理。
- 需要增加针对 panel-scoped transform、完整重建、证据补充门禁、上下文透传和单次 VLM 审核的 pytest 回归测试。
- 可能为后续前端改造提供新的事件关联字段，但本 change 不要求重做前端组件或视觉布局。
