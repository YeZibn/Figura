## ADDED Requirements

### Requirement: Streamed continuation is committed only with its complete response
Figura SHALL assemble Provider continuation fragments according to the selected Provider contract and persist the resulting continuation only with the complete normalized response that produced it. Interrupted or invalid streams SHALL create no continuation fact. Continuation content SHALL remain private and SHALL NOT be included in transient Gateway deltas, public attempt diagnostics, or user-visible assistant text.

#### Scenario: Persist continuation after a terminal event
- **WHEN** a valid terminal stream contains continuation data accepted by the Provider contract
- **THEN** Figura atomically links the assembled continuation to that committed model response

#### Scenario: Do not persist continuation from an interrupted stream
- **WHEN** a stream ends before a valid terminal event after emitting continuation fragments
- **THEN** Figura persists no continuation fact from that attempt
