## MODIFIED Requirements

### Requirement: Projected messages preserve the complete committed conversation
Figura SHALL project each earlier Run input as one user message containing its persisted text and ordered attachment references, each committed model response as one assistant message, and every committed tool result as a tool message associated with its original call ID. Tool calls SHALL retain their provider order and arguments. A final-answer fact that references an existing response SHALL NOT create a duplicate message. Session history SHALL include all committed interactions and SHALL NOT summarize, clip, or omit a complete interaction. The neutral Session history SHALL NOT contain provider-private continuation payloads. Provider request assembly MAY resolve a continuation from its exact source Run and response, but SHALL associate it only with that assistant response and SHALL preserve the continuation unchanged when the selected Provider and format are compatible.

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

#### Scenario: Keep continuation out of neutral Session history
- **WHEN** a prior Run has provider-private continuation attached to one of its responses
- **THEN** the later Run's projected Session history contains the normalized assistant response and tool facts but no continuation payload

#### Scenario: Replay compatible source continuation in a later Provider request
- **WHEN** a later Run's Provider request includes an assistant response from an earlier Run and that response has a continuation compatible with the selected Provider and format
- **THEN** the Provider request includes the exact continuation associated with that source Run and response without changing the neutral Session history or assistant message content

#### Scenario: Reject a historical response without required compatible continuation
- **WHEN** the selected Provider requires continuation for a historical assistant response but its exact source Run and response has no continuation compatible with that Provider and format
- **THEN** Figura fails request preparation before claiming a Provider attempt and does not fabricate continuation, omit history, or dispatch a Provider request
