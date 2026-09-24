## MODIFIED Requirements

### Requirement: Measurement evidence has an explicit lifecycle

系统 SHALL 为每次源图测量提供可追踪的执行状态、质量结果、attempt lineage 和实际下游使用情况。质量结果 SHALL 保留 `provisional`、`partial`、`remeasure_required`、`unsupported` 和 `failed` 等适用诊断；模型无需为每次 attempt 创建 selected/discarded/abandoned 状态。质量 warning 或局部问题不得自动成为主流程门禁。

#### Scenario: Initial measurement remains candidate evidence

- **WHEN** 任一图表传感器完成测量
- **THEN** 结果包含执行状态、质量信息、refs、overlay 和 attempt 身份
- **AND** 系统不自动把候选声明为最终事实

#### Scenario: Warning does not force retry or decision

- **WHEN** 测量存在标定、关联、覆盖或几何 warning
- **THEN** 结果保留问题和可选补充建议
- **AND** 系统不自动重测、不阻塞其他工具，也不要求先提交舍弃状态

#### Scenario: Actual evidence use is recorded

- **WHEN** 后续装配引用该 attempt 的部分 refs
- **THEN** 系统记录实际使用的 refs 和 provenance
- **AND** 未使用 refs 保持普通候选状态

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

### Requirement: Evidence quality does not autonomously select semantic roles

测量质量审计 SHALL 报告几何、数值、warning、候选引用和可用角色线索，但不得自动把 OCR/CV 候选升级为业务语义，也不得替主 Agent选择系列。主 Agent通过最终工具输入、ChartSpec 语义和实际引用表达选择，系统不要求额外的 decision 对象。

#### Scenario: Legend swatch is ignored by model choice

- **WHEN** 测量结果包含可能是 legend swatch 的候选
- **THEN** 结果提供位置和角色线索
- **AND** 主 Agent可以不引用该候选，无需单独提交 discarded 状态

### Requirement: Focused measurement closes its observation obligation

局部测量 SHALL 区分 focus request、effective scope 和 measurement observation。`focus_applied` 只有在绑定明确 attempt 时才有效；无有效 observation 时 SHALL 记录 pending 或 failed 事实，但不得要求模型关闭独立 decision unit，也不得单独阻止模型选择其他合法修复路线。

#### Scenario: Applied focus is followed by same-scope observation

- **WHEN** 主 Agent请求局部测量且工具成功应用范围
- **THEN** attempt 记录 effective scope 并返回 observation
- **AND** 后续装配可以直接引用其 refs

#### Scenario: Applied focus has no observation

- **WHEN** 局部范围已应用但没有有效 observation
- **THEN** 系统记录 pending 或 failed 状态和诊断
- **AND** 主 Agent可以选择其他授权工具、调整范围或停止

## REMOVED Requirements

### Requirement: Evidence decisions are bound to one measurement attempt

**Reason**: 独立且必须持久化的 decision 状态与实际装配引用重复，并会制造第二套业务状态机。

**Migration**: 保留旧 decision 事件的读取能力；新运行从工具调用和实际引用派生 provenance。

### Requirement: Required and optional measurement actions are distinguishable

**Reason**: 将审核分类转换为 required measurement action 会替模型固定修复路线；系统只需限制来源和发布，不应强制补测。

**Migration**: 所有 measurement target 都由模型显式调用；审核 target 作为建议，重试预算继续限制调用次数。
