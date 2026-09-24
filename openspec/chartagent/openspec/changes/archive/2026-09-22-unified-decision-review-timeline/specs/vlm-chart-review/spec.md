## ADDED Requirements

### Requirement: Deterministic and semantic checks share one review cycle

生成候选的 deterministic quality audit 与 semantic VLM review SHALL 共享 candidate、review 和 attempt 身份，但必须在结构化结果中区分检查类型、状态、问题和来源。确定性检查的完成不得冒充 VLM 语义审核通过。

#### Scenario: Deterministic audit passes before VLM review

- **WHEN** renderer 质量检查通过但 source-linked candidate 尚未完成 VLM review
- **THEN** candidate 仍保持 review_pending 或 blocking
- **AND** publication status 不得变为 published

#### Scenario: VLM review fails after audit

- **WHEN** deterministic audit 通过而 VLM 返回 repair_required 或 failed
- **THEN** review cycle 保留两个子检查结果和明确的 repair kind
- **AND** 不覆盖 deterministic audit 的原始诊断

### Requirement: Semantic VLM invocation is bounded per candidate attempt

同一 candidate attempt SHALL 至多产生一个语义 VLM review decision。重复请求相同 candidate、attempt、review identity 和输入 digest SHALL 幂等复用已有结果；真正的新语义判断必须创建新的 attempt 或显式的 review retry lineage。

#### Scenario: Review state update does not call VLM again

- **WHEN** shared review adapter 或 tool result snapshot 重复提交同一 candidate review state
- **THEN** 系统只返回已有语义结果
- **AND** 不新增 VLM invocation 或第二个 review start transition

#### Scenario: New repair attempt receives a new semantic review

- **WHEN** ChartSpec 修复或同 scope evidence repair 产生新的 candidate attempt
- **THEN** 新 attempt 可以执行一次新的 VLM review
- **AND** 新旧 attempt 的结果、输入 digest 和 repair lineage 保持可区分

### Requirement: Collection review keeps child semantic outcomes attributable

当一个 ChartSpec collection 产生多个 child candidates 时，VLM review 结果 SHALL 同时保留 collection/figure/child 的安全引用。父级汇总不得删除 child 的 issue、repair kind 或 publication 状态。

#### Scenario: Child review is expanded from the parent

- **WHEN** 用户查看 collection 的统一 review cycle 并展开一个 child
- **THEN** 客户端可以看到该 child 的 source scope、candidate attempt、VLM decision 和 issues
- **AND** 其他 child 的结果不会混入该 child 的语义判断
