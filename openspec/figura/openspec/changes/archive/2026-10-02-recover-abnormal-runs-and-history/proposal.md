## Why

当前 Figura 的未完成工具尝试可能让 Run 长期保持 `running`；即使旧 Run 被中断，其缺少结果的工具历史仍会阻止下一条模型请求。需要把合法异常历史、无人执行 Run 的收敛与安全停止一起处理，让一次失败不再永久阻断 Session，同时保留原始事实和已提交结果。

## What Changes

- 对 `failed` / `interrupted` Run 的合法未完成尾部生成有来源的异常上下文；完整交互保持原样，缺失结果不补造，完整性损坏仍拒绝。
- 在既有第三层动态运行时指令中表达异常终态、原始操作意图、已提交观察、未开始调用和结果未知调用；资源目录继续从已提交成功事实重建。
- 引入覆盖执行任务生命周期的所有权锁和统一执行协调入口，连接正常调度、启动接管和执行退出补偿；读取接口不执行恢复。
- 对确认旧执行者退出后的工具尝试按已有 replay 分类恢复，每个逻辑调用最多两次自动恢复；未知 Provider 尝试仍不重发。
- 持久化幂等停止请求，在步骤边界停止新动作，允许已开始动作提交真实结果，再原子收尾为 `interrupted`。
- 增加 Session-scoped 停止接口与安全执行活动 DTO，前端展示排队、执行、恢复、停止和终态，终态收敛后允许继续会话。
- 本 change 使用现有线程执行方式和协作式停止；强制终止卡死工具、工作进程管理、调用 ID 映射、跨 Provider 历史转换和通用历史摘要不在范围内。

## Capabilities

### New Capabilities

无。合同分别扩展既有 Runtime、Agent、Memory 与 Web 能力，不新增独立的恢复事实域。

### Modified Capabilities

- `run-execution-core`: 持久停止请求、动作启动与停止的事务竞争、执行所有权、停止收尾和安全终态原因。
- `durable-tool-execution`: 按单调用推进恢复、持久恢复次数约束、停止检查及不可恢复尝试的处理。
- `session-memory`: 合法异常终态尾部转成结构化上下文，保留完整交互及部分批次的真实观察。
- `agent-react-execution`: 统一推进与收尾、异常上下文的第三层指令映射、安全自动恢复及协作式停止。
- `figura-web-gateway`: 停止 API、执行状态投影、启动与退出补偿、SSE 和会话删除安全边界。
- `figura-web-client`: 停止操作、活动状态展示、刷新恢复与终态后的会话续用。

## Impact

- 后端涉及 `src/figura/runtime/`、`memory/`、`agent/`、`gateway/`、`storage/` 与 `bootstrap.py`；新增 SQLite 停止请求表和 schema migration，不修改旧 Run 的事实。
- Web 新增 `POST /sessions/{sessionId}/runs/{runId}/stop`；扩展 Figura Run DTO 和 client 能力，保持既有 HTTP/SSE 字段、游标及 `runId:sequence` 事件身份。
- 前端涉及 `frontend/src/api/figura/`、共用 workspace contract 的可选停止能力、Run 生命周期控制与 Figura 展示；保留 ChartAgent 与 mock 模式合同。
- 更新对应主规格与 `docs/figura/{runtime,agent,memory,web}.md`、总览；测试覆盖投影、锁竞争、恢复、停止事务、HTTP/SSE 与界面。
- 不引入外部服务或新 Python 依赖。单 Run 的事实及终态仍由 Runtime 拥有；存储不可用或事实损坏不承诺自动续用。
