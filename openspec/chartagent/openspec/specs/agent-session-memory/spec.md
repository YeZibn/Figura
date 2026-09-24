# agent-session-memory Specification

## Purpose

Provide resumable named Agent sessions and bounded model context while keeping the default interaction ephemeral and preserving valid tool-message groups.

## Requirements

### Requirement: Named Agent sessions are durable and opt-in

The system SHALL allow named sessions to restore completed runs after restart; without a named session, Agent history SHALL remain process-local. Named-session state SHALL be stored in `sessions.db` below the canonical data root; when no explicit data root is configured, that root SHALL be the project-local `.chartagent/` directory.

#### Scenario: Named session resumes after restart

- **WHEN** a completed named session is opened again
- **THEN** its prior user, tool, and assistant information can enter bounded context

#### Scenario: Sessions are isolated

- **WHEN** two named sessions contain different histories
- **THEN** each exposes only records owned by that session

#### Scenario: Default session database is project-local

- **WHEN** a named session is created without an explicit data root or `CHARTAGENT_DATA_DIR`
- **THEN** its durable records are written to the project-local `.chartagent/sessions.db`
- **AND** the runtime does not create or update a second default database under `~/.chartagent`

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

### Requirement: Ordinary memory and private recovery context have separate visibility

普通会话记忆 SHALL 继续排除 reasoning、凭证、原始 provider 响应、图像字节、数据 URL 和本地路径。恢复所必需的 provider 私有续接字段 MAY 在有界、受限的私有执行记录中保存，并只向经授权的显式 resume 提供；它们 MUST NOT 流入普通上下文、transcript、trace、SSE 或评测资源。

#### Scenario: Private continuation is not a transcript
- **WHEN** 某已中断 Run 包含 provider 私有续接字段
- **THEN** 授权子 Run 可以恢复所需模型协议
- **AND** 用户读取会话历史时看不到该字段

### Requirement: New schema starts with empty legacy session data

新版存储切换 SHALL 不迁移旧会话、附件、Run 历史和已发布图表；配置路径中的旧托管数据清理后，新创建的 session、附件和 Run 仍 SHALL 持久且相互隔离。外部原始源图 SHALL 不受清理影响。

#### Scenario: Fresh session after reset
- **WHEN** 旧托管数据库与附件/产物目录完成清理并启动新版
- **THEN** 会话列表为空且可创建持久的新会话
- **AND** 外部源图片仍位于原路径
