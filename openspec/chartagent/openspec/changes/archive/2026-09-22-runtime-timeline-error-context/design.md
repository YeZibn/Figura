## Context

当前 execution event history 是普通运行和评测运行共同的事实来源。决策事件已经有 `unit_id` 等关联字段，但 `run_started`、model lifecycle、operation lifecycle 和 terminal/error 事件仍可能只有 run sequence、turn 或 operation identity；前端当前把缺少 `unit_id` 的每个事件按 sequence 生成独立 legacy unit。与此同时，模型调用异常在 turn 边界被统一当作 uncertain，图表工具则在模型 schema 与 `GenerationContext.validate()` 之间存在条件约束不一致。具体动机见 `proposal.md`，行为约束见本 change 下的 delta specs。

## Goals / Non-Goals

**Goals:**

- 建立一个可从现有 event history 重建的四层展示语义：run envelope、process/turn/operation context、decision unit、bounded legacy fallback。
- 让普通运行、重连历史和评测视图使用同一 projection，并保留原始事件、顺序、工具详情和错误引用。
- 在 provider/模型调用边界区分确定性拒绝与远端结果未知，避免用 recovery-blocked 覆盖真实失败原因。
- 让 source-linked generation context 在唯一授权 panel 可验证时安全绑定 effective scope，在歧义时返回明确错误。

**Non-Goals:**

- 不新增独立 timeline 数据库或以投影文件替代 execution event history。
- 不让 OCR、CV、工具或 scope resolver 自动决定系列语义、删改候选或生成 ChartSpec。
- 不把所有 lifecycle event 强行提升为 decision unit，也不改变已有 review gate、publication 或 retry 的业务语义。
- 不在本 change 中接入新模型、改 provider 选择策略或引入自动重试。

## Decisions

### 1. 保留事件事实来源，增加兼容性过程关联

事件仍由现有 run history 持久化；新增的关联和错误字段是有界 envelope，而不是第二套 timeline 状态。关联优先级固定为：

1. 显式 `unit_id`/`parent_unit_id`，用于 measurement、generation、review 和 publication；
2. 可验证的 `process_id`、`turn`、`operation_id`，用于 model/tool lifecycle；
3. run 级 terminal 或无法关联的事件进入有限的 lifecycle/legacy bucket。

兼容 bucket 的 key 必须与 run、事件阶段/过程类别绑定，不得使用单独的 event sequence 作为 key。bucket 内仍按 sequence 展开，因此聚合不会损失原始诊断。若关联证据不足，宁可保留为 legacy，也不根据事件先后猜测 candidate 或 review 父子关系。

选择这一方案是因为它能兼容旧事件，同时修复“每个普通事件一张卡片”的噪声。单纯在前端按相邻事件合并会把不同 operation 混在一起；把每个 lifecycle event 都补成 decision unit 又会污染领域语义。

### 2. 统一错误 envelope，并在调用边界完成分类

模型/provider 调用和工具调用的失败事件使用同一组有界字段：`failure_category`、稳定 `error_code`、可选 `provider_status`、脱敏 `safe_message`、`retryable`、`outcome_known` 和 `first_failure_ref`。provider adapter 负责把明确的 4xx/余额/授权/参数/限流拒绝标记为 known deterministic failure；只有 timeout、连接断开或没有确认远端是否接受时才标记 `outcome_known=false`。

run terminalizer、recovery 记录和前端摘要都消费这个 envelope。这样可以保持一个 terminal outcome，同时让 `recovery_blocked` 只表示恢复安全性未知。错误正文仍受长度和敏感信息限制，完整原始响应不直接进入日志或界面摘要。

备选方案是让前端从异常字符串或 HTTP 文本自行推断错误类型；这会导致普通运行、评测和不同 provider 得到不一致结果，也无法可靠决定是否允许恢复，因此不采用。

### 3. 前端只做确定性投影，不推断业务关系

将 `projectDecisionTimeline` 的兼容路径拆成可测试的 projection 层：

- 有 `unit_id` 的事件按现有 decision-unit 逻辑处理；
- 有 process/turn/operation identity 的生命周期事件归入同一过程容器或对应的工具 step；
- 只有完全没有安全关联的事件才进入 run-scoped legacy bucket；
- terminal summary 和 failure detail 作为 run/process 详情展示，不创建额外的 review/generation unit；
- 相同 run/sequence 仍先去重，相同 transition 仍按现有规则去重。

前端标签改为“运行过程”“模型调用”“工具操作”或“历史事件（兼容模式）”等稳定中文。原有 `legacy:...:kind:sequence` 只保留为单条事件的内部 fallback identity，不再作为顶层聚合 key。

### 4. source scope 由显式上下文优先、唯一授权上下文兜底

source-linked 请求仍优先接受模型明确提交的 `generation_context.source_scope`，并校验 attachment、panel 和 revision。对于工具已经解析出一个唯一、已授权的 attachment/panel，且模型 context 仅缺少可安全补全的 scope 字段时，context normalizer 使用运行时 scope hint 绑定 effective scope，并在工具结果、attempt 和 trace 中回显绑定结果。

当存在多个 panel、attachment 不一致、handoff 过期或 scope 无法唯一解析时，禁止兜底绑定，返回 `generation_context.source_scope` 的字段级结构化错误。source-free `synthesize` 仍必须使用 `not_applicable` coverage，不能借 scope 兜底掩盖模式错误。

选择“唯一上下文安全绑定 + 歧义拒绝”是为了修复 test5 中模型已有 `attachment_id`/`panel_id` 但遗漏 `source_scope` 的运行时失败，同时保留跨 panel 防护。完全强制模型每次重复内部 scope 会继续放大 prompt 遗漏；无条件自动补全则会产生跨 panel 证据污染。

### 5. 普通运行与评测共享同一个回放入口

后端只保存兼容字段和结构化错误；普通运行与评测工作台都把同一份 event history 交给相同的 projection 输入。评测可以在外层添加 case/report 信息，但不复制 projection 算法。回放夹具同时覆盖新字段和旧事件，确保旧记录仍能进入 bounded legacy bucket。

## Risks / Trade-offs

- [Risk] 旧事件缺少过程字段，兼容 bucket 可能仍然无法表达精确父子关系 → [Mitigation] 使用明确的兼容标签、保留完整 sequence/detail，并禁止从 legacy bucket 推导业务成功或 lineage。
- [Risk] provider 错误正文包含密钥、请求头或过长响应 → [Mitigation] 只保存稳定分类、状态和脱敏 bounded message；原始响应继续走现有安全诊断限制。
- [Risk] 唯一 scope 绑定可能掩盖模型没有完整提交 context 的问题 → [Mitigation] 只允许在 attachment/panel/revision 唯一且已授权时绑定，并在结果中显示 requested/effective/binding basis；歧义直接拒绝。
- [Risk] 新旧事件混合时实时投影与历史重放产生不同分组 → [Mitigation] projection 只依赖事件字段、run sequence 和固定优先级，增加实时追加、刷新、重连和评测等价性测试。
- [Risk] 错误分类改变现有恢复行为 → [Mitigation] 先以 additive failure envelope 落盘，针对确定性拒绝和 uncertain outcome 分别做回放测试，再启用 terminalizer 的分类分支；父 run 的 terminal outcome 保持幂等。

## Migration Plan

1. 先实现并测试错误 envelope、source scope 规范化和后端 lifecycle 关联字段；旧事件字段保持可读。
2. 更新前端 projection 和错误摘要，再让评测工作台复用同一入口；以 test4/test5 回放夹具验证新旧事件混合场景。
3. 更新工具 schema、提示说明和结构化错误展示，确认唯一 scope 绑定与歧义拒绝均能在 trace 中定位。
4. 通过实时追加、刷新、重连、显式 retry 和 provider rejection 回归后启用新投影。若发现兼容回放问题，可回退到旧 projector；事件新增字段仍可被旧客户端忽略。

## Open Questions

无。过程 bucket 的命名和错误分类属于实现细节，但其边界已由规格固定，不应在实现阶段改变行为契约。
