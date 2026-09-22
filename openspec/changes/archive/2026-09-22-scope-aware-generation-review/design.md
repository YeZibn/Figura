## Context

See `proposal.md` for the motivation and scope. 当前链路已经有 PanelHandoff、ChartSpec/figure
集合、测量 evidence lifecycle、tool-free VLM review 和 publication gate，但它们之间主要
通过 `source` 文本、可选 provenance 或分散的事件字段传递信息。这样会出现两个边界错位：

1. 主 Agent 认为“左侧 panel 的 Actual 转成 pie”，审核器却只拿到整张 dashboard 和一个
   没有 panel provenance 的简单 ChartSpec，于是把无关 panel 或未选系列判成缺失。
2. 测量 warning、Agent 的 evidence decision、review failure 和 render retry 没有一个共同
   的 candidate context，修复动作因而不是严格的状态转换，容易出现隐式重复测量、跨 panel
   补证据或失败后直接结束。

本设计保留现有四层 prompt、单次无工具 VLM review、PanelHandoff 的授权边界以及
`assemble_spec`/`render_chart` 的单图兼容，不引入 SAM/CV 新依赖，也不把角色判断交给 OCR
或几何传感器。

## Goals / Non-Goals

**Goals:**

- 让 source-linked generation 使用一份可序列化、可审计、跨工具透传的 generation context。
- 让审核器拿到与任务一致的来源 panel crop，并按 `reconstruct`、`transform`、
  `summarize`、`synthesize` 解释 coverage。
- 将 review failure 变成有界的 `spec_only`、`evidence_needed`、`source_rebind`、
  `terminal` 状态机；补证据必须由主 Agent 显式发起且保持同 attachment/panel scope。
- 让 measurement、assembly、render 和 review 的结果都能关联到同一 candidate/attempt，
  为后续前端聚合提供稳定数据。
- 保持旧版直接 ChartSpec 能生成，并对缺失上下文的 source-linked 请求采取保守策略。

**Non-Goals:**

- 不在本 change 中重做前端时间线、review 卡片或完整的对话式 UI；这里只增加客户端可用的
  关联字段。
- 不替换 SAM/CV/OCR，也不把 OCR/CV 输出直接提升为业务 series role。
- 不执行工具内部自动重复测量；工具只报告候选和质量线索。
- 不增加 reviewer 可调用的工具，不把 reviewer 拆成多次 VLM 工具链。
- 不建设新的评测平台或改变真实图表评测数据布局。

## Decisions

### 1. 用独立的 generation context 连接意图与产物

在 ChartSpec/figure 的生成输入和 candidate metadata 旁增加结构化
`generation_context`，而不是把 intent 塞进 ChartSpec 的 title、metadata.source 或
provenance 自由文本。推荐的规范形状如下：

```json
{
  "mode": "transform",
  "source_scope": {
    "attachment_id": "att_opaque",
    "panel_ids": ["panel_left"]
  },
  "coverage": {
    "basis": "requested_subset",
    "source_series": ["Actual", "Target"],
    "represented_series": ["Actual"],
    "intentionally_omitted_series": ["Target"],
    "status": "complete"
  },
  "selection_basis": "agent_resolved",
  "goal_summary": "将左侧面板的 Actual 系列转换为饼图"
}
```

`ChartSpec` 继续负责“画什么数据”，context 负责“为什么画这些数据、来自哪里以及审核
要看哪里”。若一个 figure collection 有多个 child，每个 child 都拥有自己的 context；
collection 只负责组合，不重新解释 child 的 coverage。

选择这个边界而不是把所有字段直接加到 ChartSpec，是因为 ChartSpec 仍需支持用户直接
提交且不依赖附件的单图生成；同时 review/publication 需要读取任务语义，却不应改变图表
数据 IR 的基本职责。

### 2. 以 PanelHandoff 为唯一的来源范围解析入口

实现一个 scope resolver，将 context 的 `attachment_id + panel_ids` 解析成授权来源 crop、
坐标变换和内容 hash。解析优先使用 session 中有效的 PanelHandoff；hash、session 或
revision 不匹配时返回 stale/ambiguous。

review、same-scope measurement 和 source rebind 都使用同一 resolver。任何调用都不能在
resolver 失败后自行退回整张附件，因为这会把“范围未知”错误伪装成“全图范围”。只有
`synthesize` 明确不声称 source fidelity 时才可以没有 source crop。

备选方案是让 review 每次从原附件重新做 layout inspection。该方案会重新引入 test4 暴露
的全图误判、重复拆解和坐标不一致，因此不采用。

### 3. 把 review 规则按任务模式分派

review payload 固定包含：source crop（若适用）、candidate image、immutable ChartSpec、
generation context 和有限的 review history。VLM 仍然只做一次、不能调用工具，并严格返回
结构化 JSON。

- `reconstruct`：检查声明 panel/来源范围内的图表类型、系列、类别、数值和布局语义。
- `transform`：检查目标图表类型与变换后的 selected data；有意省略不作为缺失来源。
- `summarize`：检查声明的摘要范围、代表性和数字一致性，不要求还原全部视觉元素。
- `synthesize`：只检查候选自身的结构、数值和可读性，不宣称逐值还原源图。

review 输出规范化为 `decision`、`issues[]`、`repair_kind`、`candidate_id`、`attempt`。
每个 issue 至少带 `code`、`severity`、`location`、`reason` 和可选的 bounded target。
这样主 Agent 可以选择修复，而不是依据一段“审核失败”自由文本猜下一步。

### 4. 用有限状态机控制审核修复

把现有 review gate 扩展为以下状态转换：

```text
rendered -> review_pending -> passed -> publishable
                         \-> spec_only -> reassemble -> rendered
                         \-> evidence_needed -> same-scope evidence
                                                -> reassemble -> rendered
                         \-> source_rebind -> rebind panel -> new attempt
                         \-> terminal -> rejected
```

每条边都携带父 candidate/attempt 和 scope。`evidence_needed` 只能调用同一 attachment/panel
的 measurement 或 OCR evidence adapter，不能调用全图拆解、其他 panel 或无 scope 的工具；
补证据后必须重新 assemble、render 和 review。`source_rebind` 不允许在旧来源上继续补测，
必须创建新的 context/candidate attempt。

选择显式 repair kind 而不是复用一个 `review_failed` 布尔值，是为了将“缺数据”“spec
错误”“来源失效”“不可恢复”区分开，同时保持主链路阻塞直到状态机进入 passed 或 terminal。

### 5. 保持 Agent 主动决策，工具只返回证据

首次图表测量使用 `observation_scope`；已有 attempt 的局部补充使用
`measurement_target`。两者都返回 `effective_scope`、候选 refs、几何/数值质量和 warning。
工具不自动根据 warning 发起第二次调用，也不替主 Agent 把 legend swatch、Target 或
某个 series 升级成最终语义。

assemble 请求必须携带 selected/discarded refs、coverage basis 和 generation context。
如果 ref 的 panel、attachment 或 attempt 不一致，装配在进入 renderer 前失败。这样 VLM
可以通过观察和决策自主决定是否补测，但每一次补测都可追踪、可撤回、可重放。

### 6. 在现有四层 prompt 中放置 context，而不是继续增加层级

保持四层结构：

1. static responsibilities：中文职责、任务模式判断、证据决策矩阵和禁止事项；
2. dynamic tools：工具 schema、适用范围、scope/target 区别和当前可调用能力；
3. process artifacts：当前 panel handoff、measurement refs、ChartSpec、candidate image
   和 generation context；
4. Run/Turn state：candidate/attempt、repair kind、上一步结果、剩余预算和允许的下一阶段。

context 作为结构化对象进入 process artifacts，并在 Run/Turn state 中只放当前状态引用，
避免每轮拼接一份可能漂移的自然语言副本。review prompt 是独立的静态模板加候选 context，
不继承主 Agent 的工具列表。

### 7. 只增加最小的 trace 关联字段

在既有 lifecycle event envelope 中增加或统一 `candidate_id`、`attempt`、`source_scope`、
`coverage`、`repair_kind` 和 `parent_attempt`。不合并事件种类：
`measurement_observed`、`measurement_evidence_selected/discarded`、`chart_review_*` 和
publication status 仍然独立。前端可以先按 candidate 聚合，完整的展示重构留给后续 change。

## Risks / Trade-offs

- **[旧候选缺少 context]** → 将 source-linked 但字段缺失的候选标成 legacy/unknown，采用
  保守审核并阻止无依据的全图推断；直接 source-free ChartSpec 保持兼容。
- **[PanelHandoff 过期或坐标错误]** → 每次 resolver 校验内容 hash、session、revision 和
  bbox；失败时进入 source_rebind，不回退整图。
- **[模式判断错误]** → 主 Agent 必须先声明 mode；review 输出保留模式诊断；高风险的
  unknown/ambiguous context 进入澄清或 terminal，而不是自动猜测。
- **[repair loop 产生更多状态复杂度]** → 只允许四种 repair kind、固定状态转换和最大
  attempt 预算；每次子循环保存父 attempt 和结构化原因。
- **[上下文变大导致 prompt 成本上升]** → 传递稳定 refs 和 bounded summaries，完整测量
 结果通过授权引用获取；review 只接收当前 crop 和必要的 ChartSpec。
- **[工具 schema 与 callable 漂移]** → 将 scope/coverage contract 放入注册工具的同一
  schema/description，并增加 manifest、dispatch、越界调用的回归测试。
- **[前端暂时仍显示多个生命周期卡片]** → 先保证关联字段和语义不丢失；把卡片聚合与
  ChatGPT 风格时间线单独安排，避免在本 change 同时改动持久化和视觉投影。

## Migration Plan

1. 先增加 context、scope resolver、repair kind 和事件字段的数据模型/序列化，默认不改变
   旧 source-free ChartSpec 的路径。
2. 让 assemble/render/candidate metadata 先透传 context，再切换 review payload 使用
   resolver 的 panel crop；保留 legacy 诊断而不是静默兼容。
3. 更新主 Agent 与 reviewer 的中文 Markdown prompt 和工具描述，启用 mode-aware review
   以及 same-scope evidence repair gate。
4. 增加 test4 复现用例、reconstruct 对照用例、跨 panel 越界用例、旧输入兼容用例和单次
   VLM 调用用例；在 `conda run -n agent python -m pytest` 下验证。
5. 观察真实 run 的 candidate/attempt trace 后，再由后续前端 change 将同一 candidate 的
   lifecycle 聚合为一个可展开过程。

回滚时关闭新 repair kind 路由并保留 legacy review；context 和事件字段可继续读取但不参与
旧 publication 判定。不得通过回滚恢复“整图静默兜底”的行为而掩盖 scope mismatch。

## Open Questions

- 暂无会改变当前规格或状态机的未决问题。最大 attempt 数、单次 context/diagnostic 的
  字节上限和具体 issue code 可在实现任务中沿用现有配置约定，并通过测试固定。
