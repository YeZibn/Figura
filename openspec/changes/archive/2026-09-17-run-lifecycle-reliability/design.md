## Context

Figura 当前已经具备异步 run、SQLite 事件持久化、按序列读取历史以及
SSE `Last-Event-ID` 重连的基础能力，但这些能力还没有形成一个完整的
生命周期协议：

- run 创建没有请求级幂等键，客户端在响应丢失时无法判断应该查询原 run
  还是重新提交；
- `publish`、完成、失败和重启中断之间缺少统一的终态闸门，迟到的模型或
  工具回调可能继续写入事件；
- Gateway 重启可以把数据库中的运行标为中断，但不一定产生可重放的终态
  事件；
- 前端已有有限次数的重连和历史补拉，但重连失败、历史缺口、interrupted
  与 retry 的语义没有完全分开；
- Agent 的工具循环没有一套贯穿模型请求、工具调用和结果发布的合作式
  中断检查。

本 change 只解决 run 生命周期可靠性。图片压缩、ChartSpec 布局语义、
Provider 故障转移和真正的 Agent checkpoint/resume 不在范围内。

## Goals / Non-Goals

### Goals

- 对有幂等键的同一用户意图保证至多一个 accepted run，并能报告 key 冲突。
- 为每个 run 建立清晰且持久的 active → terminal 生命周期，terminal 只能
  发生一次。
- 支持用户中断、Gateway 重启中断以及其他 bounded interruption/failure
  reason，并阻止迟到结果污染终态。
- 让 SSE 与历史 API 使用同一个 per-run event cursor，支持去重、补拉、
  显式 history gap 和有限退避重连。
- 让显式 retry 创建新的 run，同时保留旧 run 的可追踪血缘；reconnect
  永远不创建新 run。
- 使前端能够区分 connecting、running、reconnecting、completed、failed、
  interrupted、history-gap 和 unavailable，并保持已有执行时间线。
- 用并发、故障注入和前端行为测试覆盖协议边界。

### Non-Goals

- 不做跨进程任务队列、Provider 自动故障转移或跨机器调度。
- 不承诺 Gateway 重启后从模型上下文或工具中间状态继续执行；重启中的
  run 统一标记为 interrupted，可由用户 retry。
- 不把客户端断开当作取消；用户取消必须是显式操作。
- 不调整图表识别、ChartSpec 字段、布局语义或图片/事件压缩策略。
- 不在本 change 中改变 VLM 审核规则；仅保证审核/渲染迟到结果受终态闸门
  约束。

## Decisions

### 1. 以“请求幂等”而不是“run 查询幂等”为入口

异步 run 创建接口接受可选的 `Idempotency-Key`，客户端同时提交由服务端
规范化的请求指纹。指纹覆盖 session、文本、附件 ID 列表、有效 provider
以及其他会改变执行结果的输入；不包含随机 run ID、鉴权信息或本地展示字段。

服务端在接受 run 前执行以下决策：

1. key 不存在：按现有校验流程创建并记录 run；
2. key 存在且指纹相同：返回原 run 的 summary，不重复入队；
3. key 存在但指纹不同：返回 `idempotency_conflict`，不修改原记录；
4. key 存在但原 run 创建后提交 worker 失败：保留原 key 绑定，并把原 run
   收敛到 bounded failed/interrupted 状态，后续重复请求仍返回同一 run。

幂等记录与 run 接受动作需要在同一持久化边界中完成。第一方前端为每个
新的提交意图生成一个 key，在响应丢失或 SSE 断开时复用它；用户点击 retry
时生成新 key。没有 key 的旧客户端继续可用，但不获得重复提交保护。

幂等记录的保留期与 run/history retention 对齐。清理后旧 key 可以再次使用，
因此客户端不能把过期 key 当作永久全局唯一标识。

### 2. 用显式 terminal gate 串行化最终状态

沿用现有对外状态 `running`、`completed`、`failed`、`interrupted`。内部可有
非终态的取消请求标志（例如 `cancel_requested`），但它不是可供前端误判的
第五种终态。

所有终态转移必须通过同一个受锁保护的操作完成，并写入：

- `status`：终态枚举；
- `terminal_reason_code`：稳定的 bounded machine code；
- `terminal_message`：不含凭据和原始异常的 bounded 展示信息；
- `finished_at`；
- 对应的终态事件 sequence。

`publish` 在写入前检查 run 是否仍 active；一旦 terminal，模型、工具、
渲染、审核和 worker 回调都只能被丢弃或记录为内部诊断，不能进入客户端可见
历史。完成、失败和中断的竞争由同一个 gate 决定，胜出的转移保持不变，
后续调用返回 already-terminal 语义而不是覆盖状态。

这保留了已完成工作在中断之前的 trace，同时保证终态之后没有“复活”的进度。

### 3. 中断采用合作式传播，强制终止只做边界兜底

Gateway 增加 session/run 所有权校验的中断操作。中断 active run 时先持久化
取消请求和 reason，再通知运行上下文。Agent 在以下边界检查信号：

- 发起下一次 model request 前；
- 每个 native tool dispatch 前；
- 发布 tool observation、生成图、review context 或 final answer 前。

检查到中断后不再开始新的工作单元，当前不可立即打断的 provider/tool 调用
允许自然返回，但其结果必须经过 terminal gate，不能继续模型循环或发布最终
答案。Gateway 关闭/重启时，对数据库中仍 active 的 run 写入
`gateway_restarted` 中断终态；进程内能安全执行时同时发布终态事件，无法发布
时由历史查询根据 durable summary 补足权威终态。

### 4. 统一 SSE 与历史的游标协议

事件仍使用 per-run 单调递增 sequence，并通过 SSE `id` 与
`Last-Event-ID` 传递。服务端的语义是“返回大于 cursor 的 retained events，
再进入 live tail”；客户端以 `(run_id, sequence)` 去重，并记录最后一个已
连续应用的 sequence，而不是简单取收到的最大值。

前端的恢复顺序固定为：保留当前 timeline → 根据 last applied sequence 拉取
历史 → 合并并去重 → 仅在 run 仍 active 时重新订阅 live SSE。连接断开使用
有限次指数退避和抖动；重试上限后显示 unavailable，但不创建新 run。若服务端
返回 history gap，客户端显示显式 gap 状态并以 durable summary 判断最终状态，
不把局部事件伪装成完整轨迹。已 terminal 的 run 不再无限重连。

客户端断开与后端取消相互独立，因此浏览器刷新、窗口关闭或短暂网络问题不会
意外停止 Agent。

### 5. Retry 是新的意图，必须带血缘

retry 由用户动作触发，服务端使用新的 run ID 和新的 idempotency key。新 run
保存 `retry_of`（或等价的 parent run reference）、旧 run 的终态 reason 和
必要的 bounded display metadata；它不复制旧 run 的事件 sequence，也不改变
旧 run 的 summary。reconnect、history hydration 和 SSE error recovery 均只
使用原 run ID。

### 6. 前端把 durable summary 作为状态权威

事件用于补充执行时间线，run summary 用于决定终态。前端状态映射至少覆盖：

- active：connecting/running/reconnecting；
- terminal：completed/failed/interrupted；
- transport/history：history-gap/unavailable。

`interrupted` 必须显示 reason 的中文映射，并提供独立的 retry 操作；retry
失败不会清除原 run。提交组件保存 idempotency key、run ID 和 last applied
sequence，避免把网络错误路径误判成新的用户提交。

### 7. 采用故障注入测试验证竞态，而非只测 happy path

测试重点包括：并发同 key 提交、响应在接受后丢失、worker submit 失败、SSE
断在任意 sequence、history gap、重启恢复、cancel 与 completion/failure
竞态、late callback、重复 terminal event 以及 retry 血缘。前端使用 mock
adapter 模拟断线和重复 replay，Gateway 集成测试验证真实 HTTP/SSE 合约。

## Risks / Trade-offs

- **SQLite schema 迁移风险**：新增幂等表/字段与 retry reference 会提高迁移
  复杂度。采用向后兼容的 additive migration；旧数据允许为空，不做破坏性
  回填，迁移失败时 Gateway 不应静默启动。
- **接受与入队之间的窗口**：先持久化再提交 worker 会留下短暂 pending；提交
  失败必须由统一终态 gate 收敛，避免重复请求再次入队。先入队再落库则更容易
  产生不可追踪执行，因此不采用。
- **无法真正杀死 Provider 调用**：合作式中断会让取消存在延迟。通过在结果
  发布前再次检查 terminal gate 保证正确性，UI 明确展示“正在中断”直到终态
  可读。
- **历史保留造成不可恢复 gap**：客户端无法补回已清理事件。服务端必须显式
  返回 gap，客户端保留 summary 并提示轨迹不完整，不猜测缺失内容。
- **无 key 的兼容请求仍可能重复**：保留旧协议有兼容收益，但只能对带 key 的
  第一方请求承诺幂等；日志/文档要明确该边界。
- **终态事件重复或缺失**：事件 append 使用 `(run_id, sequence)` 唯一约束，
  summary 是第二权威来源；客户端按 identity/sequence 去重，并在终态历史中
  允许从 summary 补充状态。

## Migration / Rollback

1. 先发布 additive storage/API 支持：幂等记录、terminal reason、retry
   reference 和中断接口；保留现有 run/history 路由。
2. 再启用 Agent terminal gate 与中断信号，最后让前端默认发送 key、使用新的
   reconnect/retry 状态。
3. 迁移期间旧前端仍可创建无 key run；旧事件读取逻辑继续可用。新前端检测到
   capability 不足时显示有限的 legacy recovery 提示，不把 reconnect 变成
   retry。
4. 若需要回滚，保留新增列/表并关闭新客户端能力开关；已写入的终态 reason
   和 retry reference 不删除，旧服务忽略未知字段。不得通过删除历史或重置
   sequence 回滚。

## Resolved Contract Choices

- `Idempotency-Key` 使用 HTTP header；Gateway adapter 和 mock adapter 都在
  同一客户端边界暴露对应的幂等上下文，便于真实协议与故障测试保持一致。
- history gap 统一使用稳定 machine code `history_gap`；HTTP 响应和 SSE
  断流前的结构化结果都遵循这个标识，前端据此进入显式 gap 状态。
- 用户点击中断后，前端可以在 provider 尚未返回期间显示
  `cancel_requested` 临时文案；它只表示请求已提交，不是新的持久化终态，
  最终仍必须收敛到 `interrupted`。
