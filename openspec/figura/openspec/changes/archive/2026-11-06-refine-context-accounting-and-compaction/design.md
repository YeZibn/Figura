## Context

动机见 proposal.md。当前 `AgentRequestBuilder` 无条件重建所有旧用户输入，`ContextEstimate` 对实际 Provider messages/tools 进行整体估算；`AgentExecutor` 在约 80% 时尝试摘要。`context_compaction.py` 已支持当前 Run 的已提交完整交互，不需要退回整轮 Run 不可压缩的策略。

现有 `floor(C/10)` 两个目标未扣除其他输入。`_prompt_resource_projection` 仅在有摘要检查点时筛选，依据 Run、来源引用和部分显式参数；无检查点时返回完整目录。`ContextEstimate` 被严格持久 decoder 使用，直接增字段会破坏旧逻辑请求读取。当前工作区另有重复观察及周期回看实现，新的统计和动态状态组装必须兼容它们。

## Goals / Non-Goals

**Goals:**

- 区分整体压力与历史增长，并识别没有可压缩历史的压力来源。
- 当前用户输入原样保留；当前过程与较早 Run 的合格历史共用连续前缀摘要。
- 旧用户输入随覆盖进入摘要，原文可按 exact source ref 取回。
- 资源使用确定性目录选择、精确引用和按需检索，不建立第二份权威目录。
- 新旧检查点、选择计划和冻结请求均有明确兼容路径。

**Non-Goals:**

- 不做整份 Prompt 的模型改写、语义相关性模型、工具动态搜索或 UI 仪表盘。
- 不增加 Run 次数/token/时间配额，不用近似 token 估算新增普通请求硬拒绝。
- 不删除持久消息、图片或来源，不将当前用户输入截断为摘要。
- 不扩大失败/中断 Run 的摘要资格，保留异常历史 barrier 和未知副作用处理。

## Decisions

### 1. 两个主统计，分项只作为解释依据

新增调用期 `RequestContextAccounting`（建议名称），由 Agent 负责组件归属，Provider 复用既有 tokenizer 和图片估算。必须以实际准备发送的语义/协议内容为依据，包含 adapter 添加的 messages、native tools 及被重放的 continuation；不能只数 Memory messages。

| 建议字段 | 含义与 owner | 生命周期 |
| --- | --- | --- |
| `full_input_tokens` | Provider 实际完整输入估算，复用既有 `ContextEstimate.input_tokens` | prepare 后计算 |
| `history_input_tokens` | 摘要块、未覆盖旧用户输入、保留 assistant/tool 过程及对应定位信息；包含当前 Run 过程，包含实际在历史消息中加载的图片估算 | 调用期重建 |
| `current_input_tokens` | 当前 Run 唯一原生用户输入，包括有序附件身份，排除其他历史 | 调用期重建 |
| `summary_tokens` / `raw_history_tokens` | history 的解释性子项，不能再次加到 history 上 | 调用期重建 |
| `resource_directory_tokens` | 动态资源条目；不含异常 outcome、重复观察和任务回看状态 | 调用期重建 |
| `policy_tools_state_tokens` | 稳定规则、工具说明/native Schema、状态及结构开销的解释项 | 调用期重建 |
| `selected_image_count` / `image_tokens` | 实际进入请求的图片总数/估算，是 full/history 的解释项，不能重复求和 | prepare 时计算 |
| `context_capacity_tokens` / `estimator_version` | 选定模型容量与估算版本 | 跟随本次 prepare |
| `pressure_reason` | `below_trigger`、`history_reducible`、`directory_reducible`、`protected_content`、`no_new_coverage`、`estimate_unavailable` | 内部安全诊断 |

各片段分别编码与整体编码可能不同，不要求逐项和精确等于 full。任何 ratio 都明确分母；缺少容量时 count 可用、ratio 为未知，估算不可用不是零。历史读取的精确大结果计入 raw history，不能因它原本属于资源而在统计中漏计。

分项不进入模型 Prompt，不存第二套持久计数器，不输出原始正文/路径/异常。保留既有 `ContextEstimate` 三字段及其持久格式；分项无需添加 SQL 字段或公开 API。新请求计划只冻结选择所需的计数和版本，不存第二份 Prompt。

替代方案：只数历史会低估窗口压力；直接扩展持久 dataclass 会影响严格旧数据读取，均不采用。

### 2. 当前输入保护与历史输入覆盖

`current Run.input` 每次作为唯一 native user message 保留；其已完成交互可进入摘要，最新等待回看的视觉批次仍整体保留，图片加载方式不变。

此前输入只有在新版本 input-aware 检查点覆盖该输入时才可省略正文。第一次覆盖某 Run 的合格交互时，将其完整输入、附件 ID 和 exact input-message ref 单独供给摘要模型；原文只有一份，近期过程保留 source locator。较早 Run 的 input-only 完整历史也须能形成可覆盖单元，避免空响应或纯输入永久占用。

检查点在先前 Run 中间结束时，该 Run 输入可以已被摘要，后缀使用 source locator；检查点在当前 Run 中间结束时，当前输入仍原样提供。同一输入来自不同 Run 时保持不同来源身份，不按字符串去重。

摘要要求保留有效约束、更正、关键用户数据、附件身份和未接受建议的区别；引用不保证摘要语义完全正确。精确文本任务先 `read_history` 取原文。失败/中断历史沿用现有规则：未覆盖异常 Run 及不能跨越的后续过程留 raw，不伪造成功；已有被覆盖前缀保留，运行终态从 Runtime 刷新。

替代方案：保留所有旧输入无法控制长会话增长；只保留最新用户输入而无来源摘要容易丢约束，均不采用。

### 3. 有限、确定性的预算分配

已配置容量 C 且估算可用时，以 P=`floor(0.8*C)` 为软输入目标，不新增输出/费用配额。两个历史目标的初始偏好 G=`floor(C/10)`。

先计算 B：稳定规则、工具、当前输入、必须保留的异常状态/控制信息，以及强制保留的最新完整交互和本次必要图片。目录必需引用形成 mandatory 集合 M；强制交互不应再从 raw target 重复扣除。具体计数在实现中统一用去重后的组件归属，不用大小相减猜测正文。

令可选空间 A=`max(0, P - estimate(B+M))`，R 为 B 中已保护 raw 交互的估算。可选 raw 配额取 U=`min(max(0,G-R), floor(A/2))`，有效 raw 目标为 R+U；摘要目标 S=`min(G, floor(A/2))`。这样已保护交互只扣除一次，R 超过 G 时仍保留完整交互。S=0 或完整源/输出准备不可行时不发摘要，不要求零长度摘要。

可选目录在两份目标之外的剩余空间中选入；摘要后按实际 summary/raw 大小再次计算可选目录空间。完整重估只有诊断与真实 Provider 保护作用，软目标未达到不按近似估算直接终止普通请求。

流程固定为：构建并统计 → 可选目录收缩 → 仍达到触发线且能增加覆盖时选择一次摘要 → 安装或回退 → 最终目录投影与完整重估 → 普通 prepare。目录变化本身不能反复触发摘要；每次 ordinary prepare 最多创建一个新摘要操作，Provider 物理重试仍走原合同。

新增摘要只覆盖比 checkpoint 更远的完整前缀；同样 base prefix 下已完成/失败的操作不重新发起。复用现有操作身份与状态，记录 `no_new_coverage` 等安全原因；新事实推进后可以重新评估。不要为追求 80% 反复压缩同一摘要。无法压缩的当前输入、大批次或异常历史可能仍超目标，使用既有真实载荷/Provider 失败路径，不截断。

### 4. 资源目录：精确引用、三级选择

先从完整授权目录计算候选，不改变资源 lookup 或 Sources 授权。

1. **mandatory**：当前输入附件、最新保留完整批次的产物/媒体身份、未压缩调用中显式 `resource_ref`/`source_kind+source_id` 及已声明的 `figure_ref`、`measurement_refs` 等类型化引用；带上这些资源直接记录的来源身份。只追踪明确合同，不从任意正文猜 ID，不递归无限展开。
2. **optional**：当前 Run 其他资源、近期 raw 历史相关资源，按层级、Run ordinal 降序、工具事实序号降序和类型化引用排序稳定选入。Panel 不能仅因属于当前 Run 就绕过预算。
3. **discoverable**：其他旧资源，以及仅在摘要中有 exact locator、无需再次展开概要的资源。继续通过 history search / typed reads 获取；摘要 source ref 和类型资源 ref 的语义不同，不能互换。

同一 typed ref 只列一次。完整条目可放入才选，不截断 opaque ID、不改写数值。mandatory 超过软目标也保留；可选目录为零时仍有固定的历史检索使用说明，不列“全部旧资源都不存在”。没有 checkpoint 时也可进行预算筛选；容量/估算缺失则沿用现有引用规则，不发明比例或任意 top-k。

不做像素重读和图像 token 优化，媒体读取仍使用完整目录，不受 Prompt 过滤影响。纯文本里提到的旧资源由搜索兜底，本阶段不承诺语义识别。

### 5. 版本、持久化与恢复

新压缩选择使用 selection plan v2，保留现有 coverage 坐标，冻结 `context_capacity_tokens`、`raw_history_budget_tokens`、`summary_budget_tokens`、`coverage_version`、`input_projection_version`、`directory_projection_version`、`accounting_version` 及用于计算 A 的 content-free basis。v2 的 history target 不再强制等于 C//10，只要求符合本计划确定规则。

input-aware summary contract 采用新版本 3：字段形状沿用现有 v2 分类，语义明确包含原始用户要求；模型不需要看存储版本。Runtime 在提交前严格验证 source refs 授权，旧摘要的输入引用若不完整，原文补充过程由原始记录获取，不根据模型猜测。

已冻结 v1 请求和摘要操作沿用 v1 原文投影、预算、目录和 Prompt 资产身份。禁止为通过 fingerprint 修改旧描述。无法精确重建时按既有安全回退/失败路径，先关闭旧 attempt，不在其未知期间启动替代绑定。

旧 checkpoint 不能直接授权删除旧输入。新请求首次需要 input-aware 策略时，以新 operation 做一次 legacy reconciliation，提供旧摘要及其覆盖范围的原始用户输入和已授权来源；覆盖游标可相同，但 reconciliation 版本标识仅升级一次，不属于反复摘要相同版本。若输入过多使摘要 preflight 失败，则保持旧 checkpoint 和完整旧输入，明确记录原因；本阶段不设计分段 reconciliation。

冻结的普通请求重试必须能重建相同 projection version、checkpoint revision、目录排序和 Prompt digest。若现有 asset manifest 无法表达新策略，扩展其既有 JSON 元数据并版本化校验，保留历史 reader，不向 `ContextEstimate` 直接加字段。并发 stop、CAS、owner 和图片事实合同不改变。

### 6. 与其他活动变更的关系

本变更不依赖周期任务回看上线。已有或后续的重复观察/任务回看状态作为必要动态状态计入 B，不压缩其派生来源、不重置事实计数，不复制进摘要当成用户要求。实施时合并同一 request builder 的改动，保留它们的 frozen request 行为。本次规划不修改那些 change 或主规格。

## Risks / Trade-offs

- [摘要遗漏旧用户要求] → 持久原文不变、结构化字段和来源校验、跨 Run 更正/精确引用验收；不宣称无损压缩。
- [mandatory 内容过大仍无法满足目标] → 软目标可超，保护完整交互，沿用真实 Provider/载荷边界，不引入隐藏裁剪。
- [筛选漏掉语义相关旧资源] → 保留搜索和授权读取；测试“旧 Figure 未列出但能定位并修改”。
- [新旧请求身份变化] → selection/projection 明确版本，旧冻结请求不重绑；双版本重建与安全拒绝测试。
- [估算非精确且组件重复] → 明确重叠子项、图像归属和整体基准，不用组件和伪装真实 usage。
- [跨多处主规格存在旧合同冲突] → delta 同步更新 history/compaction 的旧输入与完整历史条款；不靠新增条款掩盖矛盾。
- [同源压缩浪费与 legacy 升级混淆] → 一次 reconciliation 使用版本状态；普通 v2 覆盖必须推进，失败同 base 不重做。

## Migration Plan

1. 保留既有持久 `ContextEstimate`、Run 事实和旧版本 reader，先加入新计划与策略解码以及回归 fixture。
2. 新逻辑请求采用新投影；旧冻结请求按原版本重建，无法复现显式安全收敛。
3. 首次需要新输入覆盖时进行可恢复 reconciliation，不启动时批量改写数据库，不删除文件。
4. 更新 Prompt 与实现文档并运行定向及全量 Python 验证；测量普通请求、摘要和目录实际估算变化。
5. 回滚不能让旧进程解释未知 v2 operation/v3 checkpoint。保留新增 reader 或停服恢复实施前成套备份；不得原地降级重写已有事实。本轮不执行任何迁移。
