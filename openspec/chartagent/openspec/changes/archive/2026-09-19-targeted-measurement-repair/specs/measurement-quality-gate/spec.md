## ADDED Requirements

### Requirement: Measurement issues expose machine-readable repair targets

当测量质量审计发现需要补充证据的问题时，系统 SHALL 返回有界的 repair action 和 measurement target。target 至少能够表达当前 `attachment_id`、`panel_id`、父 attempt、目标区域或证据位置、受影响字段以及建议的测量工具；缺少可靠区域时 SHALL 明确表示需要 panel 级复查，而不得伪造精确框选。

#### Scenario: Baseline issue identifies a bounded target

- **WHEN** 柱状图测量因零基线残差或基准线冲突进入 `remeasure_required`
- **THEN** 质量结果包含指向当前 panel 和 baseline 字段的 repair action
- **AND** 如果源图坐标足够可靠，target 包含有界的源图区域和父 attempt 引用

#### Scenario: Repair target cannot cross panel boundaries

- **WHEN** 模型提交的 repair target 不属于当前 measurement session 的 attachment 或 panel
- **THEN** 系统拒绝该 target 并返回结构化来源不匹配问题
- **AND** 不创建新的可接受 measurement attempt

### Requirement: Remeasurement attempts are bounded and re-audited

每次定向重测 SHALL 在同一 run、attachment 和 panel 的 measurement session 中创建新的 attempt，并记录父 attempt、target 和修复原因。重测结果 SHALL 重新经过质量审计；重复的等价请求 SHALL 幂等，且超过有界预算时 SHALL 保留明确的非接受状态。

#### Scenario: A corrected local attempt can become accepted

- **WHEN** 当前 panel 的定向重测解决了父 attempt 的阻断 issue，且视觉证据、作用域和图表专属检查均通过
- **THEN** 新 attempt 被标记为 `accepted`
- **AND** `assemble_spec` 只能引用该新 attempt，而不能继续使用未接受的父 attempt

#### Scenario: Repair budget is exhausted

- **WHEN** 同一 panel 的重测次数达到配置上限，或同一 target 被重复拒绝
- **THEN** session 返回 `failed`、`partial` 或 `remeasure_required` 中适用的终态
- **AND** Agent 保留问题、attempt lineage 和可恢复上下文，不发布未经接受的 ChartSpec
