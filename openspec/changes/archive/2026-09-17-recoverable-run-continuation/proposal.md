## Why

Figura 已经能够在前端断线后通过 run ID 和事件游标恢复展示，也能够将失败或中断的运行重新尝试。但 Gateway 重启或 Agent 在模型、工具、渲染、审核阶段中断时，系统只能把运行标记为终态，无法从已经确认完成的工作继续执行；如果简单重放，还可能重复调用模型、重复生成图表或覆盖原有终态。现在需要把“重连、重试、断点继续”定义成不同的生命周期操作，并为安全恢复建立持久化边界。

## What Changes

- 新增可恢复执行检查点和工作单元记录，保存下一步动作、已完成调用、布局上下文、审核/发布引用及必要的安全消息上下文。
- 为模型请求、工具调用、图表候选、VLM 审核和发布建立可判断的 `not_started`、`in_flight`、`completed` 状态；对不确定中的调用禁止自动重放。
- 增加显式 resume 操作：原 run 保持 `interrupted` 或其他终态不变，恢复操作创建带父子关系的新 run，并使用独立幂等身份。
- Gateway 重启后暴露恢复可用性和阻塞原因；默认不自动恢复，等待用户明确选择继续执行或重新尝试。
- 桌面端区分“重连”“继续执行”和“重新尝试”，展示恢复关系、恢复阶段和不可恢复原因。
- 让 Agent loop 能从安全检查点重建上下文，复用已持久化的调用结果和图表/审核引用，避免重复已提交工作。
- 增加 Gateway、Agent、前端和真实故障注入测试，覆盖重启、进程崩溃、调用不确定、重复 resume、图表发布和审核阶段恢复。

## Capabilities

### New Capabilities

- `run-checkpoint-recovery`: 定义安全检查点、操作账本、恢复资格和 resume 子运行关系。

### Modified Capabilities

- `agent-loop`: 支持从安全工作边界恢复，并遵守不确定调用不自动重放的规则。
- `agent-session-memory`: 允许恢复未完成运行所需的受控执行上下文，同时继续排除不完整运行作为普通历史上下文。
- `desktop-client`: 增加继续执行入口、恢复状态和 resume/retry/ reconnect 的明确区分。
- `execution-trace`: 记录检查点、工作单元状态和父子运行关系，并保持原 run 终态不可变。
- `python-gateway`: 增加 checkpoint 持久化、恢复接口、恢复资格查询和恢复调用的幂等保护。
- `run-lifecycle-reliability`: 补充 resume 语义、终态子运行关系和不确定调用处理约束。

## Impact

- 影响 `src/chartagent/agent/`、`src/chartagent/memory/`、`src/chartagent/gateway/` 和 `src/chartagent/review/` 的运行状态与持久化边界。
- 扩展 Gateway 的 run 查询、事件历史和运行操作协议，并增加 SQLite schema migration。
- 影响 `frontend/src/` 的运行时间线、恢复操作、状态标签和父子运行展示。
- 不引入分布式队列、跨机器 worker、provider 流式 token 级恢复或自动后台恢复；仍使用本地 Gateway 和 SQLite。
