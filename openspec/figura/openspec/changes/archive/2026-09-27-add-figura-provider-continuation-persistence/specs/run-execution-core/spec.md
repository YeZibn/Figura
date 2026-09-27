## MODIFIED Requirements

### Requirement: Execution facts and checkpoints advance together
Figura SHALL expose an internal commit boundary that appends only supported, bounded, versioned execution facts and advances the same Run's checkpoint atomically. Core record sequences and tool-execution fact sequences SHALL each be unique and increasing within a Run. A commit SHALL reject a stale expected checkpoint, an invalid record reference, an unsupported payload kind or version, or a terminal Run without partially advancing records, tool facts, checkpoint, or events. Core records SHALL support input, model responses, and final answers; a separate ordered tool-execution fact stream SHALL support tool-call intents, tool-attempt starts, and tool results. A model response SHALL be accepted only if any provider-private continuation it contains is valid, provider-scoped, within the continuation resource bound, and durably linked to that exact response. The response, private continuation, associated tool-call facts, and checkpoint SHALL be committed atomically. The state validator SHALL allow repeated model-response/tool-execution rounds only when every prior tool batch is fully resolved before the next model response, and SHALL verify that every non-null continuation reference resolves to the matching Run, response, provider, and supported format. Completion SHALL require a final text response with no pending or unresolved tool attempt.

#### Scenario: Commit a text-only model response without continuation
- **WHEN** a caller submits a bounded normalized model response with no tool calls or private continuation against the current model checkpoint
- **THEN** Figura appends the response as the next fact, stores no continuation, and advances the checkpoint to a final-answer action in the same commit

#### Scenario: Commit a text-only model response with continuation
- **WHEN** a caller submits a bounded normalized text response with valid provider-private continuation against the current model checkpoint
- **THEN** Figura atomically appends the response and private continuation, links them, and advances the checkpoint to a final-answer action

#### Scenario: Commit a model response with tool calls
- **WHEN** a caller submits a bounded normalized response with ordered tool calls and an absent or valid provider-private continuation against the current model checkpoint
- **THEN** Figura atomically appends the response, its optional private continuation, its associated call intents, and advances both checkpoint cursors to the first tool action

#### Scenario: Commit against stale progress
- **WHEN** two callers attempt to commit against the same checkpoint version
- **THEN** at most one commit succeeds and the other leaves no partial fact, checkpoint, continuation, or event

#### Scenario: Reject an invalid or oversized continuation
- **WHEN** a response contains a provider-mismatched, unsupported, malformed, or oversized continuation, or its continuation reference does not resolve to the same Run and response
- **THEN** Figura rejects the whole response transition and retains the prior record prefix, tool-fact prefix, continuation set, and checkpoint

#### Scenario: Commit a later model response after a completed tool batch
- **WHEN** every tool call in the previous response has a committed result and the checkpoint points to a model action
- **THEN** Figura accepts the next model response and preserves the ordered history of prior model, continuation, and tool facts

#### Scenario: Attempt completion with unresolved tool work
- **WHEN** a caller attempts to finalize a Run while any tool call is pending or has an unresolved attempt
- **THEN** Figura rejects completion without appending a final-answer fact or changing the Run's terminal state
