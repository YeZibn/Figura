# `add-figura-run-execution-core` · Run 与执行事实持久化基础

> 返回 [Figura 实现内容索引](../../figura-implementation-content.md)。

> 最近更新：2026-09-26。实施状态：已实现。OpenSpec 状态：主规格已同步、change 已归档。

## 1. 概览与决定

**来源与基线**

- 问题/目标来源：为 Figura 后续模型/工具执行提供独立于 ChartAgent 的 durable Session/Run 身份、执行事实、checkpoint、幂等和恢复读取基础。
- 代码证据：[runtime/models.py](../../../src/figura/runtime/models.py)、[coordinator.py](../../../src/figura/runtime/coordinator.py)、[store.py](../../../src/figura/runtime/store.py)、[_codec.py](../../../src/figura/runtime/_codec.py)、[errors.py](../../../src/figura/runtime/errors.py)。
- 主规格：[run-execution-core](../../../openspec/figura/openspec/specs/run-execution-core/spec.md)。
- 归档 change：[proposal](../../../openspec/figura/openspec/changes/archive/2026-09-26-add-figura-run-execution-core/proposal.md)、[design](../../../openspec/figura/openspec/changes/archive/2026-09-26-add-figura-run-execution-core/design.md)、[tasks](../../../openspec/figura/openspec/changes/archive/2026-09-26-add-figura-run-execution-core/tasks.md)。
- Provider 前置合同：[model-provider](../../../openspec/figura/openspec/specs/model-provider/spec.md)。当前 Figura store 无活动 change；主规格和归档文件均已确认。

**目标与范围**

- **问题与目标：** 提供内部 Python API 持久创建 Session/Run；将不可变输入、模型文本响应、最终答复保存为版本化事实；checkpoint 与 record/event 在一个事务内推进；按 Session 读取并 fail closed。
- **本 change 的对象/字段范围总览：**

| 对象 | 本次合同字段范围（逐字段定义见“实现合同 / 字段与数据合同”） | 本次行为边界 |
|---|---|---|
| Session | session_id、name、created_at、updated_at | Session identity 与轻量 name |
| Run | run_id、session_id、ordinal、input_record_id、status、provider、model、created_at、started_at、finished_at、terminal_code、terminal_message、final_record_id | 单一 owner、固定 provider/model、唯一终态 |
| RunCreateRequest / RunInput | session_id、text、provider_id、model_id、idempotency_key、attachment_ids、requested_provider、requested_model、schema_version | 当前只接受非空文本和空附件 |
| ExecutionRecord / payload | record_id、run_id、record_sequence、record_kind、payload、created_at；input/model_response/final_answer payload fields | append-only、versioned、bounded |
| ExecutionCheckpoint / NextAction | run_id、revision、last_committed_record_sequence、next_action、schema_version、updated_at、action_kind、response_record_id | compare-and-swap；current actions 仅 model/final/null |
| RunIdempotency | session_id、idempotency_key_digest、request_fingerprint、run_id、created_at | session scoped key digest；不存原始 key/body |
| RunStreamEvent | run_id、event_sequence、event_kind、payload、created_at | allowlisted 生命周期事件，不传输入/模型正文 |
| RunState / RunError | run、records、checkpoint、events；code、safe_message | 内部状态读模型与固定错误合同 |

- **可观察完成结果：** 同一 Session 的重复相同 create request 返回同一 Run；非法或重复冲突请求不留部分数据；响应事实/最终事实与 checkpoint/终态/event 原子一致；read 返回已提交前缀且不重放模型或工具。
- **包含：** SQLite v1、Session 创建、Run 创建/idempotency、text-only response commit、finalize、fail/interruption、session-scoped read、bounded codecs、lifecycle events。
- **不包含：** ProviderClient 调用、background runner、attachment 处理、ToolRegistry、Prompt、工具执行、retry/resume child Run、Gateway/SSE、CLI/UI、continuation 持久化、数据 retention/cleanup 策略。
- **前置依赖：** 注入 data_root；现有 ProviderFactory.availability 供配置检查；调用方提供 Session、文本、显式 allowlisted provider/model 和幂等 key。

**决定与依据**

| 主题 | 决定/事实 | 决策状态 | 实施状态与证据 | 影响字段/组件 |
|---|---|---|---|---|
| 存储边界 | Figura独立SQLite文件，不复用ChartAgent数据目录；store root由构造参数注入 | 已确认 | 已实现；design、store.py | FiguraRunStore |
| Session/Run identity | opaque UUID hex；Run.ordinal在Session内单调递增 | 已确认 | 已实现；design、主规格、store.py | Session/Run |
| Provider/model | create时显式验证并同时保留requested与实际选择 | 已确认 | 已实现；coordinator.py、主规格 | Run/RunInput |
| 当前输入 | 非空非纯空白bounded text；attachments必须为空 | 已确认 | 已实现；主规格、coordinator.py | RunCreateRequest/RunInput |
| 原子创建 | Run、input record、初始checkpoint、idempotency row、run_created event一次事务 | 已确认 | 已实现；design、store.py | 各持久实体 |
| Idempotency | Session范围；保存key SHA-256 digest与normalized request fingerprint | 已确认 | 已实现；design、coordinator.py、store.py | run_idempotency |
| Checkpoint | 使用正整数revision做compare-and-swap，不以checkpoint内容hash为权威ID | 已确认 | 已实现；design、store.py | ExecutionCheckpoint |
| 事实提交 | 只支持input/model_response/final_answer；record append-only，与checkpoint同事务 | 已确认 | 已实现；codec、store.py、主规格 | ExecutionRecord |
| Terminal owner | RunCoordinator/Store共同执行唯一终态转换；terminal不可再次修改 | 已确认 | 已实现；coordinator.py、store.py、主规格 | Run.status/terminal fields |
| Read behavior | 恢复读取fail closed，不请求Provider、不执行tool、不推断未提交进度 | 已确认 | 已实现；store.py、主规格 | RunState |
| Provider调用 | Run创建只查本地availability，不构造transport、不发网络请求 | 已确认 | 已实现边界；coordinator.py、design | create_run |
| Root directory、保留期限、opaque resume ID | 交composition/resume设计决定 | 待确认 | 未实现/待决；Open questions | data_root/checkpoint/cleanup |

## 2. 实现合同

### 组件与职责

| 组件/源码路径 | 职责 | 输入合同 | 输出合同 | 依赖/调用关系 | 状态/证据 |
|---|---|---|---|---|---|
| runtime/models.py · domain records | 定义 Session/Run/request/fact/checkpoint/event/state/status/action enums | typed field values | frozen dataclasses/enums | coordinator/store/codec共享 | 已实现 |
| runtime/coordinator.py · RunCoordinator | 校验请求、显式 provider/model、idempotency、response，委托 store 原子转换 | RunCreateRequest、revision、ProviderResponse | Session/Run/ExecutionRecord/RunState 或 RunError | 依赖 FiguraRunStore、ProviderFactory | 已实现 |
| runtime/store.py · FiguraRunStore | 管理 SQLite schema、transaction、record/checkpoint/event/Run rows 和 restart reads | validated domain payloads | persisted rows and reconstructed state | SQLite、本地 codec、RunCoordinator | 已实现 |
| runtime/_codec.py | 严格版本化 JSON 编解码及 JSON byte bounds | typed payload/event | bounded canonical JSON/domain values | store 使用 | 已实现 |
| runtime/errors.py | 固定 RunErrorCode/safe_message | bounded internal failure category | RunError | coordinator/store/codec使用 | 已实现 |
| providers.ProviderFactory | 仅用于检查显式 provider 的本地配置可用性 | provider/model selection | availability metadata | create_run 调用；不建 transport | 已实现依赖边界 |
| SQLite tables/triggers | durable owner：sessions/runs/records/idempotency/checkpoints/events；record/event 禁止 update/delete | typed writes | commit/read rows | FiguraRunStore 事务 | 已实现；store.py |

### 字段与数据合同

以下逐字段表合并 dataclass logical contract 与 SQLite/JSON 表示；未另注时每行均为已实现字段，末列是代码证据；除明确说公开投影外，均为内部字段。Timestamps 是 UTC ISO-8601 字符串，store 生成 microseconds + Z；ID 为 UUID hex，读取/查找还要求非空且 UTF-8 ≤128 bytes。

#### Session 与 Run

| 字段路径 | 类型/必填/可空/默认/边界 | 来源、owner、读写时机 | 生命周期/持久化 | 暴露/校验/证据 |
|---|---|---|---|---|
| Session.session_id | str；必需；生成 UUID hex | store.create_session创建；session-scoped API读取 | sessions PK；持久 | opaque ID；≤128 bytes；store.py |
| Session.name | str或None；默认None；≤256 UTF-8 bytes | create_session caller提供；当前无rename API | sessions.name；持久 | Run/event不复制；超限invalid_request；coordinator/store |
| Session.created_at | UTC ISO-8601 str；必需 | store生成 | sessions.created_at；持久，不更新 | internal timestamp；store.py |
| Session.updated_at | UTC ISO-8601 str；必需；创建时与created_at一致 | store生成；当前无更新API | sessions.updated_at；持久 | 不向event复制；store.py |
| Run.run_id | str；必需；生成 UUID hex | store.create_initial_run | runs PK；持久 | opaque；≤128 bytes；store.py |
| Run.session_id | str；必需；引用所属Session | create request；store/coordinator读 | runs FK；持久，不可改属主 | Session scoped read只返回owner匹配记录；store.py |
| Run.ordinal | int；必需；>0；Session内递增 | store事务分配 | runs UNIQUE(session_id,ordinal)；持久 | run_created event可暴露；store.py |
| Run.input_record_id | str；必需；同Run input record ref | create事务生成 | runs composite FK；持久 | Run摘要不含input正文；store.py |
| Run.status | RunStatus；必需；running/completed/failed/interrupted；创建为running | coordinator/store写 | runs.status；持久 | 唯一terminal；非法迁移invalid_transition；models/store |
| Run.provider | str；必需；≤64 bytes；当前allowlisted ID | coordinator规范化后创建 | runs.provider；持久固定 | public summary可投影；不含credentials；coordinator/store |
| Run.model | str；必需；≤128 bytes；匹配provider model | caller显式请求、coordinator校验 | runs.model；持久固定 | public summary可投影；coordinator/store |
| Run.created_at | UTC ISO-8601 str；必需 | store生成 | runs.created_at；持久 | 可在summary公开；store.py |
| Run.started_at | UTC ISO-8601 str；必需；当前等于created_at | create事务写入 | runs.started_at；持久固定 | 代表接受创建，不表示worker已执行；design/store |
| Run.finished_at | str或None；running时None；terminal时写入 | terminal transaction写 | runs.finished_at；持久 | summary可投影；store.py |
| Run.terminal_code | str或None；running时None；terminal时固定枚举 | terminal owner写 | runs.terminal_code；持久 | safe enum；store.py/models.py |
| Run.terminal_message | str或None；terminal时由固定消息表生成；≤256 bytes | RunCoordinator/TERMINAL_MESSAGES | runs.terminal_message；持久 | safe message，不含异常正文；models.py/store.py |
| Run.final_record_id | str或None；完成前None；完成时指final_answer record | complete transaction写 | runs composite FK；持久 | summary可公开opaque ref；store.py |

#### RunCreateRequest、RunInput 与事实 payload

| 字段路径 | 类型/必填/可空/默认/边界 | 来源、owner、读写时机 | 生命周期/持久化 | 暴露/校验/证据 |
|---|---|---|---|---|
| RunCreateRequest.session_id | str；必需非空；≤128 bytes | caller创建；coordinator校验/store校属主 | request临时；input不重复存 | private scope input；models/coordinator |
| RunCreateRequest.text | str；必需；1–64KiB UTF-8，非纯空白 | caller创建；coordinator校验 | request临时；成功后保存在input payload | repr隐藏；从Run摘要/event排除；coordinator |
| RunCreateRequest.provider_id | str；必需；≤128 bytes且allowlisted | caller显式指定；coordinator解析 | request临时；规范化复制至Run与RunInput | summary可投影；coordinator |
| RunCreateRequest.model_id | str；必需；≤128 bytes且为该provider固定model | caller显式指定；coordinator校验 | request临时；复制至Run与RunInput | summary可投影；coordinator |
| RunCreateRequest.idempotency_key | str；必需非空；≤128 UTF-8 bytes | caller每次创建提供；coordinator hash | raw key仅请求内存；持久化只存digest | repr隐藏；不得存raw；coordinator/store |
| RunCreateRequest.attachment_ids | tuple[str,...]；默认空；当前任何非空都拒绝 | caller创建；coordinator校验 | request临时；input payload只写空列表 | unsupported_payload；coordinator |
| RunInput.text | str；必需；≤64KiB UTF-8、非空白 | coordinator从request创建 | input JSON payload，schema_version=1；record sequence 1 | repr隐藏；事件/Run摘要不含；codec |
| RunInput.attachment_ids | tuple[str,...]；必需；实际必须空 | coordinator创建 | payload JSON空数组；持久 | 暂无attachment data暴露；非空拒绝；codec |
| RunInput.requested_provider | str；必需；≤64 bytes；当前存canonical provider ID | coordinator规范化后写 | input payload持久 | 私有record；Run summary只含实际provider；codec |
| RunInput.requested_model | str；必需；≤128 bytes | coordinator规范化后写 | input payload持久 | 私有record；summary含实际model；codec |
| RunInput.schema_version | int；默认1；仅支持1 | domain/codec | JSON payload持久 | 未知版本unsupported_version；models/codec |
| ModelResponseFact.provider_id | str；必需；≤64 bytes；须等于Run.provider | 来自ProviderResponse/coordinator | model_response payload持久 | record为内部事实；coordinator/codec |
| ModelResponseFact.model_id | str；必需；≤128 bytes；须等于Run.model | 来自ProviderResponse/coordinator | model_response payload持久 | coordinator/codec |
| ModelResponseFact.assistant_content | str；必需；≤128KiB UTF-8 | ProviderResponse/coordinator | JSON payload持久 | repr隐藏；Run summary/event不暴露；coordinator/codec |
| ModelResponseFact.finish_reason | str；必需；≤32 bytes；当前Provider FinishReason | ProviderResponse/coordinator | JSON payload持久 | 仅stop且非空白可finalize；coordinator/store |
| ModelResponseFact.usage | ProviderUsage或None；默认None | ProviderResponse | JSON payload持久 | 每项0–2³¹−1，否则拒绝；codec |
| ModelResponseFact.provider_response_id | str或None；默认None；≤512 bytes | ProviderResponse | JSON payload持久 | opaque provider metadata；codec |
| ModelResponseFact.schema_version | int；默认1；仅支持1 | domain/codec | JSON payload持久 | 未知版本unsupported_version；codec |
| ProviderUsage.prompt_tokens | int或None；默认None；0–2³¹−1 | Provider normalize | 嵌入model_response payload | 有界数值；codec |
| ProviderUsage.completion_tokens | int或None；默认None；0–2³¹−1 | Provider normalize | 嵌入model_response payload | 有界数值；codec |
| ProviderUsage.total_tokens | int或None；默认None；0–2³¹−1 | Provider normalize | 嵌入model_response payload | 有界数值；codec |
| FinalAnswerFact.response_record_id | str；必需；≤128 bytes；引用同Run已提交response | coordinator/store校验 | final_answer payload持久 | 不复制response正文；非法引用integrity/transition error |
| FinalAnswerFact.artifact_refs | tuple[str,...]；默认空；decode最多64但本change只接受空 | future artifact owner；当前coordinator/store | payload持久为空数组 | 非空unsupported_payload；codec |
| FinalAnswerFact.guard_version | str；默认且只接受text-only-v1；≤64 bytes | coordinator/domain固定 | payload持久 | 不是图表/工具审核；codec/store |
| FinalAnswerFact.schema_version | int；默认1；只支持1 | domain/codec | payload持久 | 未知版本unsupported_version；codec |

#### Record、checkpoint、event 与内部读模型字段

| 字段路径 | 类型/必填/可空/默认/边界 | 来源、owner、读写时机 | 生命周期/持久化 | 暴露/校验/证据 |
|---|---|---|---|---|
| ExecutionRecord.record_id | str；必需；UUID hex | store append时生成 | run_execution_records PK | opaque；同Run unique pair；store.py |
| ExecutionRecord.run_id | str；必需；引用Run | store创建 | records FK；持久 | Session scoped state内返回；store.py |
| ExecutionRecord.record_sequence | int；必需；>0；Run内连续递增 | store事务分配 | UNIQUE(run_id,sequence)；持久 | 只读状态按序返回；store.py |
| ExecutionRecord.record_kind | RecordKind；必需；input/model_response/final_answer | coordinator/store选择 | records column持久 | 未知kind unsupported_payload；store/codec |
| ExecutionRecord.payload | RunInput/ModelResponseFact/FinalAnswerFact；必需；repr隐藏 | coordinator传store；codec序列化 | payload_json ≤256KiB；immutable trigger禁止update/delete | private事实；Run summary/event不包含；codec/store |
| ExecutionRecord.created_at | UTC ISO-8601 str；必需 | store写入 | records持久 | internal timestamp；store.py |
| ExecutionRecord schema_version column | int；>0；当前payload version 1 | codec/store derived | records.schema_version持久 | reader拒绝未知version；codec/store |
| ExecutionCheckpoint.run_id | str；必需；Run PK/FK | store初始创建 | 每Run一行 | internal state；store.py |
| ExecutionCheckpoint.revision | int；必需；>0；初始1 | store每次commit递增 | checkpoint持久 | CAS token；陈旧值返回stale_checkpoint；store.py |
| ExecutionCheckpoint.last_committed_record_sequence | int；必需；>0；初始1 | store与record原子更新 | checkpoint持久 | 必须指向已提交前缀；否则integrity_error；store.py |
| ExecutionCheckpoint.next_action | NextAction或None；初始model；终态完成时None | store推进 | next_action_json ≤1024 bytes | internal；read时完整校验；codec/store |
| ExecutionCheckpoint.schema_version | int；必需；当前1 | store写入 | checkpoint持久 | 未知版本fail closed；store.py |
| ExecutionCheckpoint.updated_at | UTC ISO-8601 str；必需 | store写入/推进 | checkpoint持久 | internal timestamp；store.py |
| NextAction.action_kind | ActionKind；model/final | store创建或推进 | 嵌入checkpoint JSON | model不带response ref；final必须有ref；store.py |
| NextAction.response_record_id | str或None；model时None，final时引用response | commit response生成final action | 嵌入checkpoint JSON | 同Run reference检查；store.py |
| RunStreamEvent.run_id | str；必需 | store event writer | event表FK | scope内返回；store.py |
| RunStreamEvent.event_sequence | int；>0；与record seq独立 | store事务分配 | PK(run_id,event_sequence) | event identity为run_id:sequence；store.py |
| RunStreamEvent.event_kind | EventKind；四种固定生命周期值 | store按transition写 | event列持久 | 非法值fail closed；models/store.py |
| RunStreamEvent.payload | Mapping[str,EventValue]；immutable mapping | codec/store创建 | JSON ≤16KiB；append-only | allowlist payload，不含输入或正文；codec.py |
| RunStreamEvent.created_at | UTC ISO-8601 str；必需 | store写入 | event表持久 | safe metadata；store.py |
| run_created.payload.session_id | str；必需≤128 bytes | 创建Run store事务 | event payload持久 | 可读opaque ID；不含input；codec.py |
| run_created.payload.ordinal | int；必需>0 | 创建Run store事务 | event payload持久 | 可公开ordinal；codec.py |
| run_completed.payload.final_artifact_refs | tuple；当前必须空 | complete transaction | event payload持久为空数组 | 不泄露response正文；codec.py |
| run_failed/run_interrupted.payload.terminal_code | str；固定TerminalCode | terminal transaction | event payload持久 | 不含异常原文；codec.py |
| RunState.run | Run；必需 | store读取时构造 | read model临时对象 | Run summary projection可公开；models.py |
| RunState.records | tuple[ExecutionRecord,...]；必需；repr隐藏 | store读取已提交前缀 | read model临时对象 | 内含私有输入/响应，只给内部owner；models.py |
| RunState.checkpoint | ExecutionCheckpoint；必需 | store读取校验后构造 | read model临时对象 | 内部恢复事实；models.py |
| RunState.events | tuple[RunStreamEvent,...]；必需 | store按event seq读取 | read model临时对象 | 仅安全payload；models.py |
| run_idempotency.session_id | str；必需 | create事务 | idempotency PK的一部分 | Session scope；store.py |
| run_idempotency.idempotency_key_digest | hex SHA-256 str；64 chars | coordinator对raw key hash | 持久；PK与session_id | 不保存raw key；store.py/coordinator.py |
| run_idempotency.request_fingerprint | hex SHA-256 str；64 chars | coordinator规范化request后hash | 持久 | 不保存raw request，但文本hash泄露相等性；store.py/coordinator.py |
| run_idempotency.run_id | str；必需 | create事务写 | FK至同Session Run | opaque reference；store.py |
| run_idempotency.created_at | UTC ISO-8601 str | create事务写 | 持久；无自动清理 | cleanup retention未定义；store.py |
| RunCreateRequest.idempotency_key | str；1–128 UTF-8 bytes；repr隐藏 | caller提供、coordinator hash | 仅请求内存，持久只存digest | key冲突时返回固定idempotency_conflict；coordinator.py |
| RunError.code | RunErrorCode；必需；固定枚举 | coordinator/store/codec | exception内存 | 对外安全分类；errors.py |
| RunError.safe_message | str；必需；由code映射固定文案 | RunError构造 | exception内存 | 不包含SQLite/provider原始文本；errors.py |

枚举：RunStatus=running/completed/failed/interrupted；RecordKind=input/model_response/final_answer；ActionKind=model/final；EventKind=run_created/run_completed/run_failed/run_interrupted；TerminalCode=execution_failed/invalid_response/storage_error/interrupted。RunErrorCode 全量见“API、事件与错误合同”。集合顺序：records按record_sequence、events按event_sequence；idempotency仅一行/session+key digest；attachment_ids/artifact_refs本change必须空。

### API、事件与错误合同

| API/event | 调用者 | 入参 | 返回 | 校验与错误 | 副作用/幂等/顺序 | 协议/证据 |
|---|---|---|---|---|---|---|
| FiguraRunStore(data_root) | composition owner | 注入的root path | 已初始化store | sqlite error转STORAGE_ERROR；高版本转UNSUPPORTED_VERSION | 建立figura.sqlite3；schema init | store.py |
| create_session(name?) | internal app | optional name | Session | name≤256 UTF-8 | INSERT一行；无rename | coordinator/store |
| create_run(RunCreateRequest) | internal app | session/text/provider/model/key/attachments | Run | validates所有字段与本地provider availability | transaction写Run、input、checkpoint、idempotency、event；重复同请求返回原Run | coordinator/store |
| read_run_state(session_id,run_id) | internal recovery/app | session/run IDs | RunState | owner、序号、version、reference和cursor integrity | 只读；不重放执行 | coordinator/store |
| commit_model_response(session,run,expected_revision,response) | execution owner | identity/revision/ProviderResponse | ExecutionRecord | 只接无tool calls、无continuation、正确provider/model的 bounded text response | response record与checkpoint原子推进 | coordinator/store |
| complete_run(session,run,expected_revision) | execution owner | identity/revision | final ExecutionRecord | 当前action=final；response合法、同Run、stop且非空白 | final fact、Run terminal、checkpoint清action、event一次提交 | coordinator/store |
| fail_run(session,run,revision,terminal_code) | execution owner | identity/revision/非interrupted terminal code | failed Run | running + current revision；code不能是INTERRUPTED | terminal metadata、checkpoint revision、event同事务 | coordinator/store |
| interrupt_run(session,run,revision) | execution owner | identity/revision | interrupted Run | running + current revision | terminal metadata、checkpoint revision、event同事务 | coordinator/store |
| Run.to_public_dict() | future API projection | Run | bounded summary dict | omit input_record_id/payload | no storage side effect | models.py |
| RunStreamEvent.to_public_dict() | future event/API projection | safe event object | dict with allowed payload | payload由codec allowlist构造 | no storage side effect | models.py/codec.py |

没有HTTP route/SSE；Provider external request也不由此change触发。RunStreamEvent 是数据库事实，不代表已实现 event delivery。

**错误、重试与恢复**

| RunErrorCode | 触发点/结果 | 是否暂时/能否重试 | 已提交状态 | 安全消息 | 恢复owner |
|---|---|---|---|---|---|
| INVALID_REQUEST | 参数类型、空白文本、ID或key长度非法；拒绝前失败 | 否；修正请求后重来 | 无创建副作用 | Run请求无效。 | caller |
| SESSION_NOT_FOUND | create/read目标Session不存在 | 否；不能盲目建新Session替代 | 无 | 未找到可用的Session。 | caller |
| RUN_NOT_FOUND | Session不拥有/不存在Run | 否；检查opaque IDs | 无 | 未找到可用的Run。 | caller |
| PROVIDER_UNAVAILABLE | provider配置缺失或本地不可用 | 配置修复后可新试；不触网 | create前无Run | 所选模型服务当前不可用。 | config owner |
| IDEMPOTENCY_CONFLICT | 同Session key digest对应不同请求fingerprint | 否；换合法新key或恢复原请求 | 原Run不变，无第二Run | 幂等键已用于不同的Run请求。 | caller |
| STALE_CHECKPOINT | expected_revision旧 | 需先read；不能盲重放外部模型工作 | 无部分record/checkpoint/event | Run执行进度已变化，请重新读取。 | execution owner |
| INVALID_TRANSITION | Run非running或action不匹配 | 否；按当前状态决定后续 | 无部分提交 | Run当前状态不允许此操作。 | RunCoordinator |
| UNSUPPORTED_PAYLOAD | attachment/tool/continuation/artifact或大小/结构超界 | 否；feature owner实现前不重试 | transaction无部分写入 | Run执行记录不受支持或超出范围。 | feature owner |
| UNSUPPORTED_VERSION | DB/payload/checkpoint版本未知 | 否；不可自行降级/重放 | read/write fail closed | Run数据版本不受支持。 | migration owner |
| INTEGRITY_ERROR | 引用、sequence、cursor、schema不一致 | 否；无自动修复 | 不返回不可信state | Run持久数据未通过完整性检查。 | storage/recovery owner |
| STORAGE_ERROR | SQLite失败 | 可能暂时，但不可假定commit状态；重新read后由caller判断 | 事务rollback代码路径；commit断连结果需read确认 | Run数据暂时无法读取或保存。 | store owner |
| TerminalCode | execution_failed/invalid_response/storage_error/interrupted | 持久安全原因，不包含raw exception | terminal run/event写入同一事务 | 由固定TERMINAL_MESSAGES映射 | RunCoordinator |

Run核心本身没有外部Provider请求，因此其错误不能证明模型调用未发生于上游；执行层必须避免以盲重试造成重复外部动作。

### 安全、隐私与资源上限

| 数据/资源 | owner/合法来源 | 可读组件 | 传输/持久化/保留 | 日志/公开投影 | 上限与拒绝 | 证据 |
|---|---|---|---|---|---|---|
| RunInput.text | caller | coordinator/store及持有RunState的内部owner | SQLite JSON明文持久；保留期未定义 | repr隐藏；Run summary/event不含 | 非空白且≤64KiB | coordinator/codec |
| ModelResponseFact.assistant_content | normalized ProviderResponse | coordinator/store/internal state reader | SQLite JSON明文持久 | repr隐藏；Run summary/event不含 | ≤128KiB | coordinator/codec |
| API credentials/base_url | Provider config owner | Run只读availability projection | 不复制到Run/SQLite | event/summary不含 | 无Run层存储字段 | coordinator/models |
| idempotency raw key | caller | create coordinator | 仅请求期内存 | repr隐藏；不持久 | 1–128 UTF-8 bytes | coordinator |
| idempotency key digest | coordinator SHA-256 | store | SQLite持久，无清理策略 | 不进public projection | exactly 64 hex chars | coordinator/store |
| request fingerprint | coordinator canonical JSON SHA-256 | store | SQLite持久；可透露相等性；无retention policy | 不进public projection | exactly 64 hex chars | coordinator/store |
| provider response ID | ProviderResponse | coordinator/store | input payload JSON持久 | event不含；内部metadata | ≤512 UTF-8 bytes | coordinator/codec |
| terminal_message/code | TerminalCode mapping | coordinator/store | Run row + safe lifecycle event | 可投影固定文案/枚举，不含异常 | message≤256 bytes | models/store/codec |
| RunStreamEvent payload | store allowlist factory | event reader | SQLite JSON持久 | safe public dict；immutable append-only | ≤16KiB；4种event payload固定key | codec/store |
| ExecutionRecord payload | coordinator typed facts | store/internal recovery owner | SQLite JSON持久、不可变trigger | repr隐藏；public Run摘要不带 | ≤256KiB；不支持未知payload/version | codec/store |
| SQLite database | injected data_root owner | process/OS account | figura.sqlite3；WAL；无应用层加密；保留期未定义 | 不返回本地路径 | DB安全依赖运行环境文件权限；代码未单独设ACL/encryption | store.py/design |
| IDs/JSON/collections | domain/store owner | coordinator/store | SQLite | opaque refs；不带本机路径 | ID≤128 bytes；checkpoint action≤1024；artifact refs解码≤64但实际只空 | models/codec/store |

**版本、兼容与迁移**

- SQLite PRAGMA user_version 当前为1。空数据库执行初始schema；version>1拒绝；version=1直接打开。当前只有初始schema，没有从旧Figura schema升级的migration。
- input/model_response/final_answer JSON payload 内 schema_version=1；未知版本以 UNSUPPORTED_VERSION fail closed。
- ExecutionCheckpoint schema_version=1；checkpoint action JSON有界并检查字段/引用。
- Event JSON没有独立schema_version；event_kind和payload字段集合通过codec allowlist固定校验。
- ProviderOptions/Run API为内部Python contracts，无独立HTTP API version。
- 没有已有 Figura Run 数据迁移；后续增字段需加显式数据库与payload migrations，不得静默删除旧事实。
- 不适用：旧数据兼容/降级在首次schema change前不存在；当前不能读取未知高版本。

## 3. 核心流程

### 状态与事务

| 实体/操作 | 起始→目标状态 | 前置与触发 | 原子边界 | 并发/终态规则 | 失败影响/证据 |
|---|---|---|---|---|---|
| Session create | absent→present | name合法 | 单INSERT事务 | ID唯一 | 回滚则无Session；store.py |
| Run create | absent→running | input有效、Session存在、model allowlisted且本地available、key有效 | Run+input seq1+checkpoint rev1/action=model+idempotency+run_created seq1一次BEGIN IMMEDIATE | Session ordinal唯一；同key/fingerprint返回原Run；相同key不同fingerprint冲突 | 任一步失败整体rollback；store/coordinator |
| Model response commit | running/action=model→running/action=final | expected_revision匹配；response与Run provider/model一致且无tools/continuation | append record+checkpoint sequence/revision/next_action一次事务 | revision CAS；stale拒绝且不产生partial record/event | rollback；store.py |
| Complete | running/action=final→completed/action=null | ref属于同Run且response finish_reason=stop、内容非空白 | final record+Run terminal fields+checkpoint+event一次事务 | terminal唯一；revision CAS | rollback无terminal event；store.py |
| Fail | running→failed | revision匹配；TerminalCode非interrupted | Run terminal metadata+checkpoint revision+event一次事务 | 唯一终态；保留next_action/cursor | 回滚无部分状态；store.py |
| Interrupt | running→interrupted | revision匹配 | Run terminal metadata+checkpoint revision+event一次事务 | 唯一终态；保留next_action/cursor | 回滚无部分状态；store.py |
| Session-scoped read | persisted→validated RunState | run belongs to session | 只读SQLite连接，不改数据 | records/events顺序检查 | 不一致fail closed；store.py |

**端到端流转**

1. caller先创建Session，再提交RunCreateRequest；Coordinator检查字段、text大小/空白、empty attachments、allowlisted provider/model、key长度。
2. Coordinator先确认Session归属，再计算idempotency_key_digest与request_fingerprint；相同请求返回已存在Run，key复用但请求变化时报冲突。
3. 新请求只读取ProviderFactory.availability；不创建ProviderClient、不建立transport、不发供应商网络调用。
4. store在BEGIN IMMEDIATE事务内分配Run ID/ordinal/record ID，写Run、sequence-1 input、revision-1 checkpoint、idempotency mapping和run_created event；任一失败全部rollback。
5. 后续模型响应由独立调用者提交；Coordinator拒绝不支持的tool calls/continuation；store用expected_revision原子append response并把action推进到final。
6. complete验证response和同Run引用，原子写final fact、completed状态、final ref、完成时间、清空action、增加revision并append事件。fail/interruption写固定终态信息，保留最后checkpoint action。
7. read只返回经过Session ownership、version、序号、ref与cursor检查的committed state；不自动重放provider/tool，不修补数据。

~~~mermaid
sequenceDiagram
    participant Caller
    participant Coordinator
    participant ProviderFactory
    participant Store
    participant SQLite
    Caller->>Coordinator: create_run(request)
    Coordinator->>ProviderFactory: availability() local only
    ProviderFactory-->>Coordinator: selected provider available
    Coordinator->>Store: create_initial_run(typed input + digests)
    Store->>SQLite: BEGIN IMMEDIATE; Run + record + checkpoint + idempotency + event
    SQLite-->>Store: commit
    Store-->>Caller: running Run
    Caller->>Coordinator: commit_model_response(expected_revision, response)
    Coordinator->>Store: validated text-only fact
    Store->>SQLite: append response + advance checkpoint atomically
    SQLite-->>Caller: committed response record
    Caller->>Coordinator: complete_run(expected_revision)
    Coordinator->>Store: finalize
    Store->>SQLite: final fact + terminal Run + checkpoint + event
    SQLite-->>Caller: completed Run
~~~

## 4. 实现对照



| 字段/组件/行为 | 原计划/design | 当前代码 | 主规格/OpenSpec | 差异/影响 | 后续owner/证据 |
|---|---|---|---|---|---|
| data root | 由上层部署/Runtime决定默认位置 | Store强制接收data_root | 主规格不指定默认目录 | path provisioning留composition层 | Runtime composition/design |
| Session rename | 早期对象表描述name/update可变化 | 当前只有create_session；无rename API | 主规格仅定义身份隔离 | updated_at当前不再推进 | Session lifecycle owner |
| checkpoint ID | 架构草案倾向可派生opaque ID | 实际以整数revision CAS | design明确选择revision | 未来resume ID另做，不作为当前authority | Recovery change/design |
| Run启动语义 | 字段名started_at可能被理解为worker已执行 | create时与created_at相同；无worker | 主规格定义创建为running | 表示接受到持久Run，不代表Provider work启动 | Execution integration |
| attachments | 规划未来引用授权附件 | 当前只允许空列表 | 主规格明确本change拒绝非空attachments | 上传/授权/读取仍未实现 | Attachment change |
| tool/continuation facts | 后续事实类型方向 | response commit拒绝tool_calls和continuation | 主规格要求fail explicitly | 先做受控continuation存储/工具fact | Provider/Tool changes |
| Provider invocation | 后续通过execution loop接入 | create只查availability；commit接受response，不调用模型 | 主规格限定create无网络副作用 | 当前核心不能独立完成一轮模型对话 | Execution integration |
| public events | 未来由transport delivery | 只持久化RunStreamEvent；无HTTP/SSE delivery | 主规格明确传输层在change外 | Gateway/SSE仍未完成 | Gateway change |
| final artifact | 未来可引用artifact refs | 当前只接受空refs和text-only-v1 | 主规格限定text-only final | 图表artifact审核/publish仍未实现 | Artifact/review change |
| retention/recovery | 后续保留与child Run策略 | 无清理、retry/resume child Run | Open questions留待后续 | 不可声称已支持durable resume executor | Storage/Recovery owner |

## 5. 验证与交接

### 验证

#### 计划验证

| 目标 | 精确命令/操作 | 可观察预期 | 边界 |
|---|---|---|---|
| Run durable behavior、transactions、idempotency、terminal/read integrity | conda run -n agent python -m pytest -q tests/test_figura_run_execution_core.py | focused tests通过 | 本地SQLite；非Gateway/SSE集成 |
| Provider contract dependency | conda run -n agent python -m pytest -q tests/test_figura_provider.py | Provider mock tests通过 | 不触发真实provider |
| 主规格 | Figura run-execution-core strict OpenSpec validation | requirements/scenarios通过 | 静态规格校验 |
| 文档差异 | git diff --check -- docs/figura-implementation/changes/add-figura-run-execution-core.md | 无空白错误 | 仅本文档 |

#### 已观察验证

| 日期 | 实际命令/操作 | 实际结果 | 覆盖边界与来源 |
|---|---|---|---|
| 2026-09-26，既有实现记录 | conda run -n agent python -m pytest -q tests/test_figura_run_execution_core.py | 21项通过 | SQLite Run behavior；本次未重跑 |
| 2026-09-26，既有实现记录 | conda run -n agent python -m pytest -q tests/test_figura_provider.py | 15项通过 | Provider mock suite；本次未重跑 |
| 2026-09-26，既有实现记录 | Run主规格 strict validation | 通过；具体CLI未保留 | 不补造命令；本次确认spec/archive存在 |
| 2026-09-26，既有实现记录 | git diff --check | 通过；旧记录未保留路径参数 | 非本次行为验证 |
| 本次回填 | 只读核对runtime源码、主规格和归档工件 | 未运行应用测试 | 仅用于本次字段/流程文档校正 |

### 交接

- **后续依赖/change：** Provider execution adapter/worker；continuation私有持久化；attachments authorization/loader；ToolRegistry/tool facts；Prompt；Gateway/SSE；CLI/UI。
- **待确认：** data_root默认值；Session rename/API需要；数据保留和清理期限；opaque resume checkpoint ID格式；Provider profile/policy version如何固定。
- **未实现/暂缓：** Provider请求执行、background runner、retry/resume child Run、非空附件、tool execution、continuation persistence、Gateway/SSE、CLI/UI、artifact review/promotion。
- **交接：** 此 change 提供持久化事实和应用协调器；后续执行change负责worker与安全resume策略，不得在read路径重放外部动作。
