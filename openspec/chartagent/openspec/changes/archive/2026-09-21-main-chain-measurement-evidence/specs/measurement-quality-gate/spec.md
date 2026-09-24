## MODIFIED Requirements

### Requirement: Measurement evidence has an explicit lifecycle

系统 SHALL 为每次源图测量提供明确的生命周期状态，至少区分 `provisional`、`accepted`、`remeasure_required`、`partial`、`unsupported` 和 `failed`。初次测量 SHALL 默认作为候选证据；`remeasure_required`、warning 或低置信度 SHALL 只表示需要主 Agent 判断的证据状态，不得自动触发重测。只有主 Agent 明确选择可用证据且硬性校验通过后，测量 attempt 才能成为 `accepted`。

#### Scenario: Initial measurement remains provisional

- **WHEN** 柱状图、折线图、饼图或散点图传感器完成一次测量
- **THEN** 结果包含有界的测量状态、confidence、warnings、证据引用和结构化质量信息
- **AND** 结果在主 Agent 作出选择前不得被下游默认为已经确认的源图数值

#### Scenario: Uncertainty does not trigger an automatic remeasurement

- **WHEN** 测量发现基准线、坐标标定、系列关联、覆盖范围或几何支持存在不确定性
- **THEN** 结果以 `remeasure_required`、`partial` 或其他适用的非接受状态报告具体证据问题
- **AND** 系统只把局部目标建议提供给主 Agent，不得自动调用任何测量工具

#### Scenario: Main Agent accepts selected evidence

- **WHEN** 主 Agent 根据原图、overlay、证据引用和质量信息选择一组候选
- **THEN** 系统记录被选择、被舍弃和仍不确定的证据引用
- **AND** 只有被选择且通过硬性校验的 attempt 或候选子集可以进入 `accepted` 状态

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

### Requirement: Measurement issues expose machine-readable repair targets

当测量质量审计发现需要补充证据的问题时，系统 SHALL 返回有界的 focus suggestion 或 measurement target。target 至少能够表达当前 panel、目标证据引用或区域、受影响字段、`include`/`exclude` 模式以及原因；target 是主 Agent 可主动提交的工具输入，不是代码审核器自动执行的命令。缺少可靠区域时 SHALL 明确表示需要主 Agent 重新选择观察范围，而不得伪造精确框选。

#### Scenario: Baseline issue identifies a bounded target

- **WHEN** 柱状图测量因零基线残差或基准线冲突进入非接受状态
- **THEN** 质量结果包含指向当前 panel、baseline 字段和相关证据引用的 focus suggestion
- **AND** 如果源图坐标足够可靠，target 可以包含有界的源图区域或可解析的候选引用

#### Scenario: Repair target cannot cross panel boundaries

- **WHEN** 主 Agent 提交的 measurement target 不属于当前 measurement session 的 attachment 或 panel
- **THEN** 系统拒绝该 target 并返回结构化来源不匹配问题
- **AND** 不创建新的可接受 measurement attempt

#### Scenario: A suggestion alone does not authorize execution

- **WHEN** 测量结果包含 focus suggestion 但主 Agent 没有发起带 target 的测量工具调用
- **THEN** 系统保持当前证据为 provisional 或非接受状态
- **AND** 不执行局部重测，也不改变当前 attempt 的 lineage

### Requirement: Remeasurement attempts are bounded and re-audited

每次定向重测 SHALL 由主 Agent 在主链路中显式调用原图表测量工具发起，并 SHALL 在同一 run、attachment 和 panel 的 measurement session 中创建新的 attempt，记录父 attempt、target、证据引用和修复原因。重测结果 SHALL 重新经过质量审计；重复的等价请求 SHALL 幂等，且超过有界预算时 SHALL 保留明确的非接受状态。代码不得在质量审计或恢复过程中自动重复调用测量工具。

#### Scenario: A corrected local attempt can become accepted

- **WHEN** 主 Agent 使用有效 target 调用同一图表测量工具，且定向重测解决了父 attempt 的阻断 issue
- **THEN** 新 attempt 返回新的证据和 overlay，并可以在主 Agent 再次选择后被标记为 `accepted`
- **AND** `assemble_spec` 只能引用新 attempt 中被选择的证据，不能继续使用未接受的父 attempt

#### Scenario: Repair budget is exhausted

- **WHEN** 同一 panel 的主 Agent 定向重测次数达到配置上限，或同一 target 被重复提交
- **THEN** session 返回 `failed`、`partial`、`remeasure_required` 或结构化重复错误中的适用结果
- **AND** 系统保留问题、attempt lineage 和可恢复上下文，不发布未经接受的 ChartSpec

#### Scenario: A failed target does not fall back to full-panel measurement

- **WHEN** 定向区域内没有足够证据或 mask 无法应用
- **THEN** 工具返回 `focus_empty`、`focus_insufficient` 或等价的非接受结果
- **AND** 工具不得静默扩大到整个 panel 再次搜索

### Requirement: Measurement review is a hard gate for the main chain

测量证据 SHALL 在进入 `assemble_spec` 前经过主 Agent 的明确选择；系统 SHALL 提供硬性门禁阻止未选择、未归属、越界、重复或未通过必要结构校验的证据进入装配。该门禁 SHALL 不作为独立语义审核者，不得自动生成或执行重测。

#### Scenario: Measurement decision blocks assembly

- **WHEN** 一次测量返回 `provisional`、`remeasure_required`、`partial`、`unsupported` 或 `failed`
- **THEN** 系统阻止依赖该测量的 assemble 和后续生成阶段
- **AND** 主 Agent 可以在同一主链路中选择证据、舍弃候选或显式调用带 target 的原测量工具

#### Scenario: Assembly receives selected evidence

- **WHEN** 主 Agent 提交带有当前 panel 证据引用的 `assemble_spec` 请求
- **THEN** 系统校验引用属于当前 attachment、panel 和已记录 attempt
- **AND** 只有满足硬性校验且被主 Agent 选择的证据可以进入 ChartSpec

#### Scenario: A failed measurement does not schedule an automatic repair

- **WHEN** 测量门禁发现阻断问题
- **THEN** 当前主链路收到结构化的 `measurement_decision_required` 或等价上下文
- **AND** 系统不得自动追加测量修复消息、自动调用测量工具或切换到其他 panel

#### Scenario: Measurement exhaustion prevents chart output

- **WHEN** 主 Agent 的定向重测失败或达到预算上限
- **THEN** 当前 run 保留 attempt lineage、问题和恢复信息
- **AND** 系统不得组装或发布基于未接受测量的 ChartSpec

## ADDED Requirements

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
