## Why

最近的真实图表评测在测量工具返回 `remeasure_required` 后，于下一次模型请求以 `BadRequestError` 终止。根因是同一 assistant 回合包含多个 tool call 时，Agent 将 repair user 消息插入到了对应 tool 结果之间，破坏了 provider 要求的原生工具消息顺序；同时评测报告把尚未到达的 render 阶段误报为首个失败阶段，掩盖了真实故障位置。

## What Changes

- 保证一个 assistant tool-call 批次的全部 `tool` 结果先连续写入模型上下文，再追加 repair 上下文。
- 在同一批次产生多个测量修复请求时，按 attachment、panel、session 和 attempt 保留并汇总所有待处理 repair，不互相覆盖。
- 保持 repair、checkpoint 和后续定向重测的父子 attempt 关联，允许模型在合法消息历史上继续处理修复。
- 增加针对多工具调用与 repair 组合场景的 Agent 回归测试，并使用最近的真实图表评测样本验证链路可继续运行。
- 修正评测阶段归因：模型请求失败应归因于模型/传输运行阶段，只有实际观察到 assemble 或 render 事件时才报告对应阶段。
- 在不泄露密钥、路径、图片和完整 provider payload 的前提下，保留足够的 provider 错误摘要用于诊断。

本次不调整柱状图、折线图的坐标轴检测、绘图区识别或数值测量算法；这些属于后续独立 change。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-loop`: 明确多工具调用批次的原生消息顺序、多个 repair 上下文的保存与继续执行语义。
- `real-chart-evaluation`: 修正模型请求失败、repair 阻塞和未到达 assemble/render 阶段的诊断归因与报告语义。

## Impact

- 影响 `src/chartagent/agent/loop.py` 的工具批处理、repair 上下文和 checkpoint 状态。
- 影响 `src/chartagent/evaluation/timeline.py` 及相关报告投影和前端可见失败信息。
- 增加 Agent、Gateway/评测诊断相关回归测试；不新增外部依赖，不改变 provider 请求的业务参数。
