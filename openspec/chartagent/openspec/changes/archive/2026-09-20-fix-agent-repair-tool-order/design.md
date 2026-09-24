## Context

See `proposal.md` for the motivation and scope. 当前 Agent 在一个 assistant 回合返回多个 tool call 时逐个处理工具；测量质量门禁可能在某个工具结果之后生成 repair user 消息，导致该消息出现在同一 assistant 回合的其他 tool 结果之前。现有 measurement session 已经按来源和 panel 保存 attempt lineage，但 checkpoint 的待处理 repair 仍然投影为单个 action。评测 timeline 目前只把工具和最终阶段作为阶段证据，provider 的模型请求异常又被压缩成通用 `run_failed`，因此无法准确显示模型请求失败与后续阶段未到达的关系。

## Goals / Non-Goals

**Goals:**

- 把一次 assistant tool-call 响应视为一个有序批次，保证发送给 provider 的消息始终符合原生工具调用顺序。
- 在一个批次中保留多个 panel/session 的 repair action，并让下一轮模型能够逐项选择和继续修复。
- 保持 checkpoint、measurement session 和父子 attempt 的可恢复关联，并兼容已有单个 `pendingMeasurementRepair` 状态。
- 让评测 timeline 能观察模型请求阶段，准确区分模型/传输失败、测量质量未接受、repair 阻塞和未到达的 assemble/render。
- 记录有界、脱敏且足以定位问题的 provider 错误摘要。

**Non-Goals:**

- 不改变柱状图、折线图、饼图或散点图的像素检测和坐标轴算法。
- 不在本 change 中引入新的 provider、重试策略或外部队列。
- 不改变审核只由 VLM 执行的既有边界，也不把评测变成准确率或 IoU 平台。
- 不复用不同评测批次之间的 panel 或 measurement session。

## Decisions

### 1. 将一次 assistant 响应作为原子工具批次

工具 dispatch 仍可串行执行，但模型上下文的追加必须遵循以下顺序：

```text
assistant(tool_calls=[A, B])
        │
        ├── tool(A)
        └── tool(B)
        │
        ├── visual observation（如果有）
        └── aggregated repair context（如果有）
```

每个工具结果在处理完成后立即追加对应 `tool` 消息，但 repair user 消息不能在当前批次内追加。先收集 repair action，待全部 tool call 结束后按原调用顺序生成一个有界的 repair 集合。这样既保留工具结果顺序，也不需要禁止模型并行提出独立证据请求。

备选方案是提示词要求模型每轮只调用一个工具，或遇到 repair 就中断剩余 tool call；前者依赖模型自律，后者会丢失已经声明的工具调用，均不如批次原子化稳定。

### 2. 以 measurement session 为 repair 状态的权威来源

运行态继续使用现有的 measurement sessions 保存每个 attachment/panel 的 attempt、父 attempt、预算和 pending action。面向下一轮 prompt 与 checkpoint 时，将所有 pending action 投影为有界列表，并按当前批次出现顺序、session、panel 和 attempt 保持稳定排序；不再用单个字典覆盖前一个 repair。

读取 checkpoint 时同时接受旧的单数 `pendingMeasurementRepair` 和新的列表字段，统一规范化到内部列表。写入新 checkpoint 时使用列表字段；当列表为空时不注入 repair 消息。

### 3. Repair 上下文只作为下一轮模型输入

当前批次的 repair 结果仍然发布 `measurement_repair_required` 事件并写入普通运行记录，但不会立即修改 tool-message 序列。批次结束后追加一条包含所有 bounded action 的 user continuation，明确每个 action 的 panel、session、父 attempt、目标字段和下一动作。模型完成某一项修复后，由 measurement session 的 accepted/failed 状态移除或更新对应 action。

### 4. 将模型请求纳入诊断时间线

阶段投影增加 `model` 阶段，消费 `model_started` 和 `model_completed` 事件。模型请求错误以 `model_completed` 的错误事件作为最早可确认失败；`run_failed` 只作为终态补充，不能把失败阶段推断为最后一个可能的 render 阶段。若不存在模型错误细节，报告保留 `transport_runtime`/`unknown`，并明确说明证据不足。

测量阶段同时记录工具调用状态和 measurement quality 状态：工具返回 `success` 不代表测量可接受；`remeasure_required` 应显示为质量未通过并进入 repair 状态。repair 只有在定向重测被接受或明确耗尽/阻塞时才改变最终状态。

### 5. Provider 错误只保留安全摘要

在客户端边界提取 provider 异常的类型、HTTP 状态（若有）、provider error code（若有）和截断后的通用 message。对 URL、authorization、API key、完整 request/response、图片数据和本地路径执行现有脱敏规则。trace、Gateway history 和评测报告只使用该摘要，不保存原始异常对象。

## Risks / Trade-offs

- [Risk] 一个批次同时产生多个 repair action 时，模型可能一次处理多个目标，增加 prompt 长度和决策复杂度 → 限制 action 数量和字段深度，保持 panel/session/attempt 引用，且在下一轮明确逐项处理。
- [Risk] 旧 checkpoint 只有单个 repair 字段 → 读取时兼容旧字段，写入时才切换为列表，不要求历史评测迁移。
- [Risk] 新增 model 阶段会改变评测时间线的阶段数量 → 前端按已有通用阶段结构渲染未知/新增名称，旧 bundle 仍按缺失阶段 `not_observed` 读取。
- [Risk] provider 错误摘要仍可能因不同 SDK 异常结构而缺少 HTTP 细节 → 保留 `error_type` 和 `provider_request_failed` 作为最低保障，并通过客户端单测覆盖可识别和不可识别异常。
- [Risk] 修复消息顺序后，评测会继续暴露真实的绘图区和坐标轴问题 → 这是预期结果；本 change 只让链路正确到达这些问题，不伪装测量已通过。

## Migration Plan

1. 先实现批次级 tool-message 顺序、repair 列表和 checkpoint 兼容，并补充单元测试。
2. 实现 model 阶段及 provider 错误摘要，再补充 timeline/report 测试。
3. 使用同一 `bar_line_dashboard` fixture 重新运行一次真实评测，确认失败点不再显示为 render，且链路能够进入下一轮 repair 或明确报告新的测量问题。
4. 若需要回滚，只回滚 Agent 批处理和 timeline 投影代码；旧 checkpoint 仍可按单数 repair 字段读取，旧评测 bundle 不需要重写。

## Open Questions

无。绘图区识别和坐标轴算法将在后续独立 change 中讨论。
