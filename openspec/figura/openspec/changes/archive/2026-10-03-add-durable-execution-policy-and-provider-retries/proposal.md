## Why

Figura 当前将正常 Run 的执行规模、单次操作的故障恢复次数、协议正确性和存储保护混在多层硬上限中：复杂任务可能因第 9 次模型请求或第 33 个工具调用终止，而短暂网络故障又直接导致整个 Run 失败。需要删除无业务依据的累计配额，将 Provider 网络恢复集中到可持久化的 Runtime 边界，同时保持模型对工具失败后续动作的决策权。

## What Changes

- 删除每 Run 8 次 Provider attempt、32 个已启动逻辑工具调用的限制；不新增累计模型步数、token、时长、重试次数、存储量或无进展终止配额。
- Provider 每个逻辑请求最多进行 4 次物理尝试（首次加 3 次重试），记录分类、请求绑定、退避时间和跨重启次数；SDK 与 HTTP transport 不进行隐式重试，不自动切换 Provider/model。
- 仅对可确认的临时网络/服务错误重试。生成请求在结果未知时允许有记录的替代尝试，保留旧 attempt 的 unknown 事实；同一逻辑请求最多接受一个响应及其工具意图批次。
- 工具已提交失败作为真实 observation 交给模型决策，`retryable` 不触发自动调用。未知工具结果继续按原版本、replay effect 和稳定幂等键恢复，每个逻辑调用最多首次加 2 次恢复执行，并在持久化入口统一校验。
- 删除消息数、指令数、工具数、Schema 属性数、工具调用批次数量、参数/结果小字节上限和任意 call ID 长度上限；移除固定 4096 completion tokens 及通用 131072 输出上限。单次输出可由 Provider 配置显式指定，否则省略参数。
- 将执行 JSON 数据的技术保护收敛到一个可配置的单载荷保护合同（默认 32 MiB、JSON 深度 64）；保留 JSON/Schema 语义、身份关联、隐私和供应商实际协议限制。图片字节/解码保护及领域数量限制继续由原领域负责。
- 删除通用 16 张图片/Run 附件引用数量上限；保留图片单体与请求图片总字节保护，以及供应商有证据的专属限制。完整历史仍发送，不压缩、不摘要、不自动裁断。
- Provider 重试等待持久化后释放 worker；Gateway 按单外部动作切片和轮转调度，使长期 Run 与其他 Session 公平共享现有并发容量。停止请求在所有 claim 之前仲裁，工具可协作检查停止。
- 原子迁移存储、codec 与验证规则，保留既有记录、终态、事件 identity 和 continuation 的空/null/缺失语义；不为缺少请求绑定的历史 attempt 猜测重发。
- **BREAKING**：内部 Provider options 将 completion 上限改为可选；新版执行 payload/checkpoint、请求绑定与数据库结构需要升级。公开 HTTP/SSE 字段、Run 状态和前端 client façade 保持兼容。

## Capabilities

### New Capabilities

- `provider-request-retries`: 持久化逻辑请求、物理 attempt、错误分类、退避和安全替代生成。
- `execution-payload-contract`: 单执行 JSON 载荷保护及各层限制的责任边界。

### Modified Capabilities

- `model-provider`: 可选输出上限、真实 Adapter 限制、分类错误和显式 Runtime 重试。
- `run-execution-core`: 请求分组、重试 checkpoint、扩大载荷合同、迁移和停止仲裁。
- `agent-react-execution`: 无累计配额的 ReAct、完整请求、模型决议工具失败、可让出执行切片。
- `tool-runtime`: 删除零散微上限，保留严格 Schema 与 call ID 合同和无隐式重试。
- `durable-tool-execution`: 统一载荷保护、持久化恢复次数校验和未知结果边界。
- `provider-continuation-persistence`: 统一完整载荷保护，不截断 continuation。
- `session-memory`: 完整事实投影不依赖已删除的通用 Provider 微上限。
- `figura-web-gateway`: 公平切片、持久化重试等待与停止优先调度。

## Impact

实现范围是 `src/figura` 的 Agent、Providers、Tools、shared JSON validation、Runtime codec/repository/coordinator、SQLite schema/migrations 和 Gateway dispatcher/请求读取；更新对应测试、`.env.example` 与当前实现文档。不修改 `src/chartagent` 或 chartagent store，不增加 SDK、队列服务或第三方存储依赖。

保留 Sources 的上传/格式/像素保护，Charts/Measurement 的领域规则，事件与展示摘要的小载荷边界，以及 Gateway 默认 3 个 worker、8 个排队槽。上下文窗口规划、压缩、摘要、自动补发截断输出、工具明确失败自动重试、Provider fallback、Run 配额管理均不在本轮。
