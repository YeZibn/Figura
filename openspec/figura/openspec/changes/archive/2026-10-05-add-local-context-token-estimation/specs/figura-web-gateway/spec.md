## ADDED Requirements

### Requirement: Run reads expose the latest logical request context estimate
Figura SHALL add optional `contextUsage` to Run summaries returned by Session and Run-history reads. When the latest durable logical request has an estimate, the value SHALL contain only `inputTokens` and nullable `contextWindowTokens`; its Provider/model identity SHALL be the enclosing Run identity. When no binding exists or the latest binding has no estimate, the field SHALL be absent or null without falling back to an older request. Reads SHALL not rebuild requests, load images, initialize tokenizers or dispatch models. Existing progress and history reconciliation SHALL make a newly committed estimate observable without a separate polling service or token event stream.

#### Scenario: Read a failed request estimate
- **WHEN** a logical request was durably bound with an estimate and its network attempt failed
- **THEN** Run-history reads still return that request estimate

#### Scenario: Latest request has no estimate
- **WHEN** an earlier logical request has an estimate but the latest binding does not
- **THEN** the Run summary exposes no current estimate rather than displaying the earlier value as current

#### Scenario: Refresh after restart
- **WHEN** a client reloads a Session after Gateway restart
- **THEN** it receives the stored latest request estimate without recomputing historical payloads

#### Scenario: Protect private request content
- **WHEN** estimation counted private continuation and image-bearing messages
- **THEN** the public summary discloses aggregate counts only and no private content, images, local paths or binding fingerprint
