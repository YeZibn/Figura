## ADDED Requirements

### Requirement: A candidate attempt has one canonical review cycle

每个 generated candidate attempt SHALL 对外表现为一个 canonical review cycle。该 cycle 可以包含 deterministic quality audit、semantic VLM review、repair decision 和最终状态，但 shared gate 更新、review snapshot 和子检查结果不得各自创建新的顶层审核周期。

#### Scenario: Review cycle contains deterministic and semantic checks

- **WHEN** 候选先通过确定性质量检查，再等待或执行 semantic VLM review
- **THEN** gate 维持同一个 review identity 和 candidate attempt
- **AND** 时间线只显示一个审核周期及其子检查状态

#### Scenario: Replayed state does not reopen a completed cycle

- **WHEN** 相同 candidate attempt 的 completed review snapshot 被重复提交
- **THEN** gate 返回已有 review state
- **AND** 不重复执行审核或重新打开 publication gate

### Requirement: Review repair exposes one ordered next phase

每种 repair kind SHALL 暴露当前 phase 和唯一允许的下一阶段集合。`evidence_needed` 的合法顺序 SHALL 为 same-scope evidence、assemble、render、review；`spec_only` 不得直接跳过 assemble/render；`source_rebind` 不得在旧 scope 上继续补测。

#### Scenario: Evidence repair follows the bounded path

- **WHEN** review 返回 evidence_needed
- **THEN** 主链路只能在同一 scope 完成证据、重新 assemble、重新 render 并回到 review
- **AND** 跨 panel、跳过 assemble 或直接 publication 的请求被拒绝并记录 scope/gate violation

#### Scenario: Unresolved next action blocks publication

- **WHEN** review cycle 仍有 required next action
- **THEN** gate 保持 blocking
- **AND** final text、tool result snapshot 或旧 review 状态不能释放 publication

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
