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

生成图审核返回 `repair_required` 且仍有预算时，系统 SHALL 只允许与该候选关联的 ChartSpec 修正和重新渲染，并在发布前重新审核。测量 observation 的局部重测不再作为共享 review gate 的独占子循环，而是主 Agent 可以主动调用的普通有界工具动作；两类动作都必须保留来源和父对象 lineage。

#### Scenario: Generated candidate repair is controlled

- **WHEN** 当前生成图审核要求修正 ChartSpec
- **THEN** 系统限制后续生成动作到该候选的修正和重新渲染
- **AND** 父失败候选保持不可发布且可追踪

#### Scenario: Measurement re-observation does not freeze unrelated work

- **WHEN** 主 Agent 根据测量 warning 请求局部补充
- **THEN** 系统记录新的 measurement attempt 和父 attempt
- **AND** OCR、布局观察或对其他未依赖候选的判断不因该补充请求被隐式跳过

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

审核 gate SHALL 将失败或需要补充的信息归一化为 `spec_only`、`evidence_needed`、
`source_rebind` 或 `terminal`，并将 repair kind 与 candidate attempt 绑定。未识别或越界
的 repair kind SHALL 按 terminal/blocked 处理，而不是继续执行未知动作。

#### Scenario: Review issue selects evidence repair

- **WHEN** 审核认为现有 scope 内的一个值缺少足够证据，但来源 panel 仍然有效
- **THEN** gate 返回 `evidence_needed`
- **AND** 主 Agent 只被允许在同一 scope 内补证据并重新装配

### Requirement: Evidence repair is an in-gate bounded sub-loop

`evidence_needed` SHALL 开启一个有界的审核修复子循环，允许的顺序为
same-scope evidence -> ChartSpec assembly -> render -> VLM review。子循环 SHALL 继承原
候选上下文、受最大 attempt 次数限制，并在每次失败后保留诊断；不得因为首次审核失败
而直接把 Run 标为成功或无上下文结束。

#### Scenario: Successful evidence repair returns to review

- **WHEN** 同一 panel 的补充测量完成且新 ChartSpec 已渲染
- **THEN** gate 再次执行生成图审核
- **AND** 只有新的审核通过才允许 publication

#### Scenario: Repair budget is exhausted

- **WHEN** evidence repair 达到最大 attempt 次数仍未通过
- **THEN** gate 进入 terminal/failed 状态并返回最后一次结构化诊断
- **AND** 候选保持不可发布

### Requirement: Scope violations fail closed

审核修复中的工具调用、装配或来源解析若超出 generation context 的 attachment/panel
scope，gate SHALL 拒绝该动作并记录 scope violation；不得通过扩大 scope 来绕过审核。

#### Scenario: Cross-panel evidence call is blocked

- **WHEN** repair request 从左侧 panel 改为右侧 panel 或整张 dashboard
- **THEN** gate 返回 scope violation
- **AND** 不执行该工具调用且不推进候选状态
