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
Figura SHALL project each earlier Run input as one user message containing its persisted text and ordered attachment references, each committed model response as one assistant message, and every committed tool result as a tool message associated with its original call ID. Tool calls SHALL retain their provider order and arguments. A final-answer fact that references an existing response SHALL NOT create a duplicate message. Session history SHALL include all committed interactions and SHALL NOT summarize, clip, or omit a complete interaction.

#### Scenario: Preserve user text and attachment order
- **WHEN** an earlier Run input contains text and multiple attachment IDs
- **THEN** its projected user message retains the text followed by those attachment references in the exact persisted order

#### Scenario: Preserve a completed tool round
- **WHEN** an earlier Run contains a committed assistant response with multiple tool calls and a matching committed result for every call
- **THEN** the projected assistant message preserves provider call order and each corresponding tool message follows with the matching opaque call ID

#### Scenario: Do not duplicate a final answer
- **WHEN** an earlier Run has a final-answer fact referencing a committed model response
- **THEN** the response appears once in history and the final-answer reference adds no message

#### Scenario: Reject an incomplete historical tool batch
- **WHEN** an earlier Run contains a tool call or started tool attempt without exactly one committed result for that call
- **THEN** Figura fails closed without fabricating a result or omitting the incomplete interaction from an otherwise dispatchable history

#### Scenario: Keep provider continuation within its source Run
- **WHEN** a prior Run has provider-private continuation attached to one of its responses
- **THEN** the later Run's Session history includes the normalized assistant response and tool facts but does not carry that continuation payload across the Run boundary

### Requirement: Session history remains complete and private to its owning Session
Figura SHALL retain the complete projected history in memory for request construction and SHALL rely on the Provider boundary's existing hard limits rather than a Memory retention, token, or summarization budget. It SHALL preserve Session ownership for every Run and attachment reference and SHALL expose no continuation payload or local attachment path through the projection's public surface.

#### Scenario: Preserve full history beyond a Provider request limit
- **WHEN** complete Session history exceeds a Provider message, image, text, or schema limit
- **THEN** the projection remains complete and request construction fails before Provider-attempt claim without pruning, summarizing, or dispatching the history

#### Scenario: Reject a cross-Session attachment reference
- **WHEN** an attachment referenced by a historical Run does not belong to the owning Session or cannot be resolved
- **THEN** Figura fails closed without returning image bytes or dispatching a Provider request
