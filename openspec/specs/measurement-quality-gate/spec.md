# measurement-quality-gate Specification

## Purpose

为图表测量建立可追踪、可审计且不可被静默越过的证据生命周期，使初次测量结果在进入结构化图表数据前经过明确的质量判断，并为后续定向重测保留稳定的上下文和 lineage。

## Requirements

### Requirement: Measurement evidence has an explicit lifecycle

系统 SHALL 为每次源图测量提供可追踪的执行状态、质量结果、attempt lineage 和实际下游使用情况。质量结果 SHALL 保留 `provisional`、`partial`、`remeasure_required`、`unsupported` 和 `failed` 等适用诊断；模型无需为每次 attempt 创建 selected/discarded/abandoned 状态。质量 warning 或局部问题不得自动成为主流程门禁。

#### Scenario: Initial measurement remains observable evidence

- **WHEN** 柱状图、折线图、饼图或散点图传感器完成一次测量
- **THEN** 结果包含有界的执行状态、质量信息、证据引用、overlay 和 attempt 身份
- **AND** 结果在主 Agent 选择前保持为候选证据，不被系统自动声明为最终事实

#### Scenario: Warning does not force a workflow retry

- **WHEN** 测量发现基准线、坐标标定、系列关联、覆盖范围或几何支持存在阻断性问题
- **THEN** 结果保留对应 warning 和可选的补充范围建议
- **AND** 系统不得自动重测、阻塞其他观察工具或结束主链路

#### Scenario: Actual evidence use is recorded

- **WHEN** 后续装配引用该 attempt 的部分 refs
- **THEN** 系统记录实际使用的 refs 和 provenance
- **AND** 未使用 refs 保持普通候选状态

### Requirement: Measurement attempts remain attributable

系统 SHALL 按精确的源附件和面板身份维护测量会话，并 SHALL 为每次测量记录稳定的 attempt 身份、父 attempt、工具、测量范围、质量结果、证据引用和主 Agent 的选择结果。重复调用、恢复或重连不得使一个测量结果归属于其他附件或面板。

#### Scenario: Attempts form a recoverable lineage

- **WHEN** 同一 panel 发生初次测量、主 Agent 判断或后续定向重测
- **THEN** 每次结果可以通过 session、attempt 和父 attempt 关联到同一 `attachment_id + panel_id`
- **AND** 下游可以识别当前采用的 attempt、被舍弃的 attempt 和仍待判断的 attempt

#### Scenario: Persisted context does not cross panel boundaries

- **WHEN** Agent 从 checkpoint 或历史状态恢复测量上下文
- **THEN** 只恢复与当前附件和面板匹配的测量会话
- **AND** 不得把其他 panel 的 accepted、provisional 或证据引用用于当前 ChartSpec

### Requirement: Quality audit returns structured measurement issues

每次测量 SHALL 经过适用的质量审计，并 SHALL 以结构化方式报告范围、几何、标定、覆盖、关联和可视证据完整性。审计 SHALL 只描述观测质量和可执行约束，不得替主 Agent 决定采用哪个候选，也不得因发现 issue 自动发起重测。

#### Scenario: Material geometry uncertainty is blocking

- **WHEN** 柱状图基准线残差过大、折线坐标标定不足、饼图扇区总和不一致或散点存在无法解析的关键重叠
- **THEN** 审计结果包含对应 issue code、location、severity 和 bounded message
- **AND** 结果不能被标记为无条件 accepted

#### Scenario: Partial evidence remains inspectable

- **WHEN** 测量只能确认部分柱体、轨迹、扇区或散点
- **THEN** 系统保留已确认的结构化像素证据、引用标签和 overlay
- **AND** 未确认部分保持 null、partial 或 unresolved，不得被补成确定数值

#### Scenario: Quality issue remains an advisory observation

- **WHEN** 审计生成 `repair_action` 或局部目标建议
- **THEN** 该内容作为主 Agent 的动态证据上下文返回
- **AND** 系统不得仅凭该字段自动创建下一次 measurement attempt

### Requirement: Measurement quality state is bounded and serializable

测量执行状态、质量检查、问题、观察范围、证据决策和 attempt lineage SHALL 使用有界、可序列化的结果表达，并 SHALL 能够在 Agent observation、run artifact index、checkpoint 和恢复流程之间保持一致。结果不得暴露本地路径、图像字节或 provider 原始 payload。

#### Scenario: Observation and recovery preserve the same quality state

- **WHEN** 测量结果通过工具观察返回后被写入运行记录并在后续恢复
- **THEN** 恢复后的执行状态、质量问题、证据选择和来源身份与原结果一致
- **AND** 恢复不会凭空新增 selected evidence 或改变模型尚未作出的决策

### Requirement: Measurement issues expose machine-readable repair targets

当测量质量审计发现需要补充证据的问题时，系统 SHALL 返回有界的 `observation_scope` 或 `measurement_target`。首次观察可以使用 `observation_scope` 表达当前 panel 内的 plot、legend、axis 等 include/exclude 范围；已有 attempt 的局部补充 SHALL 使用 `measurement_target` 表达候选引用或区域、受影响字段、模式和原因。两类范围都必须保持 attachment、panel 和源坐标边界，且不得由代码自动执行。

#### Scenario: Initial scope identifies a bounded plot

- **WHEN** 主 Agent 在第一次调用测量工具前能够从源图判断绘图区和图例位置
- **THEN** 主 Agent 可以提交相对于当前 panel 的归一化 include/exclude 范围
- **AND** 工具返回实际应用的源坐标、局部坐标和 overlay

#### Scenario: Repair target identifies a bounded candidate set

- **WHEN** 已有测量结果中的候选需要补充或排除
- **THEN** 主 Agent 可以提交同一 panel 的 refs、区域、受影响字段和原因
- **AND** 系统校验 target 归属，但不把 target 建议自动转换成工具调用

#### Scenario: Scope cannot cross panel boundaries

- **WHEN** 主 Agent 提交的 scope 或 target 不属于当前 measurement session 的 attachment 或 panel
- **THEN** 系统拒绝该范围并返回结构化来源不匹配问题
- **AND** 不创建新的 observation 或 repair attempt

### Requirement: Remeasurement attempts are bounded and re-audited

每次定向重测 SHALL 由主 Agent 在主链路中显式调用原图表测量工具发起，并 SHALL 在同一 run、attachment 和 panel 的 measurement session 中创建新的 attempt，记录父 attempt、target、证据引用和原因。重测结果 SHALL 重新经过质量审计；重复的等价请求 SHALL 幂等；超过预算时 SHALL 保留明确的耗尽状态。代码不得在质量审计或恢复过程中自动重复调用测量工具。

#### Scenario: A corrected local attempt supplies better candidates

- **WHEN** 当前 panel 的定向重测解决了父 attempt 的局部问题
- **THEN** 新 attempt 被记录为当前 observation，并可由主 Agent 选择其中的候选
- **AND** 旧 attempt 保持可追踪但不会自动覆盖新结果

#### Scenario: Repair budget is exhausted

- **WHEN** 同一 panel 的重测次数达到配置上限，或同一 target 被重复拒绝
- **THEN** session 返回明确的耗尽状态、问题、attempt lineage 和下一动作
- **AND** 系统不再自动创建 attempt，也不把未选择的候选交给组装器

#### Scenario: A failed target does not fall back to full-panel measurement

- **WHEN** 定向区域内没有足够证据或 mask 无法应用
- **THEN** 工具返回有界的 `focus_empty`、`focus_insufficient` 或等价局部结果
- **AND** 工具不得静默扩大到整个 panel 或源图再次搜索

### Requirement: Measurement review is a hard gate for the main chain

测量结果 SHALL 经过质量审计，但 measurement review SHALL NOT 成为独占主链路或组装前决策门禁。`assemble_spec` SHALL 只校验实际引用证据的 attachment、panel、attempt、范围和必要结构；warning、未解析标签、未引用候选或缺少独立 decision 状态不得阻塞其他观察和合法组装。

#### Scenario: Measurement observation does not block unrelated work

- **WHEN** 测量返回 warning、`partial` 或 `remeasure_required`
- **THEN** 主 Agent仍可调用 OCR、布局、其他测量或直接视觉装配
- **AND** 系统不创建独占 measurement review gate

#### Scenario: Assembly validates only referenced evidence

- **WHEN** 主 Agent提交 measurement refs 和 ChartSpec
- **THEN** 系统校验这些 refs 属于当前来源和 attempt
- **AND** 未引用误检不影响合法 refs

#### Scenario: Invalid referenced evidence is rejected safely

- **WHEN** 主 Agent引用不存在、越界、来源不匹配或缺少必要数值的 ref
- **THEN** `assemble_spec` 返回定位错误
- **AND** 系统不渲染或发布依赖该 ref 的结果

### Requirement: Measurement evidence exposes compact stable references

图表测量结果 SHALL 为可见候选提供有界且稳定的模型引用，例如柱体 `B1`、系列 `S1` 或饼图片区段引用。引用 SHALL 同时出现在结构化结果和对应 overlay 中，并 SHALL 与内部几何和 attempt lineage 关联。引用仅用于证据交叉引用，不得被当作最终用户可见的系列名称或语义角色。

#### Scenario: Overlay and result share the same reference

- **WHEN** 测量工具返回柱体、系列、轨迹、散点或扇区候选
- **THEN** overlay 使用与结构化结果一致的 bounded reference
- **AND** 主 Agent 可以只使用该 reference 请求选择或局部重测，而不必重复提交完整几何数据

#### Scenario: Internal reference is not rendered as a business label

- **WHEN** 主 Agent 使用测量引用组装 ChartSpec
- **THEN** 系统将引用与真实系列名称或未解析状态分开保存
- **AND** `series_1`、`B1` 等内部引用不得直接出现在最终用户图例中
### Requirement: Measurement evidence is bound to generation scope

当测量为某个 generation candidate 提供证据时，measurement attempt SHALL 记录
candidate/attempt、attachment、panel、effective scope 和目标角色。工具返回的 evidence
reference SHALL 能够被装配和审核定位到同一来源范围。

#### Scenario: Same-panel evidence is accepted

- **WHEN** evidence-needed repair 请求左侧 panel 内的局部补测
- **THEN** 新 attempt 继承 candidate 的 attachment/panel scope
- **AND** accepted evidence 可以被 assemble_spec 引用

#### Scenario: Cross-panel measurement is not accepted as repair evidence

- **WHEN** measurement attempt 来自 candidate 未声明的 panel
- **THEN** 质量门禁返回 scope mismatch
- **AND** 该 evidence 不得作为 candidate 的 accepted measurement provenance

### Requirement: Observation scope and measurement target have distinct meanings

首次观察 SHALL 使用可选 `observation_scope` 描述当前调用要查看的区域和角色；已有
attempt 的补充测量 SHALL 使用 `measurement_target` 指向候选证据、局部区域或待确认引用。
系统 SHALL 在结果中返回实际应用的 effective scope，不得把两者混成自动重测指令。

#### Scenario: Initial scoped observation is not a remeasure

- **WHEN** 第一次测量调用带有 panel 内的 observation_scope
- **THEN** 系统创建新的 observation attempt
- **AND** 结果说明实际应用范围与发现的候选
- **AND** 不自动创建第二次测量

#### Scenario: Targeted repair starts only by Agent decision

- **WHEN** 主 Agent 根据 review 的 evidence_needed 决定补测一个候选引用
- **THEN** 调用使用 measurement_target 并关联父 attempt
- **AND** 只有该显式调用会产生新的测量 attempt

### Requirement: Evidence quality does not autonomously select semantic roles

测量质量审计 SHALL 报告几何、数值、warning、候选引用和可用角色线索，但不得自动把 OCR/CV 候选升级为业务语义，也不得替主 Agent选择系列。主 Agent通过最终工具输入、ChartSpec 语义和实际引用表达选择，系统不要求额外的 decision 对象。

#### Scenario: Legend swatch is discarded explicitly

- **WHEN** 测量结果包含可能是 legend swatch 的候选
- **THEN** 结果提供位置和角色线索
- **AND** 主 Agent可以不引用该候选，无需单独提交 discarded 状态

### Requirement: Focused measurement closes its observation obligation

局部测量 SHALL 区分 focus request、effective scope 和 measurement observation。`focus_applied` 只有在绑定明确 attempt 时才有效；无有效 observation 时 SHALL 记录 pending 或 failed 事实，但不得要求模型关闭独立 decision unit，也不得单独阻止模型选择其他合法修复路线。

#### Scenario: Applied focus is followed by same-scope observation

- **WHEN** 主 Agent 请求同一 panel 内的局部测量且工具成功应用该范围
- **THEN** measurement attempt 记录 effective scope 并返回对应 observation
- **AND** 后续证据选择可以引用该 attempt 的 refs

#### Scenario: Applied focus has no observation

- **WHEN** 局部范围已应用但没有有效 observation
- **THEN** 系统记录 pending 或 failed 状态和诊断
- **AND** 主 Agent可以选择其他授权工具、调整范围或停止

### Requirement: Bound generation evidence to an effective source scope

测量 evidence SHALL 绑定经过授权和解析的 effective attachment/panel scope。若 scope 由工具根据唯一上下文补全，结果 SHALL 明确记录 requested scope、effective scope 和绑定依据；若 scope 不可解析，系统不得产生可被 assemble 接受的 evidence ref。

#### Scenario: Bound scope produces attributable evidence

- **WHEN** 测量调用在唯一授权 panel 内完成并返回候选
- **THEN** attempt 和 evidence refs 记录该 panel、effective scope 和质量状态
- **AND** assemble 可以定位到同一来源范围而不依赖模型猜测内部身份

#### Scenario: Scope error produces no accepted evidence

- **WHEN** 测量调用的 source scope 缺失、歧义或跨 panel
- **THEN** 质量状态为 scope error 或等价的非证据状态
- **AND** 该调用不得产生 accepted evidence 或推动 candidate 进入 assemble

### Requirement: Scope repair remains a local, attributable action

source scope 修复 SHALL 保持在当前 attachment/panel 和对应 measurement attempt 的边界内。修复错误、重新绑定或放弃 SHALL 记录在同一证据 lineage 下，并 SHALL 不自动扩大搜索范围或自动选择语义角色。

#### Scenario: Rebinding does not widen measurement

- **WHEN** Agent 根据工具 action hint 重新提交同一 panel 的 source context
- **THEN** 新 attempt 明确关联父 attempt 并只读取有效同范围
- **AND** 工具不因为第一次 scope 错误而回退到全图测量
