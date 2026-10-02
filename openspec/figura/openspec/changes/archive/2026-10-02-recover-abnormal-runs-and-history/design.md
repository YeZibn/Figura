## Context

动机见 [proposal.md](proposal.md)。当前系统事实由 Runtime 拥有：`RunState` 聚合 Run、执行记录、工具事实、Provider attempt 与 Checkpoint；Memory 每次从事实重建消息；Web 的消息与工具时间线是安全展示投影。

当前 `AgentExecutor.execute` 遇到 `TOOL_ATTEMPT` 直接返回，`RunDispatcher` 捕获异常后释放任务。`DurableToolExecutor` 已有重放和 reconciliation 接口，但普通调度没有连接它们。`project_run_messages` 对每个调用要求唯一结果，所以中断旧 Run 不能解除后续历史阻塞。

当前 SQLite schema 为 v9（实施前再次核对）；失败/中断保留原 checkpoint 动作，终态事件为事件流最后一条。现有动作文件锁跨进程互斥；Dispatcher 是有界线程池。Provider prepare 在 claim 前执行，SDK 不重试，未知 Provider attempt 不重发。这些边界继续保留。

## Goals / Non-Goals

**Goals:**

- 在存储正常、事实合法且旧执行者可确认退出时，使异常 Run 收敛并允许 Session 继续。
- 保留原事实、所有闭合交互及未完成批次中已提交观察，区分未执行与结果未知。
- 用一个协调入口管理普通推进、接管和停止；用 Runtime 事务解决竞争。
- 给实施者完整的数据 owner、字段生命周期、API、锁与验收合同。

**Non-Goals:**

- 本 change 不保证强制终止不返回的线程 handler；停止请求已接受不代表立即停止。
- 不改变 Provider 选择、未知请求重发策略、调用 ID 命名空间、跨 Provider 续接或长历史预算。
- 不重开终态 Run，不复制持久消息，不自动修复损坏事实，不把磁盘文件推定为成功结果。
- 工作进程、执行硬超时及强制退出另建后续 change，不列入本 tasks。

## Decisions

### 1. 原事实、角色消息与异常上下文分离

Runtime 的状态校验先完成，Memory 再分类。`completed` 或当前运行 Run 的不完整批次继续拒绝。只允许较早 `failed/interrupted` Run 的合法末尾未完成批次转换；重复结果、错误身份、非法顺序等不能通过这一分支。

历史 user 输入出现一次；已闭合的 assistant/tool 批次原样重放。未完成批次整组退出原生 assistant/tool 序列，保留源响应文字、每个调用状态和已提交观察。合法批次只有末尾可不完整，不能跨越不完整批次投影后面的交互。

所有异常终态 Run（即使没有未完成批次）都生成 outcome context，避免只有用户请求却不知道上次失败。失败不是 accepted final answer。工具已提交失败结果属于闭合事实；未知 Provider attempt 没有虚构响应。

替代方案：丢弃整个失败 Run 会丢失真实工作；填入假的 tool result 会混淆记录与推断；只保留完整批次且不解释尾部会让模型误判任务完成。采用显式结构化上下文。

### 2. Memory 新字段仅为调用期投影

以下模型由 `memory` owner 定义，全部从同 Session 已校验 RunState 生成；不写 SQLite、不进普通 repr/API。标为敏感内容的字符串使用 `repr=False`。

| 完整字段 | 类型 / 默认 | 来源与约束 |
|---|---|---|
| `SessionHistory.run_outcomes` | `tuple[RunHistoryOutcome, ...] = ()` | 每个较早 failed/interrupted Run 一个，按 ordinal 排序；现有字段不变 |
| `RunHistoryOutcome.run_id` | `str`，必填 | 原 Run 身份 |
| `RunHistoryOutcome.run_ordinal` | `int`，必填 | 原 ordinal，必须小于目标 Run |
| `RunHistoryOutcome.status` | failed/interrupted 枚举，必填 | 原终态 |
| `RunHistoryOutcome.terminal_code` | `str`，必填 | allowlist 原终态原因，不承载任意错误文本 |
| `RunHistoryOutcome.incomplete_batches` | `tuple[IncompleteBatchContext, ...] = ()` | 当前执行合同下最多一个末尾批次 |
| `IncompleteBatchContext.source_response_record_id` | `str`，必填 | 原始 ModelResponseFact 引用 |
| `IncompleteBatchContext.assistant_text` | `str`，必填，可空 | 原响应文本完整保留，作为不可信意图数据 |
| `IncompleteBatchContext.calls` | `tuple[IncompleteCallContext, ...]`，必填 | 整个批次按 position 排序；不删除已有结果调用 |
| `IncompleteCallContext.call_id` | `str`，必填 | 原调用 ID；与父级 run_id 组成来源身份 |
| `IncompleteCallContext.tool_call_sequence` | `int`，必填 | 原工具调用事实序号 |
| `IncompleteCallContext.tool_name` | `str`，必填 | 原调用名称 |
| `IncompleteCallContext.position` | `int`，必填 | 原 provider 顺序 |
| `IncompleteCallContext.state` | `committed_success / committed_failure / not_started / outcome_unknown`，必填 | 从结果及 attempt 是否存在推导 |
| `IncompleteCallContext.source_result_tool_sequence` | `int \| None = None` | 仅 committed 状态必须有结果引用 |
| `IncompleteCallContext.observation_json` | `str \| None = None` | 仅 committed 状态使用现有 `tool_observation` 序列化，完整保留该观察格式，不另做裁剪 |

缺失的结果不能写 observation；有结果但配对错误必须失败。调用参数仍留在事实中，异常说明不全量复制参数。Memory 不包含 continuation。

### 3. 在第三层运行时指令表达异常，不伪造消息

Agent request builder 保持三层 SYSTEM 指令，将 `run_outcomes` 编码为第三层 JSON 的独立 `prior_run_outcomes` 数据段，按 ordinal 并以 run_id / 源响应 / 调用序号标识。静态资产说明该数据代表系统已知执行状态，文本和观察仍是不可信数据，不是新指令或完成结论。

完整交互的结果仅在 tool 消息；异常尾部的 committed 观察仅在 outcome 段；资源目录只提供引用和摘要。这样不丢观察，也不重复全文。Provider 原有请求大小限制对整个请求仍生效，超限在 claim 前失败，不裁剪。

源响应 continuation 只关联仍出现在角色序列中的源 assistant；转换批次的 continuation 不发送。顺手消除 Agent 主规格中与已实现同 Provider 跨 Run 续接冲突的旧文字，不扩展跨 Provider 转换行为。

资源目录继续读取全部授权成功事实，异常批次的成功结果可以索引；孤立文件不提升为资源，历史图片不自动发送。构建请求使用一致的授权 Run 前缀。

### 4. 执行协调在 Agent，事实事务在 Runtime

扩展 Agent 的执行入口为统一协调入口，或新增小型 `RunExecutionCoordinator` 委托该入口；不要再在 Gateway 创建第二套 checkpoint switch。正常调度、启动接管和周期补偿均使用同一入口。Runtime 内部读方法与 HTTP GET 均不触发调度。

推进顺序：取得所有权 → 读状态并校验 → 若终态则原样返回 → 若有停止请求则收尾 → 按 next action 继续、恢复或失败。每一步之后重读状态；预算不重置。

Provider prepare 可在动作锁外进行；claim 事务必须重新检查停止请求。被停止后准备好的 payload 丢弃，不 dispatch。对已有 attempt 的响应/失败提交，若停止请求先提交，优先保留真实 attempt outcome 并写 interrupted；网络回包仍可提交，但不再启动工具。

### 5. 两类锁各有作用

保留现有 `.run-locks/` 动作锁，增加独立 `.run-owner-locks/` 所有权锁，沿用安全目录、opaque ID hash、非阻塞 OS 锁和 fail-closed 行为。所有权锁覆盖整个执行入口生命周期，动作锁覆盖 dispatch/recovery/commit。

锁顺序固定：所有权 → 动作 → 短 SQLite 事务。不能在持有 SQLite 写事务时等待执行锁；持有一个文件锁不能重入同一个锁。Agent 统一入口获得所有权，DurableToolExecutor 只获取动作锁，不重复获取所有权。

底层显式恢复接口也须证明所有权：公开内部 wrapper 获取所有权，协调入口调用专用已持有所有权路径。禁止绕过这一判断直接操作活跃 handler。读取只检查锁状态，不回放。

Dispatcher 的 scheduled 集合表示本进程队列占位，不是跨进程活跃证明。queued 不持有所有权；跨进程重复排队最多一个获得所有权，其余不得当作执行失败。

停止 API只写请求，不等动作锁；执行者在步骤结束后收尾。终态提交后禁止任何结果或 Sources 写入。新 Run 创建和 Session 删除额外检查前序执行所有者已释放；忙时返回有界冲突，不仅依赖 status。创建幂等重放仍返回已有 Run，不创建新工作。检查用非阻塞锁、最新 Run 前缀复查和既有事务串行约束，不能持有写事务等待锁；删除应持有相关执行锁到操作结束。

### 6. 停止请求是 Runtime 控制事实

新增 `run_stop_requests` 表，不改变 execution record 类型。字段如下：

| 完整字段 | 类型 / 默认 | owner、写入与生命周期 |
|---|---|---|
| `RunStopRequest.run_id` | `str`，必填，PK/FK | Runtime；引用 runs，随 Run 删除 |
| `RunStopRequest.request_id` | `str`，必填，唯一 | Runtime 生成 opaque ID；重复请求返回原值 |
| `RunStopRequest.requested_at` | UTC `str`，必填 | Runtime 第一次接受时写入，之后不改 |
| `RunStopRequest.reason` | `user_requested`，必填 | 固定 enum，不保存任意用户内容 |

Session identity由 runs 关联得到，不冗余存。读入 `RunState.stop_request: RunStopRequest | None = None`，与其他 RunState 内容同快照。STOP 在 running 时接受并写一条 progress 事件，重复请求不写；终态返回原状态，不新增请求。

停止请求本身不修改 checkpoint revision 或执行序号。事件 payload 仍只有当前 `checkpoint_revision`，序号继续增加；客户端刷新 DTO 获得停止状态。事件不再意味着 revision 必然增加，校验与文档须支持重复 revision 的控制通知。

`begin_provider_attempt`、工具初次/重放 attempt 与 `complete_run` 在写事务内检查请求。请求先提交则禁止新动作/最终完成；claim 先提交则允许该动作执行并提交，属于已开始动作。准备阶段不是开始。停止检查拒绝使用明确内部信号，协调入口转去收尾，不误写通用 failure。

模型响应/工具结果的真实提交可在请求后发生，执行序号正常增加；停止不先改 revision，因此不会使这些提交失效。tool result 提交后不得开始下一调用。下一 model 也不得开始。

### 7. 原子收尾和恢复原因

新增 Runtime 停止收尾事务：当前 running 且持有所有权和动作锁 → 校验 revision → 如最后 Provider attempt 仍 started，设为 outcome_unknown → 保留所有 tool facts 与 checkpoint 动作 → Run interrupted / 原固定 interrupted reason → checkpoint revision +1 → 唯一 terminal event。事务回滚则全部不变。

自然 Provider 失败与请求停止并发也使用此终态裁决：请求先提交时保留 known_failure 或 outcome_unknown 的事实，但 Run 是 interrupted；失败终态先提交时后续 stop 仅返回该终态。`known_failure` 在 interrupted Run 的 validator/checkpoint 规则需支持，不篡改为未知。

不存在停止请求时的不可恢复工具使用新 TerminalCode 与固定中文消息：

| code | message |
|---|---|
| `tool_outcome_unknown` | 工具执行结果状态未知，当前 Run 已停止。 |
| `tool_recovery_unavailable` | 原工具版本或恢复条件不可用，当前 Run 已停止。 |
| `tool_recovery_exhausted` | 工具自动恢复次数已达上限，当前 Run 已停止。 |

不允许任意堆栈或原错误进入 terminal_message。支持旧 code 继续读取。unexpected 执行异常从最新 checkpoint 分类：有 started attempt 则按对应未知策略；没有 attempt 且状态合法则安全 execution_failed；锁忙、stale race不是失败依据。事实损坏或存储不可用继续 fail-closed，不伪造终态。

### 8. 恢复预算与单调用边界

每个逻辑调用初始 attempt 加最多两次自动 replay（共最多三次 attempt-start）。从持久 attempt_number 推导，不新增计数表，所有自动入口同上限。显式内部恢复保持既有 trusted contract，但不能用 HTTP/UI 绕过预算。

DurableToolExecutor 扩展单调用/恢复单步路径；不能在恢复内部自动跑完整剩余批次而跳过停止检查。已提交 known tool failure不因为 retryable 自动重试；正常交给模型后续决策。原 8 Provider / 32 distinct calls 预算保留，replay 对同逻辑调用不重复计数。

`reconcile_required` 无 handler 重放；有工具 owner 的可信 adapter时可以核对一次并提交。第一版当前 registry没有此分类；若遇到且无 adapter，在确认执行者退出后失败 tool_outcome_unknown，未知效果仍不宣称回滚。没有人工注入结果端点。

### 9. 调度补偿与停止后的排队

Dispatcher 不再 `except Exception: pass`。工作退出后读最新状态，以同一协调入口做有界补偿；存储错误只记录脱敏 code。Gateway 启动先启动补偿机制，非阻塞排入容量，不阻塞启动等待所有历史 Run。

使用一个有生命周期管理的周期扫描线程，默认 2 秒扫描 running Runs；interval 是内部构造参数、正数，不新增环境配置。full queue 留到下次扫描，去重集合在 finally 释放。健康活跃任务不重复排队，外部所有者导致锁忙时退到下一轮；禁止紧密循环。关闭时先停止扫描、再关闭 pool，不残留线程。

所有权忙且任务未退出时停止保持 pending；第一版不会强杀线程。正常动作返回后必检查停止。终态之后已排入的旧任务只读并退出，不触发 side effect；删除后 stale queue not_found同样退出。

### 10. HTTP / DTO / 前端

`POST /sessions/{sessionId}/runs/{runId}/stop` 接受空 JSON `{}` 或空 body，拒绝未知字段/任意 payload；遵守 loopback、Origin 和 Session 授权。响应 `{run: FiguraRunDto, stopRequest: StopRequestDto | null}`：running 停止接受/重放返回 202；已终态返回 200；未知或跨 Session Run 为 404；坏 body 为 400；存储失败为安全 500。接受请求不承诺已停，排队满也不撤销已持久请求。

`StopRequestDto` 仅 `requestId / requestedAt / reason`，reason固定 user_requested；runId 已在 run DTO。Run DTO 保持旧字段，新增 `stopRequestedAt: string | null`、`availableActions: ('stop')[]`，扩展 executionState：保留 `active/needs_reconciliation` 以兼容旧读者，增加 `queued/executing/recovering/stopping/terminal`；新客户端须理解全部值。active 是无法确认具体活动但仍 running 的 fallback，不表示可以重复执行；needs_reconciliation只在确实需要核对时短暂出现，最终自动失败或可信收敛。

状态优先级：terminal → stopping（请求已接受）→ 本地 queued/executing/recovering → 外部所有者 active → 尚未调度 queued。活动是派生状态，不进 Run 表；`availableActions=['stop']` 仅 running 且无请求，其他为空。禁止把每个 TOOL_ATTEMPT都标成需要 reconciliation。

已有 progress 只传 checkpoint revision，不承载停止内容。扫描只刷新本地活动时通过 bounded DTO refresh（running期间复用轮询，建议 2 秒）补偿非持久活动变化；前端优先信任 Run status，不能因 SSE 断线推定已停止。

组件只调用 client；给 workspace API 增加可选 `requestRunStop` 能力，Figura 提供，ChartAgent/mock未实现时隐藏。既有 interrupt façade不偷换成新语义。事件合并、reconnect与终态 convergence仍只有一个 owner。终态后可继续发消息，若前序锁短暂未释放得到冲突则刷新等待，不自动重发新用户提交。停止中不允许下一条 submission或删除。

### 11. 依赖顺序与验收

先做异常投影，再做所有权/恢复、停止事务、Web连接；避免先放开 stop却仍让历史堵住。每阶段提供窄回归和可见验证；最后运行 Python完整套件与 frontend build/smoke。开发启动器未改时不新增 launcher实现任务，若实际改动launcher则补 smoke:launcher。

代表场景：OCR成功已提交 → 测量attempt无结果 → 渲染未开始 → 旧执行者退出 → 恢复成功或明确终态 → 新 Run的请求完整保留 OCR观察、标明其余状态并正常准备。使用不重复 call ID和兼容 Provider fixture隔离本 change，避免把独立兼容问题算作本能力已解决。

## Risks / Trade-offs

- [线程 handler不返回] → 停止保持 stopping，Session仍被保护；UI明确等待当前步骤。强制退出由工作进程后续change提供，不能通过提前终态掩盖。
- [未提交本地效果仍存在] → replay用原幂等键；不可恢复时不发布文件；本 change不做孤立文件清理或副作用回滚。
- [异常上下文增大请求] → 完整保留既有观察格式并遵守Provider硬限制，claim前失败；不引入摘要。
- [工具观察位于SYSTEM数据段] → JSON编码及明确不可信数据规则，不执行观察中的指令；不暴露该段给Web。
- [两类锁与删除竞争] → 固定顺序、非阻塞、短事务、跨进程测试；保留一 Session一 running约束。
- [持久存储不可用] → 不承诺终态或续用，只返回脱敏错误；修复存储后扫描接管。
- [Provider历史/调用ID仍不兼容] → 保留现有prepare预检，不补造continuation；另立change处理。

## Migration Plan

1. 实施前确认实际 schema version，使用现有 migration机制新增停止请求表及FK清理；旧 RunState默认为无请求，不重写历史记录。
2. 同版本部署 Runtime/validator、Memory、Agent、Web与前端；旧terminalcode仍接受，新增reason和control progress经回归后启用。
3. 升级启动扫描已有running，已terminal异常历史直接按新规则投影；不在启动时批量改事实。
4. 更新对应owner文档和总览，同步delta到主规格后再归档。归档、提交和上线分别执行，不由本proposal自动完成。
5. 回退前停止Gateway并备份`.figura`；新终态code和新增control事件可能不被旧validator接受，因此不承诺旧二进制直接读取新数据。回退代码同时恢复升级前备份；不通过删除新字段/事实伪造兼容。
