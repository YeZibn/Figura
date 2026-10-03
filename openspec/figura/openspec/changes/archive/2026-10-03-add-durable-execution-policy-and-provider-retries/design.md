## Context

动机见 [proposal.md](proposal.md)。本设计是待实现合同，不代表当前代码已支持重试。

当前实现证据集中在 `src/figura`：`agent/executor.py` 有每 Run 8 次 Provider attempt、32 个已启动逻辑工具调用；8 次限制还存在于 `runtime/persistence/providers.py`、`runtime/record_validation.py` 和 SQLite `run_provider_attempts` 的序号 CHECK。`agent/request.py` 固定输出 4096 tokens。Provider SDK 已设置 `max_retries=0`，当前失败后直接终止，通用异常也被宽泛判为 transient。

Provider attempt 目前用 `(run_id, base_record_sequence, base_tool_sequence)` 唯一约束表达一个模型动作，不能表达同一动作多个网络尝试；验证器还假定失败 attempt 只能是终态最后一个。工具则已区分明确失败 observation 与未知结果恢复，但恢复最多 3 次实际执行主要由 Agent 检查，repository 入口还需补齐。ToolContext 的 cancellation 尚未接入持久化 stop。

数据库当前 schema 10；Record、ToolFact、continuation 在 codec 和 SQL 中分别有 256/512/512 KiB 保护。Gateway 使用 3 个 worker、8 个排队槽，一次 executor 调用执行整个 Run，扫描从列表开头填队列；直接放开 Run 次数会让长期任务占用 worker。

## Goals / Non-Goals

**Goals:** 正常任务可持续执行；同一失败操作的恢复有持久化、有限且可证明安全的边界；Agent、Runtime、Provider、Tool 和 SQL 不重复定义微上限；所有外部动作继续先 claim、后执行、再原子提交。

**Non-Goals:** 不建立 ExecutionPolicy/RunBudgetSnapshot 或 token 预留结算体系；不做 ContextPlan、压缩、摘要、窗口裁断、输出补发、模型 fallback；不新增明确失败工具的自动重试策略；不修改 legacy chartagent；不承诺杀死同步/native handler 或让远端生成停止。

## Decisions

### 1. 先删除累计配额，再按职责保留技术约束

选择删除，而非调大默认值或把配额变成一组可选配置。正常工具批次不做预算整批准入；完整响应及意图批次仍必须在一个事务内校验并提交，再逐个调用工具。

| 边界 | 当前零散限制 | 本轮处理 | 唯一责任方 |
| --- | --- | --- | --- |
| Run 模型/工具数量 | 8 Provider attempts、32 已启动逻辑工具 | 删除 Agent、repository、验证器和 SQL 的累计限制 | Runtime 仅保留事实序列 |
| Run 总输出/时间/重试/存储 | 之前讨论中的候选配额 | 不引入任何累计配额或无进展自动终止 | 用户 stop、模型完成、确定失败 |
| Provider 单逻辑请求 | 无显式重试 | 首次加 3 次，最多 4 个已 claim 的物理 attempt，含 crash replacement | Runtime |
| 未知工具恢复 | 初始加 2 次自动 replay | 保留最多 3 个执行 attempt，并在 repository 强制 | Runtime，工具提供 replay 合同 |
| 单次输出 | Agent 4096、通用最大 131072 | 删除；可选正整数，由 Adapter 使用正确参数并检查有证据的协议范围 | Provider |
| Provider 请求结构 | 256 messages、32 instructions、64 tools、64 tool calls、1 MiB text/schema | 删除通用数量/小字节上限，采用完整 JSON 载荷保护 | shared 合同 + Adapter |
| Registry/Schema | 64 tools、512 KiB 总 Schema、128 KiB 单 Schema、2048 B description | 删除，按完整 Registry 投影保护，不丢定义 | Tools + shared |
| 通用 JSON/Schema | Schema 深度 16、Schema/value properties 256、enum 256 | 删除通用属性/enum 数量上限，Schema 与值均检查实际 JSON 深度 64 | shared |
| Tool 参数/结果/批次 | 64 KiB 参数、256 KiB 结果、1 MiB 批次参数 | 删除，完整 observation/批次应用同一载荷合同 | Tools/Runtime |
| call ID/name | ID 256 字符与 256 bytes 重复；name 64 | ID 不设独立长度限，保持有效 UTF-8、非空、原值、Run 内唯一及精确配对；name 保持非空和既有字符集，供应商真实长度由 Adapter 校验 | Tools/Provider/Runtime 同一 validator |
| Runtime 存储 | input 64 KiB、assistant 128 KiB、Record 256 KiB、ToolFact/continuation 512 KiB | 新版本使用统一完整载荷保护；旧版本仍可读 | Runtime codec + shared |
| 图片数量 | 通用 16 张、Run 最多 16 个附件引用 | 删除数量限制及所有共享引用；真实厂商数量约束由 Adapter 校验 | Provider/Runtime |
| 图片字节/解码 | 单图 `24 MiB - 64 B`、单请求原始图总量 32 MiB；Sources 格式/像素保护 | 保留，不计入 Run 累计用量；引用数量不等于发送图片数量 | Sources/shared image guards |
| 时间 | Provider timeout 默认 60 s、最大 600 s | 默认保留 60 s，删除最大 600；要求有限正数；是 I/O phase 等待，不是 Run deadline | Provider |
| 公共数据 | event 16 KiB、tool error message 512 B、pointer 256 B、terminal message 256 B | 保留展示/隐私边界，不能借此截断执行结果 | Runtime/Gateway |
| 元数据/领域 | 自有 ID 格式、schema/version、Session 名称、Chart/Measurement 领域 maxItems 等 | 保留协议身份与领域语义；不把领域 Schema 的 maxItems/maxLength 当通用数量限制删除 | 各语义 owner |
| 并发/排队 | 3 workers、8 queue slots、扫描 2 s | 保留，增加公平让出和到期调度 | Gateway |

Provider 原始响应 content/reasoning 的 1,048,576 字符等隐藏小上限也纳入删除审计。输出 Schema 的 maxItems/maxLength 属于工具声明的业务语义，仍需忠实执行。Provider 不明确支持某结构时显式拒绝，不放宽 Schema。

### 2. 一个单载荷合同，明确字节如何计算

在 `shared` 引入 `ExecutionPayloadLimits` 与严格 JSON 编码/解码入口，组合根注入相同实例，禁止各 owner 重新定义 bytes 常量。

| 字段/配置 | 类型与默认值 | 读写生命周期 |
| --- | --- | --- |
| `max_json_bytes` / `FIGURA_EXECUTION_PAYLOAD_MAX_BYTES` | 正整数，默认 `33_554_432`（32 MiB） | 启动解析一次；适用于新载荷准入，不是 Run 总量；无任意业务最大值 |
| JSON depth | 固定 64，root 深度 0，每层 object/array 加 1 | 解析和编码前检查；字符串内容不增加深度 |
| canonical encoding | UTF-8、`ensure_ascii=False`、紧凑 separators、稳定 object key 排序、拒绝 NaN/Infinity | 所有载荷 guard、fingerprint、codec 使用一致规则；列表顺序保留 |

载荷单元必须明确：Run input record、完整 Registry 的 model-visible 投影、单个 tool observation、完整 model-response transition（响应、全部 call intents、continuation，不含派生存储 ID）、完整 continuation envelope、单个持久化 record/tool fact，以及完整 Provider 结构化请求。保护完整批次，避免 N 个合规小参数合计绕过限制；不计算整个 Run/Session 的累计存储。

原始 `arguments` 字符串作为真实协议字符串计入 response/request 编码，另按相同入口解析为严格 JSON object；不解析后替换字符串改变请求。JSON 禁止重复 keys、非有限数、非 JSON 对象、非法 Unicode 和深度超限；数值类型、Schema 支持集合、必填、枚举成员及 unknown fields 规则保持。

Provider request 的 guard 覆盖所有文本、指令、schema、历史调用、continuation 和 options；图片块使用 `{media_type, byte_count, sha256}` 占位表示，原始图片采用独立字节/解码保护。真正 wire payload/fingerprint 包含真实 data URL，图片 base64 不再重复算入 32 MiB JSON guard，否则 32 MiB 原图会因约 4/3 膨胀被误拒绝。Adapter 新增具体厂商 wire 限制必须附来源/验证用例，不引入猜测的通用窗口值。

对原始 Provider response 使用同一 `max_json_bytes` 作完整响应 JSON body 接收保护，随后对规范化 transition 再按其实际编码检查；SDK envelope 也计入原始 body，不额外发明一个 envelope 配额。transport 必须在有界读取后才允许 SDK 解析，并在规范化过程中及时停止过大值；禁止仅在 SDK 已无限量解析后才声称内存受到保护。已有直接 Provider 流式调用保持兼容：有界读取/解析单事件并对本次响应原始 stream bytes 与规范化结果累计应用同一个guard，不将流变成无限缓冲；Agent仍non-streaming，不增加流式重试或输出补发。HTTP Run create JSON 则按同一配置读取；上传图片继续走 Sources 上传路径，公开事件/detail route 保留各自展示限额。

SQL 删除执行 payload 三张表的固定小字节 CHECK，保留 json_valid、外键、引用和不可变触发器；写事务必须从统一 codec 进入。增加私有 store metadata `execution_payload_read_ceiling_bytes`，记录本 store 曾准入的配置最大值，首次新版本为 32 MiB；提高配置与该 ceiling 更新在首次相应写入前原子完成，只增不减。读取旧版本继续按旧格式解码，读取新版使用该 ceiling 保护；降低新写入配置不会让既有事实不可读。metadata 不是每 Run 预算，不出现在公共 API。直接 SQL 写入不属于受支持写接口。

替代方案“保留 SQL 32 MiB 固定 CHECK、仅 Python 可配置”会使调大配置无效；“所有读都用当前配置”会因降配置破坏历史，所以不用。

### 3. 逻辑 Provider 请求与物理 attempt 分开

Runtime 新增一个**不可变私有请求绑定**，每个 model action 一个，不增加可变 operation 状态/重试计数表。状态由它的 attempts 与 checkpoint 推导。沿用现有 provider-attempt 状态：`started / response_committed / known_failure / outcome_unknown`。

`ProviderRequestBinding` 由 Runtime 存储，首个 claim 时与 attempt/checkpoint 一起写入：

| 字段 | 类型/约束 | 含义与来源 |
| --- | --- | --- |
| `operation_id`, `run_id` | opaque IDs、Run FK | 此 model action 的逻辑身份 |
| `base_record_sequence`, `base_tool_sequence` | 分别为正整数、非负整数 | 冻结请求对应的提交前缀；Run 及 earlier terminal Session Runs 均不可变 |
| `provider_id`, `model_id` | 与 Run 完全一致 | 禁止 retry fallback |
| `request_fingerprint` | SHA-256 hex | 准备后的实际 wire JSON、请求 method/path、endpoint binding 的 canonical hash |
| `endpoint_binding` | SHA-256 hex | 规范化 base URL + route 的 digest；不落盘原 URL/密钥 |
| `options` | 私有 JSON，明确 optional output/null、stream=false、thinking/effort 和 phase timeout | 从已解析 profile/request 冻结，retry 不读取改变后的默认值 |
| `asset_manifest` | 私有 JSON | prompt bundle digest、Registry version/digest、Adapter contract version；图片有序 typed ref、媒体类型、byte count、sha256；重建必须匹配 |
| `request_contract_version`, `schema_version` | 支持的正整数 | fingerprint/重建算法版本，不能用升级后的 Adapter 冒充原合同 |
| `generation_only` | bool | 当前 Chat Completions 为 true；未来远端动作默认 false |
| `max_attempts`, `retry_policy_version` | 4、固定版本 | 新绑定冻结该值；重启不能恢复额度 |
| `created_at` | UTC timestamp | 首 claim 时间 |

`options` 严格键集合为 `max_completion_tokens: int|null`、`stream: false`、`thinking_mode: bool|null`、`reasoning_effort: str|null`、`timeout_seconds: finite positive float`；有效值取已准备请求与 profile，省略的输出参数由 null 明确表示。`asset_manifest` 严格键集合为 `prompt_digest`、`registry_version`、`registry_digest`、`adapter_contract_version`、`images`。每个 image 项包含 `source_ref`（现有 typed resource ref 的完整字段）、`observation_kind`（original/annotated/rendered）、`media_type`、`byte_count`、`sha256`；列表保存真实发送顺序，annotation 的重建版本包含在 request contract 中。没有图片时为空数组。绑定本身 schema_version=1，request/retry contract version=1；这些值是版本标识，不是允许数量。

不保存第二份完整 prompt、图片或 SDK prepared token。Prepared token 继续绑定原 client、仅内存使用、拒绝 pickle/serialization。Provider 提供内部 `describe_prepared()` 返回安全 digests/config，不暴露 payload。绑定及 manifest 不写日志或浏览器；credential 永不入绑定，可更新凭据但 endpoint/model/options/资产必须一致。Hash 不能作为发送授权，仍需 Session/资源完整性检查。

`ProviderAttempt` 原有字段保留，增加以下字段（旧行均 null 表示 legacy）：

| 字段 | 约束/来源 |
| --- | --- |
| `attempt_id`, `run_id` | 原有 opaque attempt identity 及 owning Run FK |
| `attempt_sequence` | 原有正整数、Run 内连续唯一；删除 <=8 |
| `base_record_sequence`, `base_tool_sequence` | 原有冻结前缀，分别正整数/非负；与 binding 一致 |
| `status` | 原有四种 attempt 状态，started 只关闭一次 |
| `response_record_id` | 原有 optional 同 Run response FK；仅 response_committed 非空 |
| `failure_code` | 原有 optional 固定枚举；失败使用安全 code，不存 raw message |
| `started_at`, `finished_at` | 原有 UTC；started 时 finished=null，关闭后非空且不再修改 |
| `operation_id` | 指向绑定；同 Run |
| `operation_attempt_number` | 从 1 连续递增，到 binding.max_attempts；已 claim 即占位，即使未证明发送 |
| `retry_of_attempt_id` | 第 1 次 null；后续指向同 operation 的前一次已关闭 attempt |
| `failure_category` | 固定枚举 `temporary_unsent / temporary_rejected / temporary_unknown / permanent / invalid_response / internal_error`；success null |
| `http_status` | optional 合法 HTTP status；不保存原 response body |
| `next_eligible_at` | optional UTC；只在关闭 attempt 并安排下一次时填写，闭合后不可变 |

`attempt_sequence` 仍是整个 Run 的事实序号，无 8 次上限；`operation_attempt_number` 才用于 4 次保护。`NextAction` 添加 `provider_retry`，只用现有 `attempt_id` 指向前一次已关闭 attempt；due time 从此 attempt 取，不在多处复制。checkpoint 新写版本升级，旧版本仍可读。

数据库新表 `run_provider_request_bindings`：唯一 `(run_id, base_record_sequence, base_tool_sequence)`，绑定不可变，受 Session 删除范围约束。attempt 原 prefix 唯一迁到绑定；attempt 增加唯一 `(operation_id, operation_attempt_number)`，并保留 `(run_id, attempt_sequence)` 和 response 唯一。新 SQL/事务守卫每 operation 最多一个 started、最多一个 response_committed，不允许已有响应后再 claim。跨表约束在同一 writer transaction 内检查，关键唯一性/terminal immutability 由 SQL 补强。

不变量：同 operation 所有 attempts 相同 base/Run/provider/model；旧失败/unknown 可位于后续成功之前但不可改写；一个被接受的响应对应一个 attempt，只有它能产生一次 continuation/tool intent batch。原 validator 中“失败只能在终态最后一个”的规则改成按 operation 验证；历史 attempts 不产生第二份 role messages，Memory 只投影实际 response facts。

### 4. 网络分类、退避与终止

Provider 只归类并返回 bounded failure，不 sleep/循环；Runtime 决定下一 action。`ProviderFailure` 保留原字段，新增内部 `category` 与 `retry_after_seconds`（optional 有限非负数），只提取 allowlisted 厂商 error code、状态和 Retry-After，不保存异常 body/header全集。

| 故障 | outcome | 自动重试 |
| --- | --- | --- |
| 本地 prepare/config/schema/continuation/真实厂商能力不合法 | 未 dispatch | 不 claim，安全失败 |
| 可证明未发送的临时 pool/connect 故障 | known failure | 同绑定可重试 |
| read/write/reset/传输 timeout，不能证明远端没生成 | unknown | 仅 generation_only 允许替代尝试 |
| 408/500/502/503/504 | 保守 unknown，除非有确定拒绝证据 | generation_only 临时替代 |
| 429 rate limit | known rejection（证据不足则 unknown） | rate limit 可重试；quota/credit exhausted 永久失败 |
| 400/401/403、未知模型、TLS certificate、无效 URL、确定性 DNS/config 错误 | 已知拒绝或未知，但永久分类 | 不重试 |
| malformed response、无效工具 JSON、`length`/`content_filter` 等 | 保留真实 attempt outcome/可规范化响应 | 不做 response repair、不执行非法 calls |
| 普通程序异常、无法归类的 SDK 异常 | 不假定 transient；发送后不确定则 unknown | 不自动重试，安全失败 |

SDK 的 connection wrapper 必须查看有类型的 cause。不能证明 no-send 时不标 `temporary_unsent`；DNS 只在明确临时解析失败时进入 temporary，未知不猜测。HTTP 429 必须先匹配永久配额错误，不能只凭状态码。

对第 n 次失败（n=1..3），先计算 `base=min(30, 1 * 2^(n-1))`，再 full jitter `[0, base]`；有效 Retry-After 取 `max(jitter, retry_after)`，不截短服务商要求的等待。接受秒数和 HTTP-date；无效/过去值忽略，非有限值拒绝。计算 `next_eligible_at`，与 attempt 终态、checkpoint `provider_retry` 和仅含 revision 的 progress event 在一事务提交。无 busy loop，无 worker 内 sleep；到期仅代表可 claim，不代表新 allowance。

到期后重新获取 execution owner，读 stop，按原前缀、冻结 options/manifest 重建并 prepare，比较 exact fingerprint，再 CAS claim下一 attempt。已改变的默认 output/timeout/thinking 配置不能覆盖绑定值；仍用冻结值建立本次 client。endpoint或资产不匹配安全失败（固定 `provider_retry_request_changed` 内部原因，公共终态用 `execution_failed` 与 allowlisted 安全说明），不改请求继续。

第 4 次失败不会建立 retry action：known/permanent 用 `execution_failed`；unknown 用现有 `provider_outcome_unknown`；不得将不可知尝试伪装已拒绝。API 保持已有 RunStatus/TerminalCode 范围，耗尽原因通过受控 terminal message 表达，非 raw SDK 文本。

网络调用返回后已无本地 active handler，可在其 owner 内提交 retry waiting；调度下一次前仍需前 slice 释放。进程退出的 started attempt 只能在真实跨进程 lock 获得后标 unknown，再按同一 max4合同安排 replacement。timeout、旧 timestamp 或 future.cancel 不证明 owner inactive。遗留无 binding 的 started attempt继续保守 unknown 终止，不臆测重建。

选择 at-most-one **local accepted response**，不承诺远端 exactly-once。未知尝试可能仍在服务商生成并计费，但不包含客户端工具执行；旧响应不能再回写闭合 attempt或触发工具。未来包含远端副作用的 Provider 请求只有 `generation_only=false`，未知后默认不得替代。

### 5. 工具失败由模型决议，未知副作用单独收敛

明确 ToolResult 只写一次，失败也完成该调用的 observation。批次完成后模型可以再发同工具同参数、修正参数、换工具或结束；这是**新 call ID 的新逻辑调用**，不使用旧 operation allowance、不覆盖旧结果。`retryable` 只表达可能可恢复，不承诺相同参数能成功；Schema invalid_arguments 通常需要修正。

不新增 ToolRetryPolicy、不由错误白名单启动 Tool handler、不增加 failed retry waiting 或自动补发 facts。工具 invocation 内部第三方客户端如有隐藏 retries，也必须关闭或明确只属于同一工具声明的不可见内部实现且不重复其副作用；本轮审计受 Figura 控制的 handler，不扩大成第三方库改造。

未知恢复仍使用原 call/Registry/replay effect：replay_safe 新 attempt；idempotent_local_write 保持 `sha256(canonical([run_id, call_id]))`，工具查到已应用结果则返回原结果；reconcile_required 只能可信 adapter 确认，否则 unknown terminal。初始 attempt_number=1，repository 的初始/replay claim 统一检查最多3，不仅 Agent判断；重启、新 executor 或直接 facade 调用均不能绕过。明确 failed result 不进入这条路径。

保守处理“返回 error 但可能已经写入”：纯读取/已证明 effect 结果的异常可落 failed；写入 handler 有已应用结果则返回该结果，有确定无效应证据可返回普通失败，无法判断部分写入则报告窄的 `ToolOutcomeUnknown` 内部信号，保持当前 attempt 无 result，走既有未知恢复/协调。DurableExecutor 对带潜在写入效果的未声明异常也不凭 generic `handler_failed` 假装 no-effect；Tools 的纯函数直接调用接口可保留 generic error，但 durable owner 必须得到 unknown 信号。该信号不含 raw exception、不作为模型 observation、不新增自动失败重试系统。所有现有写入 handler 要验证这一合同。

### 6. 停止、超时和公平调度

Stop 与 claim 仍以 SQLite writer transaction 仲裁：stop先提交不启动新 Provider/tool/replay；claim先提交可派发并提交真实返回，之后 interruption优先。retry wait 的 stop 不等待 due time，scheduler立即协调终止；读路径不负责终止。stop不改执行 revision，已在飞结果仍可 CAS提交。

DurableToolExecutor 给 `ToolContext.cancellation` 注入当前 Run 的持久化 stop callback；读取失败不当成未 stop，要向 owner报告存储错误。同步/native工具仅协作停止；不能因为 timeout/future.cancel 让旧 handler仍写入时开新attempt或允许Session删除。Provider取消只能用 transport真正支持的取消；否则等待 phase timeout/调用返回，不能假定远端取消。

保留每 Provider `FIGURA_<PROVIDER>_TIMEOUT_SECONDS` 默认60、正数且有限，去掉<=600。I/O read timeout是等待一个数据块，不代表总生成时长；不新增Run deadline。optional `FIGURA_<PROVIDER>_MAX_COMPLETION_TOKENS` 为空时 options=None并省略 wire字段，显式值必须正整数，Adapter使用其真实参数语义；retry重用冻结值。后续窗口工作单独规划。

AgentExecutor 新增可选 execution quantum（内部 `max_external_actions`，默认None保持同步内部调用方式；Gateway传1）。一次 Provider dispatch或一次工具handler/recovery计一个外部动作；在提交稳定 checkpoint后让出。内部prepare、终态提交不人为丢失，slice在无activehandler时才释放owner。slice 遇到非到期retry直接返回waiting；默认同步执行的外层 driver 在释放 slice owner 后等待 due time 并重新进入协调，保持原来的执行到终态返回习惯，Gateway 不使用这条等待路径。等待可被stop唤醒，不在持有执行lock时sleep。当前 `src/figura` 没有独立CLI，本轮不新增CLI入口。

Gateway scanner用稳定run排序加轮转cursor，维护去重的ready队列，执行完的长Run进入尾部，不总从最旧Run开始。3 worker、8 queue保持；超过11个Session时也应能获得slice。retry等待不占worker/queue，按UTCdue筛选；accepted stop即刻可调度，忽略due。多Gateway竞争仍靠Runtime lock/CAS，不靠进程内队列证明所有权。单个慢I/O/native调用仍可能占一个worker，公平性保证在动作边界，不能承诺固定毫秒延迟。

public Run持续running；activity沿用queued/executing/recovering/stopping，无需新增公开retry状态或工具重试行。SSE `runId:sequence`、progress仅revision、前端transport façade保持；展示安全网络恢复信息可后续做，本轮不要求新UI协议。

### 7. 兼容入口与所有权

保留 RuntimeStore、Coordinator、ProviderClient 与前端 client façade。新增 binding-aware claim 参数用 keyword-only；受支持的直接 Provider claim 无binding路径继续兼容但标legacy、未知不重试。Agent新路径必须使用binding，不能靠optional默认漏掉持久化。

新 codec 明确版本：RunInput 2、ModelResponseFact 3、FinalAnswerFact 2、ToolCallFact/ToolAttemptStartedFact/ToolResultFact 2、continuation envelope 2（Provider continuation format不变）、checkpoint 2、ProviderOptions 2。所有 writer仅写新版本，reader保留已支持旧版本。版本只更换载荷/动作合同，不改旧值；不能为了通过校验把旧fact重新encode成新fact。

Runtime-only metadata不进入Prompt、Gateway、事件。Prompt仍3个SYSTEM层、完整Sessionclosedhistory+异常尾部上下文、最近完整工具批次图片。重试重建旧绑定，不按新checkpoint重新追加attempt信息或修改history；Memory只取响应和工具真实facts。Provider真实context窗口仍可能拒绝长历史，本轮显式失败，不隐式压缩。

## Risks / Trade-offs

- [未知生成的重复计费] → 最大4次固定在同逻辑请求，保留unknown事实，不fallback，不声称远端去重；只有一个本地结果能触发工具。
- [删除累计配额后的循环任务] → 模型完成、显式stop和真实错误收敛；公平slice避免独占调度，不用隐藏次数/无进展阈值终止正常任务。
- [大载荷编码/复制耗内存] → admission前有界读取/编码、避免多份SDK/raw/canonical常驻；测试默认32MiB附近输入、response和Registry的峰值；不把32MiB当吞吐保证。
- [请求资产/Adapter更新影响重试] → 验证manifest和exactfingerprint，不保存第二份历史，不静默换版本；无法复现时安全失败。
- [新版长期Run仍遇到context窗口] → 原始事实不裁剪，厂商拒绝作为确定错误；压缩与摘要独立下一轮。
- [公平slice增加事务和恢复协调次数] → 每次动作提交后才释放，轮转ready队列和批量due查询；测试14个Session及多个进程竞争。
- [慢native调用无法立即stop] → UI保持stopping，owner及Session删除保护不提前释放；协作工具可检查callback。
- [迁移复杂且新版写入旧进程无法识别] → 停服务备份、事务升级、旧binary拒绝新schema；不执行危险的降级重写。

## Migration Plan

1. 停止所有Gateway/CLI执行owner，备份SQLite及Sources/render私有文件；迁移只处理本地存储，不调用外部服务。
2. schema10原子升级到11：重建受旧bytes/attempt<=8限制的表，保持主键/FK/事实原始JSON；创建binding和storemetadata；增加attempt可空新字段及新索引；重建不可变/删除scope/单terminal/response关联触发器；foreign_key_check与完整state验证后才改user_version。
3. 旧attempt不制造binding或推测options；旧响应仍原样关联。终态Run不重开；running安全model/tool动作可按新无累计配额合同继续；legacy orphan Provider按unknown终止，eligible tool按原版本max3恢复。
4. 部署只读兼容decoder与新版writers/claims，检查配置及payload guard一致；提高限额前更新storeceiling；完整重启后验证绑定重试与既有历史continuation。
5. 运行新存储、旧版本fixture、迁移回滚、Session aggregate删除测试；失败事务保持schema10与全部原数据。升级成功后rollback需停止服务并恢复升级前整份备份，不能让旧进程打开schema11，不能只还原SQLite丢失新版source副作用。
6. 更新当前实现overview与分域文档、配置示例和运维说明；明确仅方案转实现后才可标已支持。随后按OpenSpec流程验收/sync/archive，不在本提案阶段自动进行。
