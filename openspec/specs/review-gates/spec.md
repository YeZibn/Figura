# review-gates Specification

## Purpose

为测量审核和生成图审核提供统一、可追踪且不可绕过的主链路门禁，使不同审核领域可以共享状态、证据、修复和恢复契约，同时保留各自的专业判断逻辑。

## Requirements

### Requirement: Review subjects have a shared bounded lifecycle

系统 SHALL 为每个需要审核的测量尝试或生成图候选创建可追踪的审核记录。审核记录 SHALL 包含 subject 类型和身份、来源引用、attempt/lineage、当前状态、问题、修复动作、重试预算和时间信息，并 SHALL 使用有界、可序列化的字段。

#### Scenario: Measurement and chart subjects share the envelope
- **WHEN** 系统提交一次测量审核或生成图审核
- **THEN** 两者都返回具有审核身份、subject 引用、状态、问题和下一步动作的审核记录
- **AND** 专业检查结果仍保留在各自领域的结构化详情中

#### Scenario: Review evidence remains attributable
- **WHEN** 审核结果写入运行事件、checkpoint 或评测记录
- **THEN** 结果保留 run、attachment/panel 或 candidate/ChartSpec 的安全引用
- **AND** 不暴露本地路径、图像字节、凭证或 provider 原始 payload

### Requirement: Review gates block downstream execution

系统 SHALL 仅对真正需要发布保护的审核阶段建立共享阻塞门禁。生成图审核处于 `reviewing`、`repair_required`、`failed` 或 `exhausted` 时，系统 SHALL 阻止 render 后的 publish 或成功终结；measurement observation 的 warning、`partial` 或 `remeasure_required` SHALL 作为可追踪诊断，不得独占阻塞 OCR、布局观察、其他测量或主 Agent 的候选组装。

#### Scenario: Measurement observation remains non-blocking

- **WHEN** 测量工具返回候选和质量 warning
- **THEN** 运行记录保存 observation、问题和可选下一动作
- **AND** 主 Agent 仍可调用其他证据工具或提交 evidence decision

#### Scenario: Generated chart review blocks publication

- **WHEN** 生成图候选尚未通过生成审核
- **THEN** 系统阻止发布和声称成功的最终结果
- **AND** 候选、ChartSpec 和审核状态仍可被主 Agent 和客户端查看

#### Scenario: Gate cannot be bypassed by final text

- **WHEN** 模型最终文本声称候选已经通过，但生成审核仍处于阻塞状态
- **THEN** 系统保持发布门禁关闭
- **AND** 客户端显示代码拥有的审核状态

### Requirement: Review repair is a controlled sub-loop

生成图审核返回失败且仍有预算时，系统 SHALL 保持原候选不可发布，将结构化问题、来源范围、候选 lineage、剩余预算和可选 repair hint 返回主 Agent。主 Agent SHALL 在授权范围内自主选择观察、测量、来源恢复、ChartSpec 修正和重新渲染；系统 SHALL NOT 按 repair phase 建立工具白名单。任何新候选仍必须经过审核。

#### Scenario: Generated candidate repair is model-directed

- **WHEN** 当前生成图审核失败且仍有预算
- **THEN** 主 Agent收到有界诊断并选择适用的合法动作
- **AND** 父失败候选保持不可发布且可追踪

#### Scenario: Repair remains bounded

- **WHEN** 主 Agent选择补证据、重组装或重新绑定来源
- **THEN** 每个工具继续执行自身授权、scope、引用和结构校验
- **AND** 重试预算与新候选审核仍然适用

### Requirement: Review failures close the gate without implicit bypass

生成图审核失败、超时、证据不可用、非法审核结果或重试耗尽 SHALL 保持生成发布门禁关闭，并返回有界的失败分类和恢复信息。测量 observation 的重测预算耗尽 SHALL 关闭该补充分支，但不应被伪装成生成图审核失败；如果模型选择其他可追溯证据，主链路可以继续。

#### Scenario: Generated review budget is exhausted

- **WHEN** 生成图审核或候选修复达到配置上限
- **THEN** 当前生成候选进入明确的 `exhausted` 非发布状态
- **AND** 运行结果不得声称生成成功

#### Scenario: Measurement repair budget is exhausted

- **WHEN** 某个 measurement session 的局部补充达到上限
- **THEN** 系统记录 `measurement_repair_exhausted` 及最后诊断
- **AND** 不再自动重测，但不把整个 run 错报为 generated chart review failure

#### Scenario: Stale review cannot release publication

- **WHEN** 审核结果引用了错误的 subject、attempt、candidate 或 ChartSpec digest
- **THEN** 系统拒绝应用该结果
- **AND** 任何其他审核对象的门禁或发布状态都不发生变化

### Requirement: Review transitions are durable and idempotent

审核开始、决定、修复和释放事件 SHALL 在允许下一阶段前持久化。重复提交同一 subject 和同一审核意图 SHALL 返回已有结果，不得重复执行审核或发布；恢复运行不得跳过未完成的审核。

#### Scenario: Duplicate review submission is replayed
- **WHEN** 同一运行重复提交相同 subject、attempt 和审核意图
- **THEN** 系统返回原审核记录或其当前状态
- **AND** 不创建重复审核 attempt，不重复发布候选

#### Scenario: Recovery resumes at the gate
- **WHEN** 运行在审核或修复边界中断后恢复
- **THEN** 系统从持久化的审核门禁和下一步动作继续
- **AND** 不把未完成审核当作已通过
### Requirement: Review outcomes expose a bounded repair kind

审核结果 SHALL 可以将失败归一化为 `spec_only`、`evidence_needed`、`source_rebind` 或 `terminal`，并与 candidate attempt 绑定。除 `terminal` 和预算耗尽外，repair kind SHALL 作为主 Agent的诊断提示而不是唯一允许动作；未知分类 SHALL 保持候选不可发布并返回通用结构化问题。

#### Scenario: Review suggests evidence repair

- **WHEN** 审核认为同一来源范围内的值缺少证据
- **THEN** 结果返回 `evidence_needed`、相关 issue 和可选 target
- **AND** 主 Agent可以选择补测、重新观察、修正规格或停止

#### Scenario: Terminal outcome prevents false success

- **WHEN** 审核返回 terminal 或预算耗尽
- **THEN** 系统禁止继续发布该候选
- **AND** Run 返回明确的未发布诊断

### Requirement: Scope violations fail closed

审核修复中的工具调用、装配或来源解析若超出 generation context 的 attachment/panel
scope，gate SHALL 拒绝该动作并记录 scope violation；不得通过扩大 scope 来绕过审核。

#### Scenario: Cross-panel evidence call is blocked

- **WHEN** repair request 从左侧 panel 改为右侧 panel 或整张 dashboard
- **THEN** gate 返回 scope violation
- **AND** 不执行该工具调用且不推进候选状态

### Requirement: A candidate attempt has one canonical review cycle

每个 generated candidate attempt SHALL 对外表现为一个 canonical review cycle，且
只能使用一个 canonical review identity。审核开始、最终审核结果和发布状态必须
由同一审核协调链路产生；内部 deterministic audit、semantic VLM review、状态
快照和修复分类 SHALL 继续可追踪，但不得再发出 `chart_review_started` 或
`chart_review_completed` 兼容事件。默认用户时间线 SHALL 只显示一次审核开始和
一个最终审核结果；失败结果 SHALL 显示原因。

#### Scenario: Internal checks produce one visible review summary

- **WHEN** 候选先通过确定性质量检查，再等待或执行 semantic VLM review
- **THEN** gate 维持同一个 review identity
- **AND** 默认客户端不把内部检查显示为多个 subcheck、英文事件或重复审核步骤

#### Scenario: Canonical review events are the only lifecycle source

- **WHEN** 生成候选进入审核、修复或完成发布
- **THEN** 系统只产生 `review_started`、一个终态 `review_completed` 或
  `review_failed`，以及必要的 publication transition
- **AND** 不会同时产生另一套 `chart_review_*` 生命周期

#### Scenario: Replayed state does not reopen a completed cycle

- **WHEN** 相同 candidate attempt 的 completed review snapshot 被重复提交
- **THEN** gate 返回已有 review state
- **AND** 不重复执行审核、重新打开 publication gate 或创建新的 review identity

### Requirement: Collection children share a review parent

同一次 collection render 产生的多个 generated child candidates SHALL 保留各自 candidate/review 状态，同时共享一个 bounded review parent。父级 SHALL 汇总 child 的 pending、passed、failed 和 publication 状态，不得把 child 数量误算为多次独立 run。

#### Scenario: Three child charts are reviewed as one collection

- **WHEN** 一个 collection 包含三个 child chart candidates
- **THEN** gate 暴露一个 collection review parent 和三个 child outcomes
- **AND** 客户端可以展开 child 细节而不会显示三个重复的顶层生成审核

#### Scenario: One child fails

- **WHEN** collection 中一个 child review failed 而其他 child 已通过
- **THEN** 父级明确显示 partial/blocked 状态和失败 child
- **AND** 不把整个 collection 静默标记为 published
