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
Figura SHALL reconstruct complete canonical history from durable Run facts, including each earlier Run input, committed assistant response, committed structured tool result and ordered attachment descriptions, and validated abnormal-tail context in deterministic order. Each tool message SHALL preserve its Run, tool sequence, exact tool_call_id, outcome and mutually exclusive business result/error; it SHALL NOT hold a second authoritative serialized observation or image bytes. Plain user messages SHALL remain user inputs rather than synthetic tool-image observations.

Request assembly may replace eligible older closed interactions with source-linked summaries and retain a recent raw tail, but SHALL preserve the current input, required current prefix, complete tool-call/result batches, unconsumed visual batches, and continuation compatibility. A summary SHALL NOT alter, delete or replace canonical facts; full history and attachment references SHALL remain available to authorized retrieval. Final-answer references SHALL NOT duplicate messages. Neutral history SHALL contain neither Provider-private continuation nor image bytes. Compatible continuation may be resolved only from its exact originating Run and response and SHALL be replayed unchanged.

#### Scenario: Preserve user text and attachment order
- **WHEN** an earlier Run input contains text and multiple attachment IDs
- **THEN** canonical history and any raw request projection retain the text followed by those attachment references in the exact persisted order

#### Scenario: Preserve a completed tool round
- **WHEN** an earlier Run contains a committed assistant response with multiple tool calls and a matching committed result for every call
- **THEN** canonical history retains provider call order and each corresponding tool message follows with the matching opaque call ID, while request compaction handles the round only as a complete unit

#### Scenario: Do not duplicate a final answer
- **WHEN** an earlier Run has a final-answer fact referencing a committed model response
- **THEN** the response appears once in canonical history and the final-answer reference adds no message

#### Scenario: Keep continuation out of neutral Session history
- **WHEN** a prior Run has provider-private continuation attached to a response retained in role history
- **THEN** canonical history contains the normalized assistant response and tool facts but no continuation payload

#### Scenario: Replay compatible source continuation in a later Provider request
- **WHEN** a later Run's Provider request includes an assistant response from an earlier Run and that response has a continuation compatible with the selected Provider and format
- **THEN** the Provider request includes the exact continuation associated with that source Run and response without changing the neutral Session history or assistant message content

#### Scenario: Reject a historical response without required compatible continuation
- **WHEN** the selected Provider requires continuation for a historical assistant response but its exact source Run and response has no continuation compatible with that Provider and format
- **THEN** Figura fails request preparation before claiming a Provider attempt and does not fabricate continuation, omit history, or dispatch a Provider request

#### Scenario: Preserve an abnormal incomplete tail
- **WHEN** an earlier failed or interrupted Run has a validated incomplete final tool batch
- **THEN** canonical history retains that entire source-linked outcome context, and request compaction neither fabricates a result nor splits its call identities and classifications

#### Scenario: Reject an incomplete completed Run or corrupt history
- **WHEN** a completed Run has a missing result or any prior Run contains duplicate results, invalid ownership, broken ordering, or mismatched identities
- **THEN** Figura fails closed instead of treating corruption as a recoverable incomplete tail

#### Scenario: Read a structured tool observation with image references
- **WHEN** a committed tool result contains ordered image attachment descriptions
- **THEN** canonical history retains that data and order without opening files, generating hint text, or duplicating the business JSON as authoritative text

#### Scenario: Separate omitted image bytes from missing resources
- **WHEN** a later request omits pixels from an earlier visual result
- **THEN** the canonical tool observation and attachment references remain unchanged and the request projection explicitly marks images as not loaded
### Requirement: Session history remains complete and private to its owning Session
Figura SHALL retain complete canonical history and source-linked outcome facts for their owning Session without a Memory retention or cumulative token budget. When a valid selected Provider/model context capacity and a request estimate are available, request assembly MAY create and persist a derived source-linked compaction summary at the agreed occupancy threshold; this summary SHALL NOT become a second authoritative message history. When capacity or estimate is unknown, Figura SHALL NOT automatically summarize or prune history. Existing execution-payload protections and genuine selected-Provider protocol restrictions remain in force. Every Run, message, tool result, attachment, and summary source reference SHALL remain scoped to its owning Session. The public projection SHALL expose no provider-private continuation payload or local attachment path.

#### Scenario: Keep canonical history after compaction
- **WHEN** request assembly compacts older interactions
- **THEN** every original committed message and tool fact remains available from its canonical Run source for later retrieval

#### Scenario: Reuse a source-linked summary
- **WHEN** a valid summary covers an earlier Session-history prefix
- **THEN** later request assembly may use that summary with its source references and the eligible raw recent tail

#### Scenario: Leave history uncompressed when capacity is unknown
- **WHEN** the selected model has no valid context capacity or a request estimate is unavailable
- **THEN** Figura sends the existing uncompressed projection and does not invent a threshold decision

#### Scenario: Preserve existing payload and Provider failure behavior
- **WHEN** the uncompressed or compacted request violates an existing payload guard or genuine Provider protocol restriction
- **THEN** Figura fails request preparation before claiming an ordinary Provider attempt without silently pruning canonical history

#### Scenario: Reject a cross-Session reference
- **WHEN** a summary or retrieved reference points to a Run or attachment outside its owning Session
- **THEN** Figura rejects the reference and returns no cross-Session content

### Requirement: Abnormal terminal Runs have deterministic source-linked outcome context
Figura SHALL derive canonical outcome context for each earlier failed or interrupted Run from its validated durable facts without writing a second authoritative history or invoking a model. It SHALL identify the source Run, ordinal and safe terminal reason. An incomplete tail SHALL preserve source response text as untrusted intent data and classify each call as committed success, committed failure, not started, or outcome unknown. Every committed observation SHALL retain its source result reference and the existing complete normalized observation format. Calls without results SHALL contain no invented observation. Context SHALL contain no private continuation or automatically loaded image bytes. A request summary MAY condense older outcome wording only while retaining source references and these classifications; the complete canonical outcome remains readable by reference.

#### Scenario: Preserve a partly completed batch
- **WHEN** OCR has a committed success, measurement has a started attempt without a result, and rendering has no attempt in an interrupted Run
- **THEN** canonical context retains the OCR observation, marks measurement outcome unknown and rendering not started, and retains all three call identities in provider order

#### Scenario: Keep a known failure as an actual observation
- **WHEN** a call in an incomplete terminal batch has a committed failed result
- **THEN** canonical context preserves that failure observation and does not reclassify it as unknown

#### Scenario: Explain a failure before a response
- **WHEN** an earlier Run failed before committing any model response
- **THEN** canonical history retains its user input and safe outcome context without inventing an assistant response

#### Scenario: Retrieve complete outcome facts after compaction
- **WHEN** a compacted request refers to an abnormal Run outcome
- **THEN** the source reference resolves to the complete validated outcome context and all committed observations without rerunning tools
