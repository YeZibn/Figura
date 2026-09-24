## Context

当前系统已有两套成熟但分离的审核能力：`measurement.py` 维护测量 attempt、质量问题和定向重测；`ChartReviewManager` 维护候选图、ChartSpec digest、VLM 审核和发布状态。测量引用目前主要在 `assemble_spec` 处做门禁，生成图审核主要在渲染后同步执行并由生成图 review gate 约束。Agent loop、checkpoint、普通运行前端和评测前端还没有共享的审核投影。

本设计遵循已有的 source/panel/candidate lineage、bounded retry、事件回放和安全资源引用约束。审核调用可以同步等待结果，但不得用长事务或阻塞事件循环的方式实现；这里的“阻塞”指业务阶段不可越过审核门禁。

## Goals / Non-Goals

**Goals:**

- 让测量审核和生成图审核都成为主链路的强制门禁。
- 共享审核状态、证据引用、attempt lineage、重试预算、修复动作、事件和前端展示。
- 保留测量代码审核与生成图确定性检查/VLM 审核的领域独立性。
- 在模型批量工具调用、最终回答、发布、checkpoint 恢复和评测展示中都不允许绕过门禁。
- 让修复成为有界且可恢复的审核子循环，而不是普通流程继续。

**Non-Goals:**

- 不把测量质量判断改成 VLM，也不在生成图审核阶段重新调用 OCR、CV 或测量工具。
- 不在本 change 中重新设计 ChartSpec、测量算法、VLM JSON 字段或渲染器。
- 不把审核状态持久化为新的终态 RunStatus；运行终态继续由现有 run lifecycle 管理，审核阻塞使用独立 projection。
- 不把评测工作区改造成可写的重新执行控制台。

## Decisions

### 1. 用统一 ReviewCoordinator + 领域 Adapter，而不是合并两个审核器

新增共享审核协调层，负责审核记录、状态迁移、幂等键、attempt/lineage、重试预算、事件和门禁；领域 Adapter 只负责生成自己的审核输入和决定：

- `MeasurementReviewAdapter`：消费测量结果，调用现有质量审计，生成 measurement repair target。
- `GeneratedChartReviewAdapter`：消费候选图和 ChartSpec，组合现有结构检查与 tool-free VLM 结果，生成候选修复诊断。

共享审核记录至少包含 `review_id`、`subject_type`、`subject_id`、`parent_id`、`run_id`、来源引用、状态、attempt、预算、issues、repair_action 和时间信息。领域详情放在受限的 `details` 中，避免把两种审核强行建模成同一套检查项。

备选方案是让 Agent loop 分别判断两个审核结果；该方案会继续产生“一个审核有门禁、另一个只靠提示词”的不一致，因此不采用。

### 2. 用独立 ExecutionGate 表达阻塞，不扩展终态 RunStatus

运行摘要和 checkpoint 增加统一的 `execution_gate` 投影，状态至少为：

```text
open → reviewing → open
                  ↘ repair_required → reviewing
                  ↘ failed/exhausted
```

`RunStatus` 仍只表达 `running/completed/failed/interrupted`。运行处于 `running + reviewing` 或 `running + repair_required` 时，后台可以继续处理允许的审核动作，但不得推进普通主链路。不可恢复审核失败或预算耗尽时，使用现有失败终态和明确的 `review_failed`/`review_retry_exhausted` 终止原因。

这样既能让前端展示“审核阻塞”，又不会把非终态的等待状态混入现有 reconnect、interrupt、resume 语义。

### 3. 在每个工具结果边界执行门禁，并截断同批次后续调用

Agent loop 按以下顺序处理工具结果：

1. 持久化工具结果和安全证据引用。
2. 对测量结果立即提交测量审核；对生成图结果立即完成候选审核。
3. 原子应用审核决定并更新 `ExecutionGate`。
4. 只有 gate 为 `open` 才执行当前批次的下一个工具调用。
5. gate 为 `repair_required` 时只给模型审核修复上下文，并只允许匹配的定向重测或 ChartSpec 修正流程。

如果一个模型响应包含多个工具调用，阻塞发生后尚未开始的调用不执行，记录为 `not_started` 并写入 checkpoint。`assemble_spec` 和发布转换仍保留最后一道代码校验，形成“loop 门禁 + 领域防御门”的双层保护。

### 4. 审核调用同步等待，但审核状态先持久化

提交审核时先写入 `reviewing` 事件和 checkpoint，再执行确定性检查或 VLM 请求；应用结果时使用 subject、attempt/candidate 和 ChartSpec digest 做条件匹配。审核调用不包在 SQLite 长事务中，避免 provider 慢调用锁住运行历史。

若进程在审核调用期间中断，checkpoint 保持 `reviewing`/`uncertain`，恢复只能依赖已有的幂等审核结果或进入明确的重试路径，不能直接认为通过。相同 subject、attempt 和审核意图使用稳定幂等身份，防止重连重复审核和重复发布。

### 5. 修复是两类明确的受控动作

- 测量审核：只允许同一 attachment、panel、当前父 attempt 和 target 的定向重测；新 attempt 必须重新审核。
- 生成图审核：只允许根据 bounded diagnostics 修改 ChartSpec 并生成新 candidate；旧 candidate 永远不可发布。

修复上下文必须包含 `review_id`、父对象、受影响字段/区域、下一步动作和剩余预算。普通工具或模型最终文本不能将 `repair_required` 解释为已放行。

### 6. 统一协议和前端组件，保留旧事件兼容映射

Gateway/trace 新增统一的 review 事件和 run projection，包含 `review_type`、`review_id`、`subject_id`、`state`、`blocking`、`attempt`、`issues`、`next_action` 和证据引用。原有 `measurement_repair_*`、`chart_review_*` 事件暂时保留，由 Gateway 或前端归一化到统一 `ReviewRecord`，避免破坏历史 bundle 和旧客户端。

React 侧建立共享 `ReviewCard` 和 `ReviewTimelineItem`：统一显示审核中、需要修复、通过、带警告、失败、耗尽；测量审核展开 target/attempt/panel，生成图审核展开 candidate/ChartSpec/VLM checks。评测工作区只复用这些只读组件和安全资源引用，不触发新的审核。

### 7. 恢复以 gate 为中心，而不是只恢复消息上下文

checkpoint 除已有的 panel、candidate、measurement session 和 operation state 外，保存活动 `ExecutionGate`、审核 attempt、修复预算、父引用和下一动作。resume 创建子 run 后继承这些受限引用；只有已提交的审核通过结果才可释放下一阶段。未开始的工具可继续，审核或发布处于 uncertain/in-flight 时不得自动重放，除非已有明确幂等契约。

## Risks / Trade-offs

- **[Risk]** 审核作为硬门禁会增加单次运行延迟。→ 使用有界 timeout、持久化中间状态和明确的 repair/retry 预算；正确性优先于无审核继续。
- **[Risk]** loop 截断同批次工具调用可能让模型已声明的后续调用不再执行。→ 将未开始调用记录为 `not_started`，在 gate 释放后由新的模型轮次重新决定，不伪造为已完成。
- **[Risk]** 统一协议可能造成历史事件兼容问题。→ 保留旧事件，增加归一化层；历史记录缺少 gate 时显示明确的“历史能力有限”，不推断通过。
- **[Risk]** 审核结果与候选/测量 attempt 不匹配会产生错误放行。→ 应用决定前强制校验 subject、lineage、来源和 digest，并采用原子状态转换。
- **[Risk]** 运行失败状态与“审核修复中”容易混淆。→ 使用独立 `ExecutionGate`；只有不可恢复失败或耗尽才写入终态失败。

## Migration Plan

1. 先新增共享审核模型、状态转换和协议归一化，不改变现有审核判断逻辑。
2. 接入测量审核，在 assemble 防御门之前增加 loop 级门禁和同批次截断。
3. 接入生成图候选审核，统一发布门禁、修复 lineage 和失败终态投影。
4. 将 gate、审核事件和 checkpoint 投影接入 Gateway，再接入普通运行前端。
5. 评测工作区复用同一 timeline/card，并补充完整链路回归测试。
6. 验证历史运行、旧事件和旧客户端兼容后，再将统一事件作为新客户端的首选数据源。

回滚时保留现有领域审核和 `assemble_spec`/publication 防御门，仅关闭统一前端投影与 loop 级强门禁；不得通过回滚发布未经审核的候选或测量证据。

## Open Questions

无。`pass_with_warning` 是否放行由现有领域策略决定，但放行必须经过统一门禁并保留 warning；这不改变本 change 的硬门禁原则。
