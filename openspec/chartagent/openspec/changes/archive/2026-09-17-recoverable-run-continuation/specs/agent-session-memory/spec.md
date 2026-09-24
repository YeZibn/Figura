## ADDED Requirements

### Requirement: Recovery context is explicit and separate from normal conversation history

The memory layer SHALL persist the bounded context needed for an explicit
continuation without treating an interrupted or uncertain run as a completed
conversation turn. Normal new Agent turns SHALL continue to use only completed
runs for ordinary historical context, while a validated resume may read the
parent run's safe checkpoint and committed records. Recovery context SHALL
retain authorized references instead of binary or sensitive content.

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
