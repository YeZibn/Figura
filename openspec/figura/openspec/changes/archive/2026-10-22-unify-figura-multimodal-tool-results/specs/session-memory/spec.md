## MODIFIED Requirements

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
