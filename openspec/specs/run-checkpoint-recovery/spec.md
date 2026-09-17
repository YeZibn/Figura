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
