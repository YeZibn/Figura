## MODIFIED Requirements

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

### Requirement: A candidate attempt has one canonical review cycle

每个 generated candidate attempt SHALL 对外表现为一个 canonical review cycle。内部 deterministic audit、semantic VLM review、状态快照和修复分类 SHALL 继续可追踪，但默认用户时间线 SHALL 只显示一次审核开始和一个最终审核结果；失败结果 SHALL 显示原因。

#### Scenario: Internal checks produce one visible review summary

- **WHEN** 候选依次执行确定性检查和 semantic VLM review
- **THEN** gate 维持同一个 review identity
- **AND** 默认客户端不把内部检查显示为多个 subcheck 或重复审核步骤

#### Scenario: Replayed state does not reopen a completed cycle

- **WHEN** 相同 candidate attempt 的 completed snapshot 被重复提交
- **THEN** gate 返回已有 review state
- **AND** 不重复审核、不重复显示审核周期或释放错误 publication

## REMOVED Requirements

### Requirement: Evidence repair is an in-gate bounded sub-loop

**Reason**: 固定 same-scope evidence -> assemble -> render -> review 顺序会在问题分类不准确时阻止模型选择更合适的修复动作。

**Migration**: gate 只保持候选不可发布并提供诊断；各工具自行校验安全边界，新候选统一重新审核。

### Requirement: Review repair exposes one ordered next phase

**Reason**: 唯一 repair phase 把审核建议升级成代码拥有的业务流程，与模型自主工具选择目标冲突。

**Migration**: 保留 repair kind、lineage 和预算作为事实，不再根据 phase 拒绝同范围合法调用。
