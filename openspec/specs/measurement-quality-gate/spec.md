# measurement-quality-gate Specification

## Purpose

为图表测量建立可追踪、可审计且不可被静默越过的证据生命周期，使初次测量结果在进入结构化图表数据前经过明确的质量判断，并为后续定向重测保留稳定的上下文和 lineage。

## Requirements

### Requirement: Measurement evidence has an explicit lifecycle

每次源图测量 SHALL 返回候选证据事实，包括稳定的 `measurement_ref`、`evidence_refs`、attachment/panel 与 effective scope、质量元数据、系列元数据和适用的 overlay。质量状态用于描述可观测结果，不表达模型是否采用；工具和运行时 SHALL NOT 为候选维护 selected、discarded 或 decision 状态。

#### Scenario: Initial measurement remains candidate evidence

- **WHEN** 柱状图、折线图、饼图或散点图测量完成
- **THEN** 结果返回有界的 measurement/evidence refs、scope、质量和系列信息
- **AND** 系统不将候选自动声明为 ChartSpec 数据或要求模型提交独立决策

#### Scenario: Quality warning does not decide evidence use

- **WHEN** 测量发现基准线、坐标标定、系列关联、覆盖范围或几何支持存在问题
- **THEN** 结果保留相应质量诊断与可选的局部范围线索
- **AND** 系统不自动选值、重测、阻塞其他工具或终止主链路

#### Scenario: Actual evidence use is derived from assembly

- **WHEN** 后续 `assemble_spec` 引用某个 measurement 的部分 evidence refs
- **THEN** 系统从该请求记录实际使用的 refs 和 provenance
- **AND** 未引用候选不生成独立的舍弃状态

### Requirement: Measurement attempts remain attributable

系统 SHALL 按精确的源附件和面板身份维护 measurement session，并为当前 attempt 保存稳定身份、可选父 attempt、工具、scope、质量元数据、measurement/evidence refs 和系列元数据。session SHALL 只暴露当前 attempt 的候选结果；过去的工具调用如需审计由普通 execution history 记录，不得形成第二套采用、舍弃或待判断状态。恢复不得将结果归属于其他附件或面板。

#### Scenario: Session exposes the current measurement attempt

- **WHEN** 同一 panel 发生初次测量或显式的局部重测
- **THEN** 当前 session 指向最新工具调用产生的 attempt 及其结果事实
- **AND** 结果可通过 session、attempt 和父 attempt（如适用）关联到同一 `attachment_id + panel_id`
- **AND** session 不保存 adopted、discarded 或 pending-decision attempt 集合

#### Scenario: Persisted context does not cross panel boundaries

- **WHEN** Agent 从 checkpoint 恢复 measurement session
- **THEN** 只恢复与当前附件和面板匹配的 session/current attempt
- **AND** 不得将其他 panel 的 measurement/evidence refs 绑定到当前 ChartSpec

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

当前 attempt 的 scope、质量检查、问题、measurement/evidence refs、系列元数据和来源身份 SHALL 使用有界、可序列化的结果表达，并 SHALL 能够在工具 observation、run artifact index、checkpoint 和恢复流程之间保持一致。该状态不得包含 evidence selection/discard decisions，也不得暴露本地路径、图像字节或 provider 原始 payload。

#### Scenario: Observation and recovery preserve the same attempt facts

- **WHEN** 测量结果写入运行记录并在后续恢复
- **THEN** 恢复后的当前 attempt、refs、scope、质量问题和来源身份与原结果一致
- **AND** 恢复不会新增、推断或恢复选取/舍弃状态

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

每次局部重测 SHALL 由主 Agent 在主链路中显式调用已有图表测量工具发起，并 SHALL 在相同 run、attachment 和 panel 范围内产生新的 attempt。请求可以引用已有 `measurement_ref`、`evidence_refs` 或局部 scope；结果 SHALL 返回新的 refs、实际 scope、质量和系列元数据。调用次数仅受现有 Agent/run 和工具安全预算约束，不建立 measurement-specific repair budget 或 exhausted lifecycle。质量审计与恢复流程不得自动执行下一次测量。

#### Scenario: Explicit local remeasurement supplies new evidence

- **WHEN** 主 Agent 认为某个候选或区域仍不确定，并调用测量工具提供局部 target/scope
- **THEN** 工具只在授权的同 panel 范围内测量并返回新的当前 attempt
- **AND** 新旧工具调用通过 attempt lineage 可关联，但系统不标记任何候选为 selected/discarded

#### Scenario: Repeated equivalent request is idempotent

- **WHEN** 相同的局部测量请求因重连或安全恢复被重复提交
- **THEN** 系统按既有幂等契约复用同一结果或返回明确状态
- **AND** 不创建隐藏的重复测量调用

#### Scenario: A failed target does not widen its scope

- **WHEN** 指定区域没有足够证据或范围无法应用
- **THEN** 工具返回有界的局部失败/不充分结果及原因
- **AND** 工具不得静默扩大到整个 panel 或源图再次搜索

### Requirement: Measurement quality does not create an assembly decision gate

测量结果 SHALL 经过适用的质量审计，但 measurement quality SHALL NOT 成为独占主链路或组装前 decision gate。`assemble_spec` SHALL 只校验实际引用的 evidence refs、来源范围和必要结构；warning、partial、未解析标签、未引用候选或缺少独立 decision 状态不得阻塞其他观察或合法组装。

#### Scenario: Measurement observation does not block unrelated work

- **WHEN** 测量返回 warning、partial 或其他质量诊断
- **THEN** 主 Agent 仍可调用 OCR、布局、其他测量或直接视觉装配
- **AND** 系统不创建独占 measurement review/decision gate

#### Scenario: Assembly validates only referenced evidence

- **WHEN** 主 Agent 提交 measurement/evidence refs 和 ChartSpec
- **THEN** 系统校验实际引用的 refs 属于当前来源、session 和 attempt
- **AND** 未引用误检不影响其他合法引用

#### Scenario: Invalid referenced evidence is rejected safely

- **WHEN** 主 Agent 引用不存在、越界、来源不匹配或缺少必要结构的 ref
- **THEN** `assemble_spec` 返回定位错误
- **AND** 系统不渲染或发布依赖该 ref 的结果

### Requirement: Measurement evidence exposes compact stable references

图表测量结果 SHALL 为可见候选提供有界且稳定的模型引用，例如柱体 `B1`、系列 `S1` 或饼图片区段引用。引用 SHALL 同时出现在结构化结果和对应 overlay 中，并 SHALL 与内部几何、scope 和 attempt identity 关联。引用仅用于证据交叉引用，不得被当作最终用户可见的系列名称或语义角色。

#### Scenario: Overlay and result share the same reference

- **WHEN** 测量工具返回柱体、系列、轨迹、散点或扇区候选
- **THEN** overlay 使用与结构化结果一致的 bounded reference
- **AND** 主 Agent 可以在 assembly 或局部测量调用中引用该 ref，而不必重复提交完整几何数据

#### Scenario: Internal reference is not rendered as a business label

- **WHEN** 主 Agent 使用测量引用组装 ChartSpec
- **THEN** 系统将引用与真实系列名称或未解析状态分开保存
- **AND** `series_1`、`B1` 等内部引用不得直接出现在最终用户图例中
### Requirement: Measurement evidence is bound to generation scope

为 generation candidate 提供的 measurement evidence SHALL 绑定到明确的 attachment、panel、attempt 和 effective scope；工具返回的 evidence refs SHALL 能够被装配和审核定位到同一来源范围。质量状态描述证据质量，不充当接受或采用标记。

#### Scenario: Same-panel evidence retains its source identity

- **WHEN** generation 使用某 panel 内测量得到的 evidence refs
- **THEN** attempt 与 refs 保留该 panel、effective scope 和质量元数据
- **AND** `assemble_spec` 可以校验并定位这些实际引用

#### Scenario: Cross-panel evidence is rejected by scope validation

- **WHEN** measurement attempt 来自 candidate 未授权的 panel
- **THEN** assembly 返回结构化的 scope mismatch
- **AND** 错误不改变或创建 evidence acceptance/selection 状态

### Requirement: Observation scope and measurement target have distinct meanings

首次测量 SHALL 可使用 `observation_scope` 描述本次调用要观察的区域；对已有结果的局部补测 SHALL 可用 `measurement_target` 指向候选引用或局部区域。每次工具调用都必须直接返回其实际应用的 effective scope 和测量结果，不得将 scope/target 转化为独立 pending action 或自动重测指令。

#### Scenario: Initial scoped observation is one measurement call

- **WHEN** 首次测量调用带有 panel 内的 `observation_scope`
- **THEN** 该调用创建一个 attempt 并返回实际范围和结果
- **AND** scope 成功应用本身不创建待完成的 observation obligation

#### Scenario: The model explicitly requests focused evidence

- **WHEN** 主 Agent 根据当前证据判断某候选或区域仍不确定
- **THEN** 主 Agent 可以再次调用现有测量工具并提交 `measurement_target`
- **AND** 只有该显式 tool call 会产生新的 attempt

### Requirement: Evidence quality does not autonomously select semantic roles

测量质量审计 SHALL 报告几何、数值、warning、候选引用和可用角色线索，但不得自动将 OCR/CV 候选升级为业务语义或替主 Agent 选择系列。模型可以在后续工具输入中引用需要使用的 evidence refs；未引用候选无需创建状态或决策对象。

#### Scenario: A false candidate is simply not referenced

- **WHEN** 测量结果包含可能是图例色块、文字或其他误检的候选
- **THEN** 结果提供位置、引用和可用角色线索
- **AND** 主 Agent 可以不在 `assemble_spec` 中引用该候选，无需单独提交 discarded 状态

### Requirement: Focused measurement closes its observation obligation

每次 focused measurement SHALL 是一个同步、完整的工具观察：scope 请求、实际应用范围、质量结果和候选 refs 作为同一次调用的结果返回。系统 SHALL NOT 将 `focus_applied` 与后续 observation 分成两个必须闭合的生命周期，也不得为此创建 pending measurement repair 状态。

#### Scenario: Applied focus returns its observation in the same result

- **WHEN** 主 Agent 请求同一 panel 内的局部测量且工具成功应用该范围
- **THEN** 工具结果同时包含 effective scope、当前 attempt、质量信息和对应 evidence refs
- **AND** 模型可立即继续组装、再次调用工具或采用其他路线

#### Scenario: Focus cannot produce an observation

- **WHEN** 局部范围无效、空白或无法产生可用结果
- **THEN** 当前工具调用返回明确的失败或不充分诊断
- **AND** 不留下需要后续关闭的 pending focus/measurement unit

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

source scope 错误与重新绑定 SHALL 通过对应的普通测量工具请求/结果保持在当前 attachment/panel 和 attempt 边界内。scope 错误、重新绑定或停止测量属于工具结果及模型后续实际动作，不形成独立的 measurement abandonment 状态；工具 SHALL NOT 自动扩大搜索范围或选择语义角色。

#### Scenario: Rebinding does not widen measurement

- **WHEN** Agent 根据工具返回的 scope 诊断重新提交同一 panel 的 source context
- **THEN** 新工具调用明确关联来源及可用父 attempt，并只读取授权同范围
- **AND** 工具不因首次 scope 错误而回退到全图测量
