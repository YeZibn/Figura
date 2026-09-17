## Why

Figura 已经能够异步执行 Agent run、持久化事件并在前端展示执行过程，但一次用户意图仍可能因为响应丢失而重复创建 run，也可能因为 SSE 断线、Gateway 重启或 worker 异常而留下重复、缺失或错误的运行状态。现在需要把请求幂等、事件重连、主动与系统中断、唯一终态和可追踪重试统一成一个可靠生命周期，保证前端重试连接不会重复执行模型，同时让用户能准确知道一个 run 是否仍在运行、已经中断或可以重新运行。

## What Changes

- 为异步 run 创建增加请求级幂等键和请求指纹，重复请求返回原 run，不重复提交 worker；同一 key 搭配不同请求时返回明确冲突。
- 统一 run 的持久化生命周期和终态原因，支持用户主动中断、Gateway 重启、Provider 超时、worker 异常和过期等中断/失败来源。
- 增加合作式中断信号传播，阻止中断后的迟到模型、工具、渲染或审核结果继续发布事件或覆盖终态。
- 完善 SSE 与历史事件重连：按事件游标恢复、去重、处理历史缺口、指数退避，并在 run 已进入终态时停止重连。
- 为中断后的用户重试建立新的 run，并保留与旧 run 的父子血缘；事件重连不创建新 run。
- 更新 Gateway HTTP 协议、SQLite 持久化、前端状态映射、运行提示和故障恢复交互。
- 增加并发提交、响应丢失、SSE 断线、Gateway 重启、终态竞态和迟到结果隔离测试。

## Capabilities

### New Capabilities

- `run-lifecycle-reliability`: 为 Agent run 提供幂等创建、可恢复事件订阅、中断语义、唯一终态和重试血缘。

### Modified Capabilities

- `python-gateway`: 修改 run 创建、事件流、历史状态和 Gateway 重启后的运行处理要求。
- `desktop-client`: 修改前端对幂等提交、重连、中断和终态的展示与操作要求。
- `execution-trace`: 修改终态事件、事件游标、历史缺口和迟到事件的追踪要求。
- `agent-loop`: 修改 Agent 对中断信号、终态保护和中断后工具/模型结果的处理要求。

## Impact

- Python：`src/chartagent/gateway/service.py`、`runs.py`、`history.py`、`protocol.py`、`server.py`、Agent loop 和运行时构造。
- Frontend：Gateway client、运行订阅、提交上下文、状态映射和运行时间线 UI。
- Storage/API：SQLite 增加幂等记录、终态原因和重试血缘；`POST /runs` 增加幂等协议，并增加 run 中断操作。
- Tests：Gateway、Agent loop、执行追踪和前端 smoke/集成测试。
- 不新增外部依赖；不包含图片压缩、图表 ChartSpec 改造、Provider 故障转移或真正的 Agent 断点续跑。
