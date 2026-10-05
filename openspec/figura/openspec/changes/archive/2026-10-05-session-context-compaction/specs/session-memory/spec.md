## MODIFIED Requirements

### Requirement: Projected messages preserve the complete committed conversation
Figura SHALL reconstruct complete canonical history from durable Run facts, including each earlier Run input, committed assistant response, committed tool result, and validated abnormal-tail outcome context in deterministic order. Request assembly MAY replace eligible older closed interactions with a source-linked summary and retain a recent raw-history tail; it SHALL preserve the current Run input, required current Run prefix, complete tool-call/result batches, and provider continuation compatibility. A summary SHALL reference canonical source facts and SHALL NOT alter, delete, or stand in for them. Full canonical history SHALL remain available to authorized retrieval. A final-answer fact that references an existing response SHALL NOT create a duplicate message. The neutral Session history SHALL NOT contain provider-private continuation payloads. Provider request assembly MAY resolve a continuation from its exact source Run and response, but SHALL associate it only with that assistant response and SHALL preserve the continuation unchanged when the selected Provider and format are compatible.

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
