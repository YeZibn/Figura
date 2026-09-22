## Context

现有链路同时维护三套相近状态：模型在 `measurement_decision` 中声明选择，measurement session 保存 decision，`assemble_spec` 再通过 measurement gate 验证；生成审核失败后，review gate 又把 `repair_kind` 转换为唯一 `repair_phase` 和工具白名单。四层提示词将这些代码状态描述为高优先级行动合同，前端时间线随后把 measurement decision、focus、review subcheck 等内部状态投影成用户步骤。

这些设计保证了来源可追踪和失败候选不可发布，但也把业务判断、运行安全和展示状态耦合在一起。参见 proposal.md；delta specs 将新的行为边界定义为“模型选择、工具验证、发布门禁”。

## Goals / Non-Goals

**Goals:**

- 把模型的证据与修复选择从代码状态机中释放出来，同时保留来源、范围、引用、结构和发布安全。
- 让 measurement provenance 由装配请求实际使用的 refs 派生，而不是依赖独立 decision envelope。
- 让生成审核输出问题和建议，主 Agent选择修复路线；每个新候选仍强制审核。
- 保留内部 trace、幂等、预算和恢复能力，并让普通运行与评测使用同一简洁时间线投影。
- 平滑读取旧 checkpoint、历史事件和携带 `measurement_decision` 的旧调用。

**Non-Goals:**

- 不取消测量质量审计、ChartSpec 校验、来源授权或生成图 VLM 审核。
- 不改变四种图表传感器的 CV/OCR 算法和输出精度。
- 不允许模型覆盖 publication status、伪造 evidence refs 或越过 attachment/panel 授权边界。
- 不重新设计 review VLM 的 JSON schema；只调整 `repair_kind` 在主链路中的控制语义。
- 不删除原始执行事件或评测所需的内部诊断。

## Decisions

### 1. 将约束划分为硬边界和模型建议

硬边界只包括：附件授权、panel/source lineage、server-issued ref 真实性、ChartSpec 结构、candidate/review identity、重试预算、幂等/恢复安全以及失败候选不可发布。普通测量 warning、evidence selection、`repair_kind` 和 `repair_phase` 不再决定模型可以调用哪些工具。

选择该方案是因为硬边界可以由代码确定地判断，而“下一步应该重测还是改规格”依赖图片语义，交给多模态主 Agent更合适。备选方案是保留当前 phase 白名单并扩大每个 phase 的工具集合，但它仍会制造错误分类后的死路，也继续要求维护多套状态。

### 2. 使用实际引用取代独立 measurement decision

`assemble_spec` 的新路径从调用中读取服务端签发的 `measurement_ref` 和同级紧凑数组 `evidence_refs`。figure child 使用相同字段名，避免单图和集合形成两套协议：

1. 不含 measurement provenance 时，执行直接视觉/其他证据路径。
2. 含 `measurement_ref + evidence_refs` 时，逐项验证 session、attachment、panel、attempt、scope 和必要字段；不得接受只有 refs 而缺少来源引用的请求。
3. 验证通过后，在 assembled ChartSpec 的内部 provenance 中记录本次实际使用 refs、attempt 和适用 warning。
4. 同一 observation 中未引用的候选保持普通历史证据，不写 discarded 状态。

旧 `measurement_decision` 字段暂时保留在输入 schema 中作为兼容字段。若旧调用提供 `selected_refs`，适配器将其转换为 `evidence_refs`；discarded/abandoned 只写兼容 trace，不影响新 gate。新工具说明不再要求模型生成该字段。若新旧字段同时存在且内容冲突，返回结构化参数冲突错误，不猜测优先级。待历史 checkpoint 兼容窗口结束后，可在后续 change 中正式移除 schema 字段。

备选方案是自动替模型选择所有高 confidence refs；该方案会把几何 confidence 错当成业务语义，因此不采用。

### 3. review gate 只拥有候选发布，不拥有修复工具顺序

review coordinator 继续维护 candidate/review/publication 生命周期：

- 候选创建后进入 review pending；
- 审核 pass 才能发布；
- fail、timeout、invalid 或 exhausted 始终不可发布；
- 修复产生新 candidate，并保留父 candidate lineage；
- final text 不能释放 publication gate。

主循环不再根据 `repair_phase` 拒绝测量、OCR、布局、assemble 或来源恢复调用。每个工具仍通过自身 authorization/scope validator 拒绝越权输入。`repair_kind`、issues、target 和 `repair_hint` 注入主 Agent上下文，用于推理而非调度。

`terminal` 和预算耗尽仍停止自动修复，因为此时继续调用会违反有界运行约束。若任务目标或 source scope 发生变化，必须创建新的 generation context/candidate，而不是改写失败候选。

### 4. 动态 prompt 从行动合同改为事实摘要

保留现有四层 Markdown 装配，不增加第五层。动态运行层改为提供：

- 当前 attachment/panel/source scope；
- 可用 measurement attempts 和 bounded refs；
- 最近 issues、warnings、candidate/review/publication 状态；
- retry budget、恢复和中断事实；
- 可选 `repair_hint`。

删除普通业务决策中的 `allowed_actions`、`blocked_actions`、`required next action` 话术，以及“必须先提交 measurement_decision”的规则。安全边界仍以明确规则表达，例如不能伪造 ref、不能跨越授权来源、不能发布失败候选。

工具 description 同步说明：measurement 输出是候选证据；模型可以只引用需要的 refs；未引用候选无需显式舍弃；局部补测是模型按需选择。

### 5. 内部 trace 与用户时间线采用不同投影

原始 execution events、旧 decision events、focus、repair classification 和 subcheck 继续持久化，供 checkpoint、诊断和评测读取。用户时间线投影只产生：

- 模型实际调用的工具及主要结果；
- ChartSpec 组装和候选生成；
- 每个 candidate 的一次审核开始与最终结果；
- 审核失败原因和终态错误。

不再产生可见的 measurement decision/pending 卡片，也不把 deterministic audit 与 semantic VLM review 展示成多个英文 subcheck。普通运行和评测继续复用同一 projector；评测详情可以在诊断模式读取原始 trace，而不是污染默认 UI。

### 6. 恢复和幂等基于已提交操作，而非待关闭 decision

checkpoint 保存已完成工具结果、measurement attempts、assembled specs、candidates、review/publication 状态和实际 refs。恢复时：

- 已完成工具调用不重放；
- 不因为历史 observation 缺少 decision 而停在 pending；
- 未完成或结果不确定的外部操作继续按现有安全规则阻塞自动重放；
- 已失败且未发布 candidate 仍保持失败，模型可以在新 turn 选择修复路线。

这样保留恢复安全，同时移除“恢复后必须先关闭 measurement decision unit”的人工阶段。

## Risks / Trade-offs

- [模型可能选择质量较差但合法的证据] → 保留 measurement warnings、ChartSpec 校验和最终 VLM review；审核失败候选不可发布。
- [放宽工具顺序后模型可能循环尝试] → 保留 run/tool/review retry budget、重复 target 幂等拒绝和 maximum steps。
- [旧 checkpoint 依赖 decision status] → 提供兼容读取和实际 refs 派生逻辑；迁移测试覆盖旧事件与新事件混合恢复。
- [repair kind 不再硬调度可能增加一次无效工具调用] → 在 prompt 中保留简洁 repair hint 和 scope 信息，但不升级为白名单。
- [隐藏 decision/subcheck 后诊断信息不够] → 默认 UI 简化，原始 trace 与评测诊断接口继续保留完整信息。
- [新旧字段并存期间语义混淆] → 对外工具说明只推荐新路径；兼容字段标记 deprecated，测试确保它不能重新建立硬门禁。

## Migration Plan

1. 先增加兼容型 evidence-use 解析和 provenance 派生测试，保持旧调用可运行。
2. 将 measurement gate 拆成来源/引用校验与旧 decision 适配，默认不再要求 decision。
3. 调整 prompt 和工具 schema/description，使新模型调用只表达实际 refs。
4. 放宽 review tool-call gate，仅保留 publication、terminal、预算和工具自身安全校验。
5. 更新 checkpoint/event projection，使历史 decision 可读但不产生待处理义务。
6. 更新共享前端时间线投影和审核卡片，隐藏 decision/subcheck 控制事件。
7. 运行窄测试、全量 Python 测试、frontend build/smoke，并用现有真实评测样本验证审核失败后的自主修复。

回滚时可以恢复 prompt 的旧字段要求和 review phase filtering；兼容期内旧 decision 数据仍在，因此不需要破坏历史存储。不得通过回滚跳过 publication gate。
