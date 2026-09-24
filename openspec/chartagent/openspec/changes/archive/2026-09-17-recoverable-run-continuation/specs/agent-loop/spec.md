## ADDED Requirements

### Requirement: Agent resumes from a committed execution checkpoint

The Agent SHALL be able to start a continuation from a validated checkpoint
that contains bounded conversation context, completed tool results, visual
evidence references, layout context, and review/publication references. It SHALL
continue from the checkpoint's next action, reuse completed operations, and
preserve the existing interruption and terminal rules. It SHALL return a
bounded recovery-blocked outcome rather than automatically replaying an
uncertain provider, tool, rendering, review, or publication operation.

#### Scenario: Continuation starts after a completed tool result

- **WHEN** an explicit resume provides a checkpoint after a committed tool
  result
- **THEN** the Agent reconstructs the safe model context and begins at the
  checkpoint's next action
- **AND** the prior tool call is not dispatched again

#### Scenario: Layout and chart evidence survive continuation

- **WHEN** a checkpoint contains authorized layout, visual, candidate, or
  publication references
- **THEN** the resumed Agent can use those references in later chart reasoning
- **AND** it does not require the original process-local state to be present

#### Scenario: Uncertain operation stops automatic continuation

- **WHEN** the checkpoint identifies a provider or tool operation whose result
  is uncertain and no replay-safe contract exists
- **THEN** the Agent does not dispatch that operation automatically
- **AND** the caller receives a bounded recovery-blocked result that can be
  followed by an explicit retry
