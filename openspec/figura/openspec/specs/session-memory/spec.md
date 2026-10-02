# session-memory Specification

## Purpose

Provides a complete, ordered conversation projection across Runs in one Session so later model requests can continue the same conversation from Figura's durable execution facts.

## Requirements

### Requirement: Session history is reconstructed from earlier Runs in the same Session
For a target Run, Figura SHALL derive Session history only from durable facts belonging to Runs with a lower ordinal in the target Run's Session. It SHALL order Runs by ascending ordinal and facts within a Run by their committed record and tool-fact order. The projection SHALL be read-only and SHALL NOT create a second persisted copy of message history.

#### Scenario: Reconstruct earlier Runs in ordinal order
- **WHEN** a Session contains multiple earlier terminal Runs and a target Run with a greater ordinal
- **THEN** the projected history contains those earlier Runs in ascending ordinal order, regardless of their timestamps or database row order

#### Scenario: Exclude other Sessions and later Runs
- **WHEN** the database contains Runs from another Session or with an ordinal greater than the target Run
- **THEN** neither Run contributes messages to the target Run's Session history

#### Scenario: Reconstruct history when no earlier Run exists
- **WHEN** the target Run is the first Run in its Session
- **THEN** the projected Session history is empty and the Agent uses the target Run's own input as the first user message

#### Scenario: Read history without duplicating durable messages
- **WHEN** Figura reconstructs Session history
- **THEN** it reads existing Run facts and writes no message, history, summary, or memory record

#### Scenario: Encounter a nonterminal earlier Run
- **WHEN** an earlier Run in the target Session is still running
- **THEN** Figura does not produce a dispatchable Session history from a changing prefix and fails closed before a Provider attempt is claimed

### Requirement: Projected messages preserve the complete committed conversation
Figura SHALL project each earlier Run input as one user message containing its persisted text and ordered attachment references, each committed response in a closed interaction as one assistant message, and every committed tool result in that interaction as a tool message associated with its original call ID. A validated incomplete trailing batch in an earlier failed or interrupted Run SHALL instead contribute an explicit source-linked outcome context, preserving its original assistant text, ordered calls, and every already committed observation without sending a partial native assistant/tool batch. Tool calls retained in native role history SHALL retain their provider order and arguments; converted tails SHALL retain call order and identities while original arguments remain in their durable facts. A final-answer fact that references an existing response SHALL NOT create a duplicate message. Session history SHALL include all committed interactions and SHALL NOT summarize, clip, or omit a complete interaction. The neutral Session history SHALL NOT contain provider-private continuation payloads. Provider request assembly MAY resolve a continuation from its exact source Run and response, but SHALL associate it only with that assistant response and SHALL preserve the continuation unchanged when the selected Provider and format are compatible.

#### Scenario: Preserve user text and attachment order
- **WHEN** an earlier Run input contains text and multiple attachment IDs
- **THEN** its projected user message retains the text followed by those attachment references in the exact persisted order

#### Scenario: Preserve a completed tool round
- **WHEN** an earlier Run contains a committed assistant response with multiple tool calls and a matching committed result for every call
- **THEN** the projected assistant message preserves provider call order and each corresponding tool message follows with the matching opaque call ID

#### Scenario: Do not duplicate a final answer
- **WHEN** an earlier Run has a final-answer fact referencing a committed model response
- **THEN** the response appears once in history and the final-answer reference adds no message

#### Scenario: Keep continuation out of neutral Session history
- **WHEN** a prior Run has provider-private continuation attached to a response retained in role history
- **THEN** the later Run's projected Session history contains the normalized assistant response and tool facts but no continuation payload

#### Scenario: Replay compatible source continuation in a later Provider request
- **WHEN** a later Run's Provider request includes an assistant response from an earlier Run and that response has a continuation compatible with the selected Provider and format
- **THEN** the Provider request includes the exact continuation associated with that source Run and response without changing the neutral Session history or assistant message content

#### Scenario: Reject a historical response without required compatible continuation
- **WHEN** the selected Provider requires continuation for a historical assistant response but its exact source Run and response has no continuation compatible with that Provider and format
- **THEN** Figura fails request preparation before claiming a Provider attempt and does not fabricate continuation, omit history, or dispatch a Provider request

#### Scenario: Project a legal incomplete historical tail
- **WHEN** an earlier failed or interrupted Run has a validated incomplete final tool batch
- **THEN** Figura preserves all closed interactions, represents that entire trailing batch in source-linked outcome context, and fabricates no tool result

#### Scenario: Reject an incomplete completed Run or corrupt history
- **WHEN** a completed Run has a missing result or any prior Run contains duplicate results, invalid ownership, broken ordering, or mismatched identities
- **THEN** Figura fails closed instead of treating corruption as a recoverable incomplete tail

### Requirement: Session history remains complete and private to its owning Session
Figura SHALL retain the complete projected history and source-linked outcome contexts in memory for request construction and SHALL rely on the Provider boundary's existing hard limits rather than a Memory retention, token, or summarization budget. It SHALL preserve Session ownership for every Run and attachment reference and SHALL expose no continuation payload or local attachment path through the projection's public surface.

#### Scenario: Preserve full history beyond a Provider request limit
- **WHEN** complete Session history exceeds a Provider message, image, text, or schema limit
- **THEN** the projection remains complete and request construction fails before Provider-attempt claim without pruning, summarizing, or dispatching the history

#### Scenario: Reject a cross-Session attachment reference
- **WHEN** an attachment referenced by a historical Run does not belong to the owning Session or cannot be resolved
- **THEN** Figura fails closed without returning image bytes or dispatching a Provider request

### Requirement: Abnormal terminal Runs have deterministic source-linked outcome context
Figura SHALL derive outcome context for each earlier failed or interrupted Run from its validated durable facts without writing a second history or invoking a model. It SHALL identify the source Run, ordinal and safe terminal reason. An incomplete tail SHALL preserve source response text as untrusted intent data and classify each call as committed success, committed failure, not started, or outcome unknown. Every committed observation SHALL retain its source result reference and the existing complete normalized observation format. Calls without results SHALL contain no invented observation. Context SHALL contain no private continuation or automatically loaded image bytes.

#### Scenario: Preserve a partly completed batch
- **WHEN** OCR has a committed success, measurement has a started attempt without a result, and rendering has no attempt in an interrupted Run
- **THEN** context retains the OCR observation, marks measurement outcome unknown and rendering not started, and retains all three call identities in provider order

#### Scenario: Keep a known failure as an actual observation
- **WHEN** a call in an incomplete terminal batch has a committed failed result
- **THEN** context preserves that failure observation and does not reclassify it as unknown

#### Scenario: Explain a failure before a response
- **WHEN** an earlier Run failed before committing any model response
- **THEN** history retains its user input and a safe outcome context without inventing an assistant response

#### Scenario: Preserve source data without trimming
- **WHEN** outcome context makes a subsequent request exceed a Provider hard limit
- **THEN** preparation fails before attempt claim without dropping committed observations or summarizing the tail
