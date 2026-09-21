## Context

当前四类图表测量工具已经接受可选的 `measurement_target`，主循环也会校验 attachment、panel、父 attempt 和重复目标；但模型可见的 target 契约仍主要围绕代码生成的 `repair_action`，而测量质量结果会被自动转换为 repair context 并推动后续流程。部分传感器在 focus 区域过小时还会扩大到基础搜索范围，导致“定向重测”不一定真正定向。

本设计遵循 proposal 和 delta specs：主 Agent/VLM 是测量证据的语义决策者；OCR、CV、布局和测量工具只提供可追溯观测；代码保留硬性来源、范围、幂等和装配门禁；最终生成图的独立 VLM 审核不在本次重构范围内。

## Goals / Non-Goals

**Goals:**

- 让主 Agent 在同一 ReAct 链路中看到测量候选、overlay、稳定引用和质量警告，并自主决定接受、舍弃或局部重测。
- 把局部重测建模为原图表测量工具的可选 focus 模式，而不是新增一个需要模型额外选择的通用工具。
- 让模型以 `B1`、`S1` 等轻量引用定位候选，避免传递完整历史几何和内部 session 数据。
- 让 `include`/`exclude` focus 真正约束测量搜索范围，并返回实际是否应用成功。
- 取消质量审计、恢复流程和 gate 对测量工具的自动重复调用，同时保留安全门禁和有界幂等。
- 让 `assemble_spec` 只消费主 Agent 明确选择、且通过 attachment/panel/attempt 校验的证据。

**Non-Goals:**

- 不新增独立的 `remeasure` 或 `validate_measurement` 模型工具。
- 不让 OCR、CV、SAM 或测量算法自行决定图表元素的语义角色或最终系列名称。
- 不在本次变更中重新引入 SAM；mask 可以由已有候选几何、bbox 或 polygon 在工具内部生成。
- 不改变最终生成图的 VLM 审核、候选发布和 publication gate 语义。
- 不要求所有清晰图表都经过测量工具；直接视觉装配路径继续可用。

## Decisions

### 1. 将局部重测作为原测量工具的第二种调用模式

保留 `measure_bars`、`extract_line_series`、`extract_scatter_points` 和 `extract_pie_slices` 的工具边界。第一次调用不带 target，执行基础观测；主 Agent 判断后再次调用相同工具并携带 `measurement_target`，执行局部补充观测。

模型可见的 target 使用轻量字段：

```json
{
  "refs": ["B7", "L1"],
  "mode": "exclude",
  "fields": ["bars.measure", "baseline"],
  "reason": "排除疑似图例色块并复查基准线"
}
```

当前的 `attachment_id`、`panel_id`、`parent_attempt_id`、源坐标和内部 fingerprint 由运行时根据当前 session 补全或校验。必要时才允许模型提供一个有界 bbox/polygon，避免让主 prompt 携带内部 lineage。

选择该方案是因为同一图表工具天然知道颜色、坐标系、基线和输出结构；独立 `remeasure` 工具需要再次选择图表类型，会复制参数契约并增加主 Agent 的决策负担。

### 2. 将质量审计改为观测报告，不再是自动修复控制器

保留 `audit_measurement` 产生的状态、issues、confidence、warnings、attempt lineage 和 focus suggestion。将 `repair_action` 视为主 Agent 的建议上下文，而不是立即执行的命令。

主循环在测量工具返回后只做三件事：保存结果、生成紧凑的模型观察、等待下一次主模型决定。它不再自动追加“根据 repair_action 重测”的消息，也不因为 `remeasure_required` 自动调用测量工具。

硬性校验仍在工具适配器、measurement session 和 assemble gate 中执行，包括：

- 当前 attachment 和 panel 归属；
- target 的结构、边界和来源尺寸；
- 父 attempt、重复 fingerprint 和 repair budget；
- focus 是否实际应用；
- assemble 引用是否来自主 Agent 选择的可接受证据。

### 3. 用稳定证据引用连接 overlay、结果和后续 target

每个测量 attempt 生成有界的模型引用：系列使用 `S1`、`S2`，柱体使用 `B1`、`B2`，图例或其他区域使用相同规则的候选引用。内部已有的 `series_1` 等 identity 可以保留在审计数据中，但模型可见层统一提供短引用和映射。

结构化结果只提供必要交叉引用：

```json
{
  "series": [{"ref": "S1", "label": null}],
  "refs": [{"ref": "B1", "kind": "bar", "series_ref": "S1"}],
  "warnings": ["series label unresolved"]
}
```

overlay 在对应图形旁显示 `[B1 | S1]`。完整 bbox、polygon、像素点和 attempt 详情继续保留在内部结果及运行记录中，只在 target 解析或调试需要时使用。`ref` 只能用于证据定位，不能自动成为最终图例或 ChartSpec 的 series label。

### 4. 由运行时把引用解析成 mask，并严格报告 focus 结果

主 Agent 可以引用已有候选请求 `include` 或 `exclude`。运行时从当前 attempt 的几何索引解析引用，生成局部 bbox 或组合 polygon，再传给具体测量算法。对没有现成候选的空白区域，允许有界源坐标区域作为 fallback。

所有测量工具统一返回：

```json
{
  "focus": {
    "requested": true,
    "applied": true,
    "mode": "exclude",
    "target_refs": ["L1"],
    "search_scope": "target_region"
  }
}
```

如果目标为空、越界、无法解析或没有证据，工具返回 `focus_empty` 或 `focus_insufficient`，不得悄悄回退到整个 panel。对于需要 panel 级基准线的复查，主 Agent 必须明确请求 `region_kind: baseline` 或提供 panel 级区域，工具不能根据小 bbox 自动推断扩大范围。

### 5. 主链路使用轻量状态机，避免隐藏审核循环

测量阶段状态流转为：

```text
INITIAL_MEASURED
        ↓
WAITING_FOR_MAIN_AGENT_DECISION
   ┌────┼─────────────┐
   ▼    ▼             ▼
 ACCEPT  FOCUS_CALL   DISCARD/STOP
   │       ↓
   │  FOCUSED_MEASURED
   │       ↓
   └── WAITING_FOR_MAIN_AGENT_DECISION
```

`WAITING_FOR_MAIN_AGENT_DECISION` 期间，主链路不能直接 assemble；但它不会自动创建重测调用。主 Agent 可以调用同一个测量工具带 target，也可以明确舍弃候选或停止。

`assemble_spec` 接受一个紧凑的 selected evidence refs（或等价的当前主模型选择结果），并验证它们属于当前可接受 attempt。若主 Agent 越过判断直接 assemble，系统只返回 `measurement_decision_required`，不自动修复。

### 6. 提示词只增加决策规则，不注入完整算法细节

静态职责层增加以下规则：

- 测量工具结果是候选证据，不是自动真值；
- 先依据 overlay 和 refs 选择/舍弃候选，再决定是否装配；
- warning 不会自动触发重测；
- 需要补充时，优先使用同一图表测量工具的 `measurement_target`；
- `S1`、`B1` 是证据引用，不是最终业务标签；
- 局部测量失败时，不得猜值或假设工具已经扩大搜索范围。

动态上下文只包含当前 panel、当前 attempt 的紧凑 refs、warnings、focus suggestion 和可用工具说明。完整历史 attempt 和原始几何留在运行记录中。

### 7. 兼容恢复、幂等和最终生成审核

恢复状态保存最近完成的 attempt、当前等待决策状态、selected refs、pending focus target 和 target fingerprint。重连后从等待主 Agent 决策处继续，不重复已经完成的基础测量或已成功执行的 focus target。

最终生成图仍按现有独立 VLM reviewer 和 publication gate 处理；测量证据决策完成只是允许进入 assemble，并不代表生成图已经通过审核。

## Risks / Trade-offs

- **[主 Agent 可能忽略 warning 直接装配]** → `assemble_spec` 保留 selected refs、attempt 状态和来源范围硬门禁；未完成决策时返回 `measurement_decision_required`。
- **[VLM 请求一个过大的 focus 区域]** → 对 bbox/polygon 做 panel 边界、面积和字段校验，并在结果中返回实际搜索范围；不满足 focus 约束时拒绝或返回 focus 不充分。
- **[模型反复请求相同 target]** → 使用 target fingerprint 和父 attempt 校验，重复请求返回幂等/拒绝结果，不创建新 attempt。
- **[引用标签被误当成业务名称]** → 在静态提示词、工具结果和 assemble 校验中分离 `ref` 与 `label`，并禁止 `series_数字` 作为最终可见系列名称。
- **[局部 mask 造成观测不完整]** → 工具明确返回 `focus_empty`、`focus_insufficient` 和覆盖信息，保留父 attempt；由主 Agent 决定是否换一个目标或停止。
- **[删除自动 repair context 后恢复链路缺少动作]** → checkpoint 保存 `WAITING_FOR_MAIN_AGENT_DECISION` 和紧凑 focus suggestion；恢复只唤醒主 Agent，不执行隐式工具调用。
- **[旧调用方仍提交旧格式 target]** → 适配器在内部保留旧字段解析和 lineage 校验，同时优先使用新的 refs/mode 语义；不合法或缺少可靠范围的请求明确返回结构化错误。

## Migration Plan

1. 先扩展统一的 `measurement_target` schema 和 attempt 引用索引，保持旧 bbox target 的解析兼容。
2. 为四类测量工具增加统一的 `focus` 输出和 overlay 引用；先覆盖测试夹具，确认局部范围不会回退到 panel。
3. 将质量审核输出从“自动修复上下文”调整为“证据建议”，保留内部 lineage、预算和重复 target 校验。
4. 修改主循环：删除自动 measurement repair message 和自动测量路径，改为把紧凑证据包反馈给主 Agent。
5. 修改 `assemble_spec` 门禁，使其消费主 Agent 的 selected refs，并验证 accepted attempt、来源和范围。
6. 更新主流程静态/动态提示词，增加标签引用、接受/舍弃/局部重测决策规则。
7. 增加主循环、工具 focus、断点恢复、幂等、装配门禁和最终生成审核不回归测试。

回滚时可以保留旧的 bbox target 解析和 measurement session 数据结构，关闭新的 model-facing refs/mask 分支；不得恢复自动重复全 panel 测量作为隐式 fallback。
