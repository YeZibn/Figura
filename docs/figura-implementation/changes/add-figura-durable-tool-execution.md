# add-figura-durable-tool-execution · Figura 持久化工具执行

> 最近更新：2026-09-26。实施状态：已实现（17/17 tasks）。OpenSpec 状态：主规格已同步、已归档（17/17 tasks complete）。

## 1. 概览与决定

- **问题与目标**：实现前 ToolRuntime 只能安全执行单次调用，既不持久化调用意图、执行开始或结果，Run store 也拒绝含 tool call 的模型响应。工具副作用发生后、结果提交前若进程退出，恢复方无法判断是否可以重调。
- **完成结果**：Figura 能把无 provider continuation 的模型工具调用按顺序写入 Run 执行事实，经统一 DurableToolExecutor 调用现有 ToolRuntime，将每项结果提交并推进 checkpoint；重启后能识别未开始、已完成和结果未知的调用。
- **本次范围**：Run 执行记录/codec/SQLite schema 与迁移；模型工具调用事实；attempt 开始事实与成功/失败结果事实；checkpoint 动作；ToolRuntime 上方的单项持久执行协调；未知结果恢复策略；公开事件和摘要的数据隔离。
- **明确不包含**：Provider continuation 持久化；Provider 请求尝试和未知 Provider outcome 恢复；完整 Agent/ReAct 循环、模型轮次上限与下一轮请求；实际图表/附件/测量工具；并行 dispatch、通用 retry/fallback；Gateway/SSE/CLI/UI 与工具结果展示。
- **前置依赖**：add-figura-run-execution-core 与 add-figura-tool-runtime 已实现并归档。ToolRegistry 提供有序定义和 registry version；ToolRuntime 提供单次有界 dispatch。
- **基线与来源**：实现前基线为 Run core stream 仅有 input/model_response/final_answer、拒绝 tool_calls/continuation，且尚无 durable executor。实际实现证据见 Run models（../../../src/figura/runtime/models.py）、Run coordinator（../../../src/figura/runtime/coordinator.py）、Run store（../../../src/figura/runtime/store.py）、strict codec（../../../src/figura/runtime/_codec.py）、per-Run lock（../../../src/figura/runtime/_run_lock.py）、durable executor（../../../src/figura/runtime/tool_execution.py）、Tool contracts（../../../src/figura/tools/contracts.py）、Tool Runtime（../../../src/figura/tools/runtime.py）和 Tool Registry（../../../src/figura/tools/registry.py）。
- **OpenSpec**：已归档 change（../../../openspec/figura/openspec/changes/archive/2026-09-26-add-figura-durable-tool-execution/）；17/17 tasks 已完成，change 与全部 Figura 主规格均通过 strict validation；`durable-tool-execution` 和 `run-execution-core` 主规格已同步。

| 主题 | 决定/现状 | 决策状态 | 依据 | 受影响字段/组件 |
|---|---|---|---|---|
| 第一 change 边界 | 只做 durable tool execution；continuation 与 ReAct 调度另行处理 | 已确认 | 用户明确要求第一 change 只做 tool execution | Run store、ToolExecutor |
| 工具顺序 | 按模型响应顺序逐个串行执行；当前结果提交后才能推进下一项 | 已确认 | ToolRuntime 每次只 dispatch 一个调用；批次次序由 durable owner 控制 | ToolCallFact.position、checkpoint |
| 模型响应兼容 | 接受无 continuation 的 tool call 响应；响应含 continuation 仍拒绝 | 已确认 | continuation 持久化属于后续 change | ModelResponseFact、coordinator |
| Durable facts | core records 保持 input/model_response/final_answer；工具意图、attempt、结果写入独立的 `run_tool_execution_facts` 序列 | 已确认 | 避免重建 v1 的固定 kind CHECK 与不可变记录表；两条序列由一次事务保持一致 | ToolExecutionFact、RunState、checkpoint |
| 工具版本 | 每批 ToolCallFact 与 attempt 记录 registry_version；恢复只允许匹配该版本的定义 | 已确认 | ToolRegistry 有版本；避免旧调用落到新 handler | ToolCallFact.registry_version、ToolAttemptStartedFact.registry_version |
| 未知结果策略 | replay_safe 可在旧 owner 退出后重放；idempotent_local_write 用稳定键重放；reconcile_required 暂停并等待受信结果 | 已确认 | 用户已确认按 replay_effect 分类恢复 | ReplayEffect、ToolAttemptStartedFact、DurableToolExecutor |
| 重放身份 | 幂等键为 SHA-256(canonical JSON `[run_id, call_id]`)，跨 attempt 稳定；暴露为 ToolContext.idempotency_key | 已确认 | 避免同一逻辑调用多次产生重复本地写入 | ToolContext、ToolDefinition handler contract |
| 失败后的 Run 表达 | 不增加 RunStatus；未决 attempt 继续是 running，由 checkpoint `tool_attempt` 表示等待恢复/核对 | 已确认 | 避免本 change 提前改动公开 Run 状态合同 | RunStatus、NextAction、checkpoint |
| 数据边界 | 每 response ≤64 calls；每参数≤64 KiB UTF-8；参数总和≤1 MiB；canonical result≤256 KiB；完整工具事实≤512 KiB | 已确认 | 兼容单次 ToolRuntime 限制并支持有界事实 envelope | codec、ToolCallFact、ToolResultFact、batch validation |
| SQLite 迁移 | schema version 从 1 升级至 2；保留 v1 数据、Run IDs、checkpoint 和事件 | 已确认 | 实现前 v1 schema 的 record_kind 使用固定 CHECK；迁移 fixture 已验证原事实保留 | store migration |
| 公开事件 | 本 change 不新增工具参数/结果事件；执行事实不进入 Run 公共摘要或日志 | 已确认 | Run spec 将生命周期事件与执行事实隔离 | event codec、public projection |

## 2. 实现合同

### 组件

| 组件/源码路径 | 职责 | 输入 → 输出 | 依赖/调用关系 | 实施状态与证据 |
|---|---|---|---|---|
| Run domain models：src/figura/runtime/models.py | 定义 ToolCall/Attempt/Result facts、双序列 envelope、checkpoint actions 与 RunState | typed facts/checkpoint → RunState | Provider response 与 ToolRuntime contracts | 已实现；ToolFactKind、三种 payload、ToolExecutionFact、双 cursor 和 action 引用均已定义 |
| Run coordinator：src/figura/runtime/coordinator.py | 校验 ProviderResponse；接受不含 continuation 的 tool calls；原子提交 core response 与 tool facts | ProviderResponse → core record + tool facts + checkpoint | Run store、Provider models、ToolRegistry version | 已实现；调用批次按 Provider 顺序绑定 registry version；continuation 仍拒绝 |
| SQLite store：src/figura/runtime/store.py | 独立追加工具事实、原子 CAS 更新双 cursor/checkpoint、恢复读取；迁移 schema | expected revision + fact → tool fact + checkpoint 或 RunError | models、codec、SQLite | 已实现；schema v1→v2、外键/完整性校验、append-only facts、响应/调用及 attempt/result 原子转移 |
| Strict codecs：src/figura/runtime/_codec.py | 工具事实白名单编解码、嵌套枚举/引用/大小限制与 aggregate 预算 | typed facts ↔ bounded JSON | models、ToolExecutionResult contract、shared JSON codec | 已实现；包含重复 key、非有限值、Unicode scalar、单项及聚合大小校验 |
| Per-Run execution lock：src/figura/runtime/_run_lock.py | 以 OS advisory file lock 证明同一 Run 的唯一活动执行者 | data root + opaque run_id → exclusive lock scope | DurableToolExecutor；POSIX `fcntl.flock` | 已实现；不可用、权限不安全或锁被占用时 fail closed；不同 Run 使用不同锁文件 |
| Durable executor：src/figura/runtime/tool_execution.py | 串行 dispatch、持久化 attempt/result、按 replay effect 恢复与提交受信核对结果 | Session/Run + Registry + ToolRuntime → RunState | store、PerRunExecutionLock、ToolRuntime、ToolRegistry | 已实现；含 execute_pending、recover_unknown_attempt、reconcile_unknown_attempt |
| Tool contracts/runtime：src/figura/tools/contracts.py、runtime.py | 保持单次安全 dispatch；为幂等本地写入提供稳定 idempotency_key | ToolInvocation + ToolContext → ToolExecutionResult | Registry 与 JSON Schema 校验 | 已实现；ToolContext 接受隐藏的 64-hex key，缺少幂等键时 Runtime 不调用 handler |
| OpenSpec：openspec/figura/openspec/changes/archive/2026-09-26-add-figura-durable-tool-execution/ | 记录行为合同、设计和按依赖排序的实施任务 | proposal → delta specs/design/tasks | durable-tool-execution、run-execution-core 主规格已同步 | 已归档；17/17 tasks 完成；change 与主规格 strict validation 通过 |

### 字段

#### ToolExecutionFact 公共 envelope

| 字段路径（一字段一行） | 类型、必填/可空、默认值、约束 | 来源/owner、读写方与时机 | 生命周期、持久化与暴露范围 | 校验/错误 | 计划或实现状态、证据 |
|---|---|---|---|---|---|
| ToolExecutionFact.run_id | string，必填；opaque Run ID | Store 根据目标 Run 写入；RunState 读取 | SQLite 外键；仅内部 | 不存在的 Run 拒绝写入 | 已实现；`models.py` envelope、`store.py` FK/read |
| ToolExecutionFact.tool_sequence | int，必填；每 Run 从 1 连续递增，独立于 record_sequence | Store 分配；Executor/checkpoint 按序读取 | `run_tool_execution_facts` 主序列 | gap、duplicate、与 checkpoint 不一致为 integrity error | 已实现；Store 原子分配、`_validate_state` 校验连续序列 |
| ToolExecutionFact.fact_kind | enum，必填：tool_call / tool_attempt_started / tool_result | Store/strict codec | 表列；不可变 | 未知 kind/version fail closed | 已实现；`ToolFactKind`、SQLite CHECK 与 codec 白名单 |
| ToolExecutionFact.schema_version | int，必填；首版为 1 | strict codec/store | 表列并校验 payload 版本 | 不支持版本拒绝读取/写入 | 已实现；表列、codec 版本一致性校验 |
| ToolExecutionFact.payload | 对应下方类型的 bounded JSON object | Coordinator/Executor 创建；Store 编解码 | 私有持久化事实；不进入 public projection | 依据 kind 使用精确字段白名单 | 已实现；按 fact kind 严格编码/解码并应用 512 KiB 完整事实限额 |
| ToolExecutionFact.created_at | string，必填；Store 写入 UTC ISO 时间 | Store 追加时生成 | 随事实持久化 | 当前读取路径保留 SQLite 值，不额外校验时间格式 | 已实现；`_utc_now` 写入；读取格式未独立校验 |

#### ToolCallFact payload

| 字段路径（一字段一行） | 类型、必填/可空、默认值、约束 | 来源/owner、读写方与时机 | 生命周期、持久化与暴露范围 | 校验/错误 | 计划或实现状态、证据 |
|---|---|---|---|---|---|
| ToolCallFact.response_record_id | string，必填；同 Run 的 model_response core record | Coordinator 创建；Store/RunState validator 验证 | 持久化；不进 public event | 必须引用同 Run、同类型响应 | 已实现；Coordinator 生成 record ID，`_validate_state` 验证引用 |
| ToolCallFact.call_id | string，必填；UTF-8 ≤256 bytes；Run 内唯一 | ProviderToolCall 来源；ToolRuntime 及后续 orchestration 关联 | 持久化，作为逻辑调用 opaque identity | 空值、超限、重复时拒绝 | 已实现；Provider tool-call codec、Call codec 和 RunState validator 共同校验 |
| ToolCallFact.tool_name | string，必填；1–64 ASCII 字符，匹配工具命名规则 | Provider response 来源；Registry 查找和 dispatch 读取 | 持久化；公开 API 不暴露 | 格式非法、Registry version 不匹配或工具未注册时不执行 handler | 已实现；codec 约束格式，Executor 对 registry/version fail closed |
| ToolCallFact.arguments_json | string，必填；合法 JSON object；UTF-8 ≤64 KiB | Provider response 来源；ToolRuntime 解析；Store 保留原始有界参数 | 不可变持久化；敏感内容，不进 event/log/public summary | 非法 JSON、重复 key、非有限值、无效 Unicode scalar 或超限时整批拒绝 | 已实现；`_tool_arguments` 保留 raw JSON，并校验 UTF-8 与格式 |
| ToolCallFact.position | int，必填；0-based，范围 0–63；同 response 内连续唯一 | Coordinator 按 Provider 顺序赋值；Executor 顺序读取 | 持久化以重建执行顺序 | 缺项、重复或乱序时拒绝 | 已实现；batch codec、Store 与 RunState validator 校验 |
| ToolCallFact.registry_version | string，必填；UTF-8 ≤128 bytes | 创建批次时的 ToolRegistry.version | 持久化；恢复前精确匹配 | 不匹配或定义不可用时 fail closed | 已实现；Coordinator 写入，Executor 初次 dispatch 与恢复时精确比较 |

#### ToolAttemptStartedFact payload

| 字段路径（一字段一行） | 类型、必填/可空、默认值、约束 | 来源/owner、读写方与时机 | 生命周期、持久化与暴露范围 | 校验/错误 | 计划或实现状态、证据 |
|---|---|---|---|---|---|
| ToolAttemptStartedFact.tool_call_sequence | int，必填；指向同 Run 的 tool_call fact | Store 创建/验证；恢复读取 | 持久化内部引用 | 必须是当前逻辑调用 | 已实现；Store CAS 与 RunState reference validator 校验 |
| ToolAttemptStartedFact.call_id | string，必填；等于 ToolCallFact.call_id | Executor/Store 从意图事实复制 | 持久化；逻辑调用身份 | 不匹配为 integrity error | 已实现；Store 从持久调用意图构造，RunState 校验 |
| ToolAttemptStartedFact.attempt_id | string，必填；opaque，默认 UUID hex | Store 生成或测试/内部调用指定；结果事实引用 | 持久化 | Run 内唯一 | 已实现；Store 插入并由 validator 检查唯一性 |
| ToolAttemptStartedFact.attempt_number | int，必填；每 call 从 1 起连续递增 | Store 根据同 call 已有 start facts 分配 | 持久化 | 非正数或不连续为 integrity error | 已实现；初次 attempt 与 replay 都单调递增，validator 核对 |
| ToolAttemptStartedFact.replay_effect | enum，必填：replay_safe / idempotent_local_write / reconcile_required | 对应 ToolDefinition 快照；重放只沿用原快照 | 持久化；仅 durable owner 决定恢复动作 | 缺失/未知值读取失败并 fail closed | 已实现；Store 在 start fact 固化，Executor 按枚举分支处理 |
| ToolAttemptStartedFact.registry_version | string，必填；≤128 bytes，须等于调用意图版本 | ToolRegistry 来源 | 持久化 | 版本不一致或当前 Registry 不可用时停止执行 | 已实现；初次 dispatch、replay、reconcile 均检查 |

#### ToolResultFact payload 与错误字段

| 字段路径（一字段一行） | 类型、必填/可空、默认值、约束 | 来源/owner、读写方与时机 | 生命周期、持久化与暴露范围 | 校验/错误 | 计划或实现状态、证据 |
|---|---|---|---|---|---|
| ToolResultFact.tool_call_sequence | int，必填；引用同 Run 的 ToolCallFact | Store 从当前 action 取得并验证 | 持久化 | 不存在/错 Run 为 integrity error | 已实现；CAS 查询与 RunState validator 校验 |
| ToolResultFact.attempt_id | string，必填；引用对应 started attempt | Executor 提交；Store 校验 | 持久化 | 只允许当前最新且未完成 attempt 写结果，一个 attempt 至多一个结果 | 已实现；重复/旧 attempt result 拒绝 |
| ToolResultFact.call_id | string，必填；匹配调用意图 | ToolExecutionResult 来源；Store 由 ToolCallFact 固化 | 持久化 | 入参身份不匹配时拒绝写入 | 已实现；Store 检查 call ID |
| ToolResultFact.tool_name | string，必填；匹配调用意图 | ToolExecutionResult 来源；Store 由 ToolCallFact 固化 | 持久化 | 入参名称不匹配时拒绝写入 | 已实现；Store 检查工具名 |
| ToolResultFact.outcome | enum，必填：succeeded / failed | ToolExecutionResult.outcome | 持久化；内部 history 可读取 | 成功/失败字段互斥 | 已实现；严格 codec 和 ToolExecutionResult 联合校验 |
| ToolResultFact.result | JSON object；仅 succeeded 必填；canonical UTF-8 JSON ≤256 KiB | ToolExecutionResult.result | 持久化；不进 public summary/event/log | ToolRuntime 按工具 schema 校验；codec 再校验对象结构、canonical 大小与 envelope 大小 | 已实现；成功结果经两层校验 |
| ToolResultFact.error | object；仅 failed 必填；bounded structured error | ToolExecutionResult.error | 持久化；不直接公开 | 仅允许失败结果含 error，成功/失败字段互斥 | 已实现；严格 codec 编解码 |
| ToolResultFact.error.code | string，必填；小写字母开头，后续仅字母/数字/`_.-`，≤64 字符 | ToolExecutionError | 持久化 | 格式不合法则拒绝 | 已实现；contracts 与 codec 双重校验 |
| ToolResultFact.error.message | string，必填；UTF-8 ≤512 bytes | ToolExecutionError | 持久化；不得记录原始异常详情到诊断日志 | 超限拒绝；unexpected exception 转为 generic handler failure | 已实现；ToolRuntime 不暴露异常文本，codec 校验上限 |
| ToolResultFact.error.retryable | bool，必填 | ToolExecutionError | 持久化供上层观察 | 不单独授权恢复未知副作用 | 已实现；数据字段保存，但 DurableToolExecutor 不据此自动重试 |
| ToolResultFact.error.field_path | string 或 null，默认 null；≤256 bytes 且为 JSON Pointer | ToolExecutionError | 持久化 | 格式/上限沿用现有合同 | 已实现；contracts/codec 校验 JSON Pointer 与字节数 |

#### ToolContext 与 checkpoint

| 字段路径（一字段一行） | 类型、必填/可空、默认值、约束 | 来源/owner、读写方与时机 | 生命周期、持久化与暴露范围 | 校验/错误 | 计划或实现状态、证据 |
|---|---|---|---|---|---|
| ToolContext.run_id | string，必填；opaque Run ID | DurableToolExecutor 从已验证 Run 注入；handler 读取 | 仅 invocation context | 绑定当前 Run | 已实现；`contracts.py` 与 `tool_execution.py` |
| ToolContext.session_id | string，必填；opaque Session ID | DurableToolExecutor 从已验证 Run 注入；handler 读取 | 仅 invocation context | 绑定当前 Session | 已实现；`contracts.py` 与 `tool_execution.py` |
| ToolContext.call_id | string，必填；UTF-8 ≤256 bytes 的逻辑调用 ID | DurableToolExecutor 注入；handler 读取 | 重试时保持不变 | 必须匹配调用意图 | 已实现；ToolContext 与 ToolInvocation 都校验 |
| ToolContext.idempotency_key | string 或 null；仅 idempotent_local_write 调用提供，64 lowercase hex | Executor 对 canonical JSON `[run_id, call_id]` 计算 SHA-256 | invocation context；repr 隐藏；不得进入持久事实、日志或 public projection；跨 attempt 稳定 | 不得使用 attempt_id；缺键时 ToolRuntime 返回 bounded failure 且不调用 handler | 已实现；`contracts.py`、`tool_execution.py`、`tools/runtime.py` |
| ExecutionCheckpoint.revision | int，必填；每次成功状态转换 +1 | Store CAS | 持久化 | expected_revision 过期拒绝并回滚事务 | 已实现；Store 对 response、attempt、result、terminal transition 使用 revision compare-and-swap |
| ExecutionCheckpoint.last_committed_record_sequence | int，必填；最后 core record 序号 | Store | 持久化；与 core stream 对齐 | 不一致为 integrity error | 已实现；core 事实流校验与读写保持 |
| ExecutionCheckpoint.last_committed_tool_sequence | int，必填；最后 tool fact 序号；迁移默认 0 | Store | SQLite checkpoint 列 | 不一致为 integrity error | 已实现；schema v2，v1 migration default=0，RunState 校验连续性 |
| NextAction.action_kind | enum：model / tool_execution / tool_attempt / final | Store checkpoint codec | 持久化 | action 与引用字段需符合精确组合 | 已实现；白名单编码/解码及 `_validate_state` |
| NextAction.response_record_id | string 或 null；final 时引用 model_response core record，其余 action 为 null | Store | 持久化 | 必须指向同 Run 正确类型记录 | 已实现；兼容原 model/final JSON，validator 检查同 Run 引用 |
| NextAction.tool_call_sequence | int 或 null；tool_execution/tool_attempt 指向当前调用意图 | Store | 持久化 | 必须引用当前 batch 的下一项 ToolCallFact | 已实现；action codec 与 RunState validator |
| NextAction.attempt_id | string 或 null；tool_attempt 时引用当前未决 attempt | Store | 持久化 | 仅 tool_attempt 允许；必须是无结果 start fact | 已实现；action codec、attempt/result validator 校验 |
| RunState.tool_facts | tuple[ToolExecutionFact, ...]；按 tool_sequence 排序 | Store read API 返回；validator 校验 | 内部 state；不直接序列化为 public Run；repr 隐藏事实 payload | 双序列引用及 cursor/action 必须一致 | 已实现；读取校验无 dispatch 副作用 |
| RunStatus | 现有 running/completed/failed/interrupted；不增加 needs_reconciliation | Store/Run coordinator | public Run summary 仍只暴露原状态 | 未决 attempt 保持 running，checkpoint action 为 tool_attempt | 已确认保持现有字段 |
| RunStreamEvent.payload | 现有 allowlisted lifecycle fields；不增加 tool args/result/continuation | Event codec | public event | 不允许持久执行 payload 出现在事件中 | 已确认不变 |

### API、事件与错误

| API/event/error | 调用/触发方 | 输入 → 输出字段 | 校验、错误结果与安全消息 | 副作用、顺序、幂等/重试 | 状态与证据 |
|---|---|---|---|---|---|
| RunCoordinator.commit_model_response | 上层执行 owner 提交 normalized ProviderResponse | session_id/run_id/expected_revision/response/registry_version → core response record、ToolCallFacts 与 checkpoint | bounded tool_calls 需 registry version；continuation 非空返回 UNSUPPORTED_PAYLOAD | response、tool facts、双 cursor/checkpoint 同一事务；不能只提交一部分 | 已实现；`coordinator.py` + `store.py` |
| FiguraRunStore.begin_tool_attempt | DurableToolExecutor | Run/revision/tool_call_sequence/registry_version/replay_effect → attempt-start fact | 校验当前 action、Run running、同 Run 调用与 Registry version；stale revision 拒绝 | start fact 必须先于 handler；Store CAS，Executor 外围持 Run lock | 已实现；`store.py` |
| ToolRuntime.invoke | DurableToolExecutor | ToolInvocation + ToolContext(run/session/call/idempotency key) → ToolExecutionResult | 有界参数、结果、错误；幂等写缺 key 返回 bounded failure；身份错拒绝 | 每次 attempt 调用一次；ToolRuntime 内不 retry | 已实现；单次 dispatch + 幂等键存在性保护 |
| FiguraRunStore.commit_tool_result | DurableToolExecutor / 内部 reconciliation | expected revision + attempt_id + result → ToolResultFact + next checkpoint action | 校验最新 attempt、call ID、工具名和 outcome；完整 fact ≤512 KiB | result 与 tool cursor/checkpoint 原子提交；重复提交拒绝，不重跑 handler | 已实现；`store.py` |
| FiguraRunStore.begin_tool_replay_attempt | DurableToolExecutor 持锁恢复 | 当前 unresolved action + previous attempt ID + registry version → 新 attempt-start fact | 只允许最新无结果 attempt；拒绝 reconcile_required、已知结果、Registry mismatch | attempt number +1；原 call_id 与 replay_effect 沿用 | 已实现；`store.py` CAS |
| DurableToolExecutor.execute_pending / recover_unknown_attempt / reconcile_unknown_attempt | 内部 Run 执行 owner / 受信 reconciliation caller | Session/Run → 已推进或仍未决的 RunState | 锁获取后读 RunState；Registry version 与 replay_effect 必须匹配；reconcile_required 不 dispatch | 串行 handler；read 不恢复；lock/registry mismatch fail closed | 已实现；`tool_execution.py` |
| RunStreamEvent | Run 生命周期 owner | 当前 lifecycle payload → public safe event | 不含参数、工具结果、continuation、handler exception/raw payload | 不增加工具调用公开事件 | 已确认不变 |
| RunErrorCode | Coordinator/Store/Executor | 复用现有 bounded enum：stale revision 用 STALE_CHECKPOINT，非法状态/Registry/lock 不匹配用 INVALID_TRANSITION，非法 payload/version/integrity/storage 使用既有对应码 | 不向消息加入参数、工具结果、路径或 handler 原始异常；不新增 public event | 错误不得泄露执行数据 | 已实现；`errors.py` 未新增 public error code |
| ToolExecutionResult.error.retryable | ToolRuntime → durable result | bool 与错误信息 | 不得仅据此自动重放未知副作用 | 仅作工具错误合同，不替代 replay_effect | 当前字段已实现 |

### 安全、资源与兼容

- **敏感数据**：工具参数与结果可能含用户内容；owner 为 Run durable store；仅内部 RunState/恢复 executor读取。不得进入 Run.to_public_dict、RunStreamEvent、日志、异常 trace 或 provider continuation 公共投影。
- **锁与恢复**：`.run-locks` 目录权限为 0700，lock 文件名为 Run ID 的 SHA-256、权限为 0600；锁文件不写执行内容、不记录路径或 key。使用 OS advisory lock，无租约回收；竞争、平台不支持或权限异常时不写 attempt、不调用 handler。
- **资源限制**：每 response ≤64 calls；每项参数≤64 KiB UTF-8、aggregate ≤1 MiB；结果对象 canonical JSON ≤256 KiB；完整工具事实≤512 KiB；工具名≤64 ASCII chars；call ID≤256 bytes；registry version≤128 bytes。所有限制在事务写入前检查。结果编码/持久化失败时不推进 checkpoint、不伪造结果，attempt 保持未知并按 replay policy 恢复。
- **版本与兼容**：SQLite PRAGMA user_version 由1迁移至2；迁移仅新增工具事实表与 checkpoint tool cursor，不重建 core records 表，保留原有数据、opaque IDs、序号、事件、唯一约束和触发器。新工具事实 schema_version=1；迁移后旧 checkpoint action 的 model/final JSON 仍可解码。响应含 continuation仍被拒绝；工具 event/API公共协议不扩展。

## 3. 核心流程

### 正常工具批次

1. **触发与输入**：上层提交当前 model checkpoint 对应的 ProviderResponse；Coordinator 校验 Provider/Model、响应 finish_reason、工具调用数量、call ID/name/arguments 与 continuation。
2. **执行与校验**：无 continuation 时按 Provider 返回顺序生成 ToolCallFact；Registry version 与 batch 一起绑定。ToolExecutor 只读取 checkpoint 指向的下一项。
3. **状态/持久化/事件**：模型响应、所有 ToolCallFact 与第一个 tool action checkpoint 在一个事务提交。每次执行先提交 attempt-start，再调用 ToolRuntime；返回后 result fact、revision、下一项 action 在一个事务提交。工具执行不产生新的 public lifecycle event。
4. **返回结果**：所有工具项完成后 checkpoint 指向 model action；本 change 不发下一次 Provider 请求。RunState 可重建工具意图、执行结果和当前动作。
5. **失败、结果未知与恢复**：已知 validation/handler 失败作为 ToolResultFact 保存；结果事务失败时不推进 checkpoint，attempt 保持未知。取得同一 Run 锁并确认旧 owner 已退出、registry version 匹配后，按 replay_effect 恢复：replay_safe 重放；idempotent_local_write 使用跨 attempt 稳定键重放；reconcile_required 等受信内部调用提交核对结果。

| 实体/状态 | 触发与前置条件 | 状态变化/副作用 | 终态、并发或重入规则 |
|---|---|---|---|
| Model response with tool calls | 当前 action=model、响应合法且无 continuation | 原子追加响应及有序调用意图；checkpoint→tool_execution(first call) | 每个 response 的调用 ID/position 唯一；超限整批无部分提交 |
| Pending tool call | checkpoint action=tool_execution，且调用和 Registry version 匹配 | 同事务追加 attempt-start、推进 tool cursor；action→tool_attempt(attempt_id) | 获得 Run lock 的单一 executor 才能调用 handler |
| Started attempt | DurableToolExecutor 持有 Run lock | 调用一次 ToolRuntime handler | 锁持有到结果事务完成；同一 Run 不可并发 dispatch |
| Completed attempt | handler 返回有界 ToolExecutionResult | 原子追加 ToolResultFact 并推进 tool cursor；action 指向下一 call 或 model | 结果已提交后恢复仅读 durable result，不重跑 handler |
| Unknown attempt | 有 start fact、无结果；旧 owner 已被同一 Run lock 排除 | replay_safe / 幂等本地写按稳定身份产生新 attempt；reconcile_required 保持 tool_attempt 等待受信结果 | 不假设 handler 未执行；RunState read 无副作用 |
| Registry mismatch | durable fact version 与可用 Registry 不一致 | 不调用 handler；checkpoint 保持未决 | fail closed；不得将旧调用静默映射到新定义 |

~~~mermaid
sequenceDiagram
    participant Caller
    participant Coordinator
    participant Store
    participant Executor
    participant ToolRuntime
    Caller->>Coordinator: ProviderResponse with ordered tool calls
    Coordinator->>Store: Commit response, call facts, checkpoint atomically
    Executor->>Store: Claim current call and append attempt_started
    Store-->>Executor: attempt_id and new revision
    Executor->>ToolRuntime: Invoke one ToolInvocation
    ToolRuntime-->>Executor: ToolExecutionResult
    Executor->>Store: Commit result and advance checkpoint atomically
    Store-->>Executor: next action or model action
~~~

## 4. 实现对照

| 字段/组件/行为 | 本 change 计划 | 当前代码 | 主规格/OpenSpec | 差异、影响与后续 owner | 证据/状态 |
|---|---|---|---|---|---|
| ToolRuntime dispatch | 继续复用单次、同步、有界 dispatch，不在该层持久化 | 单次安全 dispatch；幂等本地写入无 key 时拒绝 handler | tool-runtime 主规格保持不变；幂等 key 与 durable dispatch 合同已记入 durable-tool-execution 主规格 | DurableToolExecutor 在上层负责 durable lifecycle | `src/figura/tools/runtime.py`、`contracts.py`；已实现 |
| replay_effect | attempt-start 时快照分类与 Registry version；按确认策略恢复 | 初次执行持有 Run lock；replay_safe/idempotent 重开 attempt；reconcile_required 保持未决，受信结果复用原 attempt | durable-tool-execution delta 定义三类恢复 | 不按 `retryable` 自动重试；registry mismatch 不 dispatch | `runtime/store.py`、`runtime/tool_execution.py`；已实现 |
| Run facts | core stream 保持 input/model_response/final_answer；工具意图、attempt、结果使用单独 tool stream | ToolExecutionFact 独立序号与 append-only 表 | run-execution-core 主规格已记录双序列与 references；durable-tool-execution 主规格记录工具事实合同 | `RecordKind` 不扩充；双流状态由 validator 检查 | `runtime/models.py`、`_codec.py`、`store.py`；已实现 |
| checkpoint | 增加 tool sequence cursor 和 tool_execution/tool_attempt action | checkpoint 保存两条 cursor 及当前 action 引用 | run-execution-core 主规格已记录双 cursor 与 action；durable-tool-execution 主规格记录推进和恢复约束 | v1 migration 将 cursor 默认 0；旧 model/final JSON 仍可读 | `runtime/models.py`、`store.py`；已实现 |
| SQLite schema | v1→v2 additive migration；新增工具事实表与 tool cursor | `_SCHEMA_VERSION=2`；迁移在一事务内新增列/table/triggers 并 FK/quick-check | change design 明确不重建 immutable core records 表 | v1 fixture 验证保留原 Run/records/checkpoint/events/idempotency/triggers；失败回滚 | `runtime/store.py` 与 migration tests；已实现 |
| ModelResponseFact | 保留在 core stream；每个 ToolCallFact 通过 response_record_id 关联模型响应 | 支持无 continuation 的工具响应；模型响应+意图+checkpoint 原子提交 | durable-tool-execution 与 run-execution-core 主规格已记录该转换；本 change 不含 Provider continuation 合同 | continuation 仍拒绝；后续 continuation change 负责 | `runtime/coordinator.py`、`store.py`；已实现 |
| ToolResultFact | 保存结构化 success/error 供后续 history 重建 | ToolRuntime 返回有界成功或失败；Store 原子提交 result 和下一 action | durable delta 定义结果与恢复边界 | canonical result≤256 KiB；完整 tool fact≤512 KiB；失败作为已完成结果不自动 retry | `tools/contracts.py`、`runtime/_codec.py`、`store.py`；已实现 |
| Provider continuation | 排除 | ProviderResponse continuation 仍保持 transient；Coordinator 拒绝含 continuation 的响应 | provider 主规格与本 change delta 仍要求后续单独定义持久化 | 不影响当前 no-continuation tool-call commit；后续 continuation change 负责 | `providers/models.py`、coordinator tests；本 change 已验证拒绝 |
| Public events | 不加 tool args/results 事件 | 保持 Run lifecycle event allowlist；tool facts、errors、idempotency key 不进入 public summary/event/ordinary logs | run spec 主规格不变 | Gateway/UI 后续需另定可公开投影 | `Run.to_public_dict`、event codec、privacy tests；已验证 |
| 有序批处理 | 按 Provider 原顺序串行执行，不并行 | DurableToolExecutor 每项均完成 result commit 后再推进下一项 | tool-runtime 禁止内部重排/并行/retry；durable delta 规定 provider 顺序 | 不自动 retry 已知失败；结果未知时批次暂停并由 recovery 单独处理 | `runtime/tool_execution.py`、ordered-batch tests；已验证 |
| 调用上限 | 每 response≤64 calls；每项参数≤64 KiB、aggregate≤1 MiB；result≤256 KiB；完整 tool fact≤512 KiB | 各限额在 codec/runtime/store 路径生效，超限写入被拒绝 | durable delta 新增 durable 批次预算；主 spec 待同步 | 结果 commit 失败时 start remains unresolved，不伪造结果 | `tools/limits.py`、`runtime/_codec.py`、`store.py`、边界测试；已验证 |
| Per-Run execution lock | attempt claim 至 handler 完成和 result commit 持有同一 OS lock | 不同 Run 独立 lock；竞争失败后不写 start / 不调 handler | change design 明确不使用 lease expiration | POSIX `fcntl.flock`；平台/权限错误 fail closed | `runtime/_run_lock.py`、executor contention tests；已实现 |
| completion gate | 不允许绕过未执行或 unresolved tool work 直接完成 | complete_run 在写 final/status/event 前验证完整 RunState 与 tool action | delta spec 要求 completion 不越过 pending/unresolved facts | text-only STOP 路径兼容，记录和 event contract 不变 | `store.py`、corrupt-action regression tests；已实现 |

## 5. 验证与交接

### 验证

| 类型 | 精确命令/操作 | 结果/预期 | 覆盖边界与来源 |
|---|---|---|---|
| 已观察验证（实现回合） | `conda run -n agent python -m pytest tests/test_figura_durable_tool_execution.py tests/test_figura_run_execution_core.py tests/test_figura_tool_runtime.py tests/test_figura_tool_registry.py tests/test_figura_json_schema.py tests/test_figura_provider.py -q` | 114 passed | 前序实现回合记录；覆盖 SQLite migration/CAS、dispatch/recovery、replay effects、privacy、compatibility、provider/tool runtime；本次规格同步未重跑应用测试 |
| 已观察验证（实现回合） | `conda run -n agent python -m pytest -q` | 679 passed in 51.87s | 前序实现回合记录；全仓 Python 回归，不包含真实模型 API 调用；本次规格同步未重跑应用测试 |
| 已观察验证（实现回合） | `openspec validate add-figura-durable-tool-execution --strict --no-interactive --store figura` | `Change 'add-figura-durable-tool-execution' is valid` | 前序实现回合记录；本次规格同步再次验证 |
| 已观察验证（规格同步回合） | `openspec validate add-figura-durable-tool-execution --strict --no-interactive --store figura` | `Change 'add-figura-durable-tool-execution' is valid` | 归档前活动 change 的 proposal/spec/design/tasks 结构与内容校验 |
| 已观察验证（本次规格同步） | `openspec validate --specs --strict --store figura` | 4 passed, 0 failed | durable-tool-execution、model-provider、run-execution-core、tool-runtime 主规格 |
| 已观察验证（规格同步回合） | `openspec status --change "add-figura-durable-tool-execution" --json --store figura` | 17/17 tasks complete；当时 change 仍 active，主规格已同步 | 归档前的 OpenSpec 生命周期核对 |
| 已观察验证（本次归档） | `openspec list --json --store figura`；`find openspec/figura/openspec/changes/archive/2026-09-26-add-figura-durable-tool-execution -type f` | 活动 change 列表为空；archive 中保留 `.openspec.yaml`、planning artifacts 与两个 delta specs | 确认归档完成且工件齐全 |
| 已观察验证（本次） | `git diff --check` | exit 0，无 whitespace errors | 本次实现改动格式检查 |

### 交接

- **待确认及影响**：无待确认项；replay_effect 分类与幂等键计算规则均按已确认方案实现。
- **未实现/暂缓**：Provider continuation、模型请求attempt恢复、完整ReAct循环、模型轮次/工具轮次上限、真实领域工具、Gateway/CLI/UI。
- **前置或后续 change**：前置 add-figura-run-execution-core、add-figura-tool-runtime；后续单独定义 Provider continuation durability，再建立 ReAct AgentExecutor；最终由领域工具 change接入 chart capabilities。
- **下一 owner/入口**：实现、主规格同步、change 归档和本记录回填均已完成；后续开发方向见索引中的 Provider continuation 持久化与 Agent ReAct 核心循环。
