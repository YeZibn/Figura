# agent-session-memory Specification

## Purpose

Provide resumable named Agent sessions and bounded model context while keeping the default interaction ephemeral and preserving valid tool-message groups.

## Requirements

### Requirement: Named Agent sessions are durable and opt-in

The system SHALL allow named sessions to restore completed runs after restart; without a named session, Agent history SHALL remain process-local.

#### Scenario: Named session resumes after restart

- **WHEN** a completed named session is opened again
- **THEN** its prior user, tool, and assistant information can enter bounded context

#### Scenario: Sessions are isolated

- **WHEN** two named sessions contain different histories
- **THEN** each exposes only records owned by that session

### Requirement: Agent runs have durable lifecycle states

Named runs SHALL persist ordered records with running, completed, failed, or interrupted states. Only completed runs SHALL enter later model context.

#### Scenario: Abandoned run is interrupted

- **WHEN** a session is reopened with an unfinished running run
- **THEN** that run becomes interrupted and its partial protocol is excluded

### Requirement: Model context is bounded by complete run blocks

Context SHALL contain the system prompt, bounded deterministic summaries, complete recent runs, and the current run. Assistant tool calls and matching tool results SHALL never be split.

#### Scenario: History exceeds the limit

- **WHEN** completed history exceeds the configured context limit
- **THEN** older completed runs are summarized deterministically without another model call

### Requirement: Durable memory excludes sensitive and binary content

Memory MUST exclude reasoning, credentials, raw provider responses, image bytes, data URLs, and unbounded tool content while retaining safe attachment references.

#### Scenario: Images are represented by references

- **WHEN** an image participates in a named run
- **THEN** only safe metadata and authorized references are persisted

### Requirement: Named sessions can be inspected and deleted

Users SHALL be able to list bounded session metadata and explicitly delete a session; deletion SHALL not modify referenced source files.

#### Scenario: Confirmed deletion

- **WHEN** the user confirms deletion
- **THEN** the session state and references are removed but source files remain

### Requirement: Recovery context is explicit and separate from normal conversation history

The memory layer SHALL persist the bounded context needed for an explicit
continuation without treating an interrupted or uncertain run as a completed
conversation turn. Normal new Agent turns SHALL continue to use only
completed runs for ordinary historical context, while a validated resume may
read the parent run's safe checkpoint and committed records. Recovery context
SHALL retain authorized references instead of binary or sensitive content.

#### Scenario: Resumed child reads safe parent context

- **WHEN** a validated continuation starts from an interrupted parent with a
  recoverable checkpoint
- **THEN** the child can reconstruct the bounded messages and committed tool
  results required for its next action
- **AND** the parent remains excluded from ordinary completed-run context

#### Scenario: New user turn does not inherit incomplete execution

- **WHEN** a user starts an unrelated new turn after an interrupted run
- **THEN** the interrupted run's partial protocol is not silently included as
  completed conversation history
- **AND** only an explicit resume can request its recovery context

#### Scenario: Expired recovery context is explicit

- **WHEN** the checkpoint or one of its authorized references has expired or
  been removed
- **THEN** the memory layer reports that continuation is unavailable
- **AND** it does not present the incomplete parent as a successful run

### Requirement: Session memory restores source and panel context

命名 session 的持久化状态 SHALL 包含活动源附件和有效 PanelHandoff 的安全引用。新 Agent run SHALL 在建立模型上下文前恢复这些引用；文本历史可作为语义辅助，但不得替代结构化 panel registry。

#### Scenario: New Agent runtime hydrates panel context

- **WHEN** named session 创建新的 Agent runtime
- **THEN** runtime 获得当前活动源和面板目录
- **AND** 模型可以直接使用已有 panel ID 而不依赖旧 run 的内存对象

### Requirement: Sessions isolate panel registries

一个 session 的源附件和 PanelHandoff SHALL 不得被另一个 session 的 run 解析或复用。

#### Scenario: Cross-session panel access is rejected

- **WHEN** run 使用属于其他 session 的 panel ID
- **THEN** 系统拒绝该引用并记录结构化授权错误
