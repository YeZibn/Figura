## MODIFIED Requirements

### Requirement: Execution facts and checkpoints advance together
Figura SHALL expose an internal commit boundary that appends only supported, bounded, versioned execution facts and advances the same Run's checkpoint atomically. Core record sequences and tool-execution fact sequences SHALL each be unique and increasing within a Run. A commit SHALL reject a stale expected checkpoint, an invalid record reference, an unsupported payload kind or version, or a terminal Run without partially advancing records, tool facts, checkpoint, or events. Core records SHALL support input, model responses, and final answers; a separate ordered tool-execution fact stream SHALL support tool-call intents, tool-attempt starts, and tool results. A response containing tool calls SHALL be accepted only when it has no provider-private continuation. The state validator SHALL allow repeated model-response/tool-execution rounds only when every prior tool batch is fully resolved before the next model response. Completion SHALL require a final text response with no pending or unresolved tool attempt.

#### Scenario: Commit a text-only model response
- **WHEN** a caller submits a bounded normalized model response with no tool calls or private continuation against the current model checkpoint
- **THEN** Figura appends the response as the next fact and advances the checkpoint to a final-answer action in the same commit

#### Scenario: Commit a model response with tool calls
- **WHEN** a caller submits a bounded normalized response with ordered tool calls and no private continuation against the current model checkpoint
- **THEN** Figura atomically appends the response to the core record stream, its associated call intents to the tool-execution fact stream, and advances both checkpoint cursors to the first tool action

#### Scenario: Commit against stale progress
- **WHEN** two callers attempt to commit against the same checkpoint version
- **THEN** at most one commit succeeds and the other leaves no partial fact, checkpoint, or event

#### Scenario: Response contains unsupported private continuation
- **WHEN** a model response includes provider-private continuation
- **THEN** Figura rejects the commit and retains the prior checkpoint and record prefix

#### Scenario: Commit a later model response after a completed tool batch
- **WHEN** every tool call in the previous response has a committed result and the checkpoint points to a model action
- **THEN** Figura accepts the next model response and preserves the ordered history of prior model and tool facts

#### Scenario: Attempt completion with unresolved tool work
- **WHEN** a caller attempts to finalize a Run while any tool call is pending or has an unresolved attempt
- **THEN** Figura rejects completion without appending a final-answer fact or changing the Run's terminal state
