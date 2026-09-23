# run-checkpoint-recovery Specification

## Purpose

为异步 Agent 运行提供受约束、可审计的安全检查点和恢复关系，使系统能够继续已确认完成的工作，同时避免重放不确定的模型、工具、审核或发布操作。

## Requirements

### Requirement: Safe checkpoints describe committed next actions

The system SHALL persist a bounded, versioned checkpoint for a recoverable
run. A checkpoint SHALL identify the run and session, the last committed work
unit, the next intended action, the relevant model/provider context, safe
attachment and artifact references, and its recovery status. A checkpoint SHALL
only describe work whose result has been durably committed; it MUST NOT claim
that an in-flight operation completed.

#### Scenario: Completed tool work creates a recoverable checkpoint

- **WHEN** a tool call and its bounded result have been durably committed
- **THEN** the run exposes a checkpoint identifying that completed call and the
  next Agent action
- **AND** the checkpoint can be used to evaluate whether explicit resume is
  available

#### Scenario: Checkpoint content is bounded and safe

- **WHEN** a checkpoint references model context, tool output, chart evidence,
  or attachments
- **THEN** it retains bounded sanitized content or authorized references
- **AND** it excludes credentials, raw provider responses, image bytes, data
  URLs, and local source paths

#### Scenario: Uncertain work is not reported as committed

- **WHEN** a provider, tool, review, or publication operation has started but
  its durable result is unavailable
- **THEN** the checkpoint marks recovery as blocked or uncertain
- **AND** it does not advertise that operation as completed

### Requirement: Operation records prevent unsafe replay

The system SHALL assign each resumable work unit a stable operation identity
and bounded state of `not_started`, `in_flight`, or `completed`. A recovery
attempt SHALL reuse a committed result for a completed operation, MAY execute
an operation that is known not to have started, and SHALL NOT automatically
replay an operation left in an uncertain or in-flight state unless an explicit
idempotency contract proves that replay is safe.

#### Scenario: Completed operation is reused during resume

- **WHEN** a resumed run reaches an operation whose durable record is
  `completed`
- **THEN** it loads the recorded bounded result or reference
- **AND** it does not invoke the provider, tool, review, or publication action
  a second time

#### Scenario: Not-started operation can continue

- **WHEN** a checkpoint identifies the next operation as `not_started`
- **THEN** an explicit resume may execute that operation
- **AND** the operation is recorded with the resumed run's lineage

#### Scenario: In-flight operation requires a safe decision

- **WHEN** recovery encounters an operation with `in_flight` or uncertain state
  and no replay-safe contract
- **THEN** the system returns a bounded recovery-blocked outcome
- **AND** it offers a fresh retry path without silently duplicating the
  operation

### Requirement: Resume creates an attributable child run

The system SHALL allow an explicit resume only for a run with a valid
recoverable checkpoint. Resume SHALL create a new run identity and a new
idempotency identity, retain the original run's terminal state, and record a
bounded parent relationship with continuation kind `resume`. Repeating the same
resume intent SHALL resolve to the same child run without starting another
recovery execution.

#### Scenario: Recoverable interrupted run is resumed

- **WHEN** a user explicitly resumes an interrupted run with an available
  checkpoint
- **THEN** the system creates a new running child run
- **AND** the child identifies the prior run as its resume parent

#### Scenario: Parent terminal state remains immutable

- **WHEN** a resume child is created or completes
- **THEN** the original interrupted, failed, or completed run remains unchanged
- **AND** new execution events belong only to the child run

#### Scenario: Duplicate resume intent is replayed

- **WHEN** the client repeats a resume request with the same session, parent,
  checkpoint, and idempotency key
- **THEN** the system returns the original child run and current state
- **AND** it does not create a second child execution

### Requirement: Checkpoints retain source and panel references

可恢复 checkpoint SHALL 在安全引用范围内保存 active attachment、panel ID、PanelHandoff revision、当前候选 ID、审核状态、已用修复次数和下一步意图。checkpoint 不得声称尚未提交的拆解、测量、审核或发布已完成。

#### Scenario: Interrupted scoped analysis can resume

- **WHEN** 一个 panel-scoped 工具已完成并在下一次模型调用前中断
- **THEN** checkpoint 保留该 panel ID 和已提交的工具结果
- **AND** resume 不需要重新拆解，也不重复执行已确认完成的工作

### Requirement: Review recovery is resumable but bounded

checkpoint SHALL 区分 source binding、spec correction、review retry 和 retry exhausted 状态，并 SHALL 防止恢复过程无限重复同一候选或同一失败动作。

#### Scenario: Resume after a semantic review failure

- **WHEN** 候选审核失败且仍有修复预算
- **THEN** checkpoint 指向结构化审核诊断和修正下一步
- **AND** resume 创建新的候选链路而不是重复发布旧候选

### Requirement: Checkpoints preserve the active review gate

可恢复 checkpoint SHALL 保存活动 generated-chart review 的 subject、审核状态、attempt/candidate 引用、已用预算、问题和允许的下一步动作。measurement observation 不属于独立 review gate；checkpoint 对测量仅保存重建当前 measurement session/attempt 所需的来源、refs、scope 和质量事实。恢复不得将 generated-chart reviewing、repair_required 或失败状态升级为已通过。

#### Scenario: Resume after a measurement tool call

- **WHEN** 运行在测量工具调用前中断，或测量完成后尚未进入下一模型轮次
- **THEN** checkpoint 保存足以恢复当前 session/current attempt 的 bounded 来源范围和结果事实
- **AND** resume 不重新拆解已确认面板、不重复已经完成的测量，也不等待或要求 measurement decision

#### Scenario: Resume after generated chart review interruption

- **WHEN** 候选图已生成但审核结果尚未持久化完成
- **THEN** checkpoint 将审核标记为未完成或不确定
- **AND** resume 不重复发布旧候选，只有在幂等审核结果确认后才可释放该审核状态

#### Scenario: Recovery cannot skip a generated-chart review

- **WHEN** 用户从包含活动 generated-chart review 状态的 checkpoint 继续运行
- **THEN** 子 run 继承该审核状态和修复预算
- **AND** 只有新的有效审核结果才能进入下一阶段
