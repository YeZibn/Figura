# run-lifecycle-reliability Specification

## Purpose

Provide one reliable lifecycle contract for an asynchronous Agent run from
client intent through execution, interruption, event replay, and terminal
outcome, so reconnecting or retrying a client cannot accidentally duplicate
work or hide what happened to the original run.

## Requirements

### Requirement: One client intent creates at most one accepted run

The system SHALL allow a client to associate an asynchronous run request with
an idempotency key and a bounded request fingerprint. Repeating the same key
with the same fingerprint SHALL resolve to the original accepted run without
starting another execution. Reusing the key with a different fingerprint
SHALL produce an explicit conflict and SHALL not create or mutate a run.
Requests without a key MAY remain supported for compatibility, but the
first-party client SHALL provide a key whenever it submits a run.

#### Scenario: Repeated submission after a lost response

- **WHEN** the client submits the same session, text, attachments, provider,
  and idempotency key again after losing the first response
- **THEN** the Gateway returns the original run identity and current state
- **AND** it does not submit a second Agent execution

#### Scenario: Idempotency key is reused for different work

- **WHEN** a client submits a different request under an already-used
  idempotency key
- **THEN** the Gateway returns a bounded idempotency-conflict error
- **AND** the original run and its events remain unchanged

#### Scenario: Legacy request omits an idempotency key

- **WHEN** a compatible client submits a valid run without an idempotency key
- **THEN** the Gateway may accept it as a new run
- **AND** the response does not claim idempotent replay protection for that
  request

### Requirement: Every run has one durable terminal outcome

The system SHALL expose a run state that distinguishes active execution from
completed, failed, and interrupted outcomes. A run SHALL enter at most one
terminal outcome, SHALL retain a bounded terminal reason, and SHALL expose
that outcome consistently through the run summary, event history, and client
state. Events or results arriving after terminalization SHALL NOT change the
terminal outcome or appear as new execution progress.

#### Scenario: Successful run terminalizes once

- **WHEN** an accepted run produces its final answer
- **THEN** the system records one completed outcome and a terminal event
- **AND** later completion or failure attempts leave that outcome unchanged

#### Scenario: Competing terminal transitions race

- **WHEN** interruption, provider failure, and successful completion become
  ready concurrently
- **THEN** exactly one transition wins according to the run's serialized
  terminal transition
- **AND** all later transitions are ignored or reported as already terminal

#### Scenario: Late provider result arrives after interruption

- **WHEN** a provider or tool returns after the run has been interrupted
- **THEN** the result is discarded for publication purposes
- **AND** it cannot append a misleading final answer or overwrite the
  interruption reason

### Requirement: Event subscriptions resume the same run

The system SHALL identify each run event with a monotonic per-run sequence and
SHALL support replaying events after a client cursor before continuing with
live events. Clients SHALL be able to deduplicate replayed events, detect
retention gaps explicitly, and stop reconnecting once the durable run outcome
is terminal.

#### Scenario: Client reconnects after an SSE interruption

- **WHEN** an active run's event connection breaks after the client applied
  sequence 7
- **THEN** the client requests events after sequence 7 for the same run
- **AND** the Gateway returns the missing ordered events without creating a
  new run

#### Scenario: Replayed event overlaps the client buffer

- **WHEN** a reconnect returns an event the client has already applied
- **THEN** the client ignores the duplicate by run identity and sequence
- **AND** it preserves the existing event order

#### Scenario: Retained history cannot satisfy the cursor

- **WHEN** the requested cursor is older than the retained history
- **THEN** the Gateway reports an explicit history gap or unavailable result
- **AND** the client does not present the partial replay as a complete trace

### Requirement: Interruptions are explicit and cooperative

The system SHALL support user-requested interruption and system-detected
interruption, each with a bounded reason code and user-facing state. An
interruption request SHALL be idempotent after the run is terminal. Active
Agent work SHALL observe the interruption signal at safe boundaries and SHALL
stop starting additional model, tool, rendering, or review work when possible.
Disconnecting a client SHALL NOT itself interrupt the backend run.

#### Scenario: User interrupts an active run

- **WHEN** an authorized client requests interruption for an active run
- **THEN** the run transitions to interrupted with a user-cancel reason
- **AND** the client receives or can replay an explicit terminal event

#### Scenario: Gateway restart interrupts active work

- **WHEN** the Gateway restarts while a run is marked active
- **THEN** the run becomes interrupted with a gateway-restarted reason
- **AND** a later history request exposes that terminal state

#### Scenario: User repeats interruption after terminalization

- **WHEN** a client requests interruption for a completed, failed, or already
  interrupted run
- **THEN** the Gateway returns the existing terminal state without changing it

### Requirement: Retry and resume create attributable child runs

The system SHALL distinguish reconnect, resume, and retry. Reconnect SHALL
retain the same run identity and idempotency context. An explicit resume SHALL
require a valid recoverable checkpoint, create a new run identity and new
idempotency context, and retain a bounded `resume` parent relationship. An
explicit retry SHALL create a new run identity and new idempotency context from
the original request, retaining a bounded `retry` parent relationship and the
prior run's terminal reason. Neither operation SHALL mutate the parent run or
append new execution events to it.

#### Scenario: User resumes a recoverable interrupted run

- **WHEN** the user explicitly resumes an interrupted run with an available
  safe checkpoint
- **THEN** the system creates a new child run with a new identity
- **AND** the child records the prior run as its `resume` parent

#### Scenario: Resume is unavailable for uncertain work

- **WHEN** a run has no valid checkpoint or contains an uncertain operation
  without a replay-safe contract
- **THEN** resume is rejected with a bounded recovery reason
- **AND** the system leaves the original run unchanged and offers retry as a
  separate operation

#### Scenario: User retries from the original request

- **WHEN** the user explicitly retries a failed or interrupted run
- **THEN** the Gateway creates a new run with a new identity and a `retry`
  parent relationship
- **AND** the new run starts from the original user request rather than the
  checkpoint

#### Scenario: Reconnect is not resume or retry

- **WHEN** the client loses an event connection but has not requested resume or
  retry
- **THEN** the client only resumes the existing run by identity and sequence
- **AND** no new user message or Agent execution is created

### Requirement: Deterministic provider rejection is not an uncertain recovery block

当 provider 已明确拒绝请求并且系统能够确认该结果时，run SHALL 以 provider-blocked 或等价的确定性失败终止，保留可展示的原因和重试建议。该结果不得被标记为远端操作结果未知，也不得自动创建 resume checkpoint。

#### Scenario: Provider returns a known rejection

- **WHEN** 模型请求收到确定性的余额、授权、参数或限流拒绝
- **THEN** run 进入唯一的 failed terminal outcome，并记录稳定分类和 provider 原因
- **AND** `recovery_blocked` 只用于真正的恢复不确定性，不覆盖该失败原因

#### Scenario: User retries after a deterministic rejection

- **WHEN** 用户针对已失败的 provider rejection 显式发起 retry
- **THEN** 系统创建可归因的新 child run
- **AND** 父 run 的失败原因和事件保持不变

### Requirement: Explicit recovery distinguishes replayable requests from unknown external effects

运行仍 SHALL 只使用 running、completed、failed、interrupted 四态。恢复资格 SHALL 从有效 checkpoint、授权引用和下一动作的重放契约推导；未提交模型/VLM 请求可以在显式 resume 后重新请求，只有不可核对的外部副作用结果不明时才阻止自动继续。断线重连 SHALL 保持原 Run，resume SHALL 产生可归因子 Run。

#### Scenario: Provider times out before local commit
- **WHEN** 模型请求超时且没有已提交响应
- **THEN** 原 Run 保留明确失败或中断原因
- **AND** 用户显式 resume 后系统可以重新请求，同时说明可能重复费用

#### Scenario: Reconnect does not reissue a model request
- **WHEN** 仅 SSE 连接断开
- **THEN** 客户端按原 Run 的事件序号重连
- **AND** 不创建子 Run 或重复模型调用
