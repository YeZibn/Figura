## ADDED Requirements

### Requirement: Execution checkpoints and continuation lineage are inspectable

The execution trace SHALL expose bounded checkpoint state and work-unit
completion information for runs that may be continued. A continuation SHALL
retain its parent run identifier and relation kind while using its own event
sequence. The trace SHALL keep the parent terminal state immutable and SHALL
make recovery-blocked or uncertain operations distinguishable from completed
work.

#### Scenario: Checkpoint is visible without exposing execution internals

- **WHEN** a run reaches a committed recovery boundary
- **THEN** its summary or trace exposes the checkpoint phase, next-action
  category, and recovery availability
- **AND** it does not expose secrets, raw provider responses, or binary content

#### Scenario: Resume lineage is preserved

- **WHEN** a resume creates a child run
- **THEN** the child trace identifies the parent and the `resume` relation
- **AND** the child events remain ordered independently from the parent's
  terminal event stream

#### Scenario: Uncertain operation is not shown as completed

- **WHEN** a run stops with an operation whose result cannot be confirmed
- **THEN** the trace records the bounded uncertain or recovery-blocked state
- **AND** it does not render that operation as a successful completed step
