## MODIFIED Requirements

### Requirement: Provider responses have a normalized shape
Figura SHALL send every Provider request through the streaming response contract. Each configured Provider/model pair SHALL explicitly declare streaming support; a Provider without that capability SHALL be rejected before network dispatch. Figura SHALL assemble a successful terminal stream into one normalized response containing assistant content, ordered complete tool calls, finish reason, bounded usage metadata when provided, and private continuation data when provided. A response SHALL be accepted only after a valid terminal event. Figura SHALL NOT retain an unrestricted SDK response or partial stream as a persistence contract, and SHALL NOT use a non-streaming fallback.

#### Scenario: Normalize a complete assistant stream
- **WHEN** a supported Provider emits assistant content and a valid terminal event
- **THEN** Figura returns one normalized response with ordered content, finish reason, and available bounded usage metadata

#### Scenario: Assemble fragmented tool calls
- **WHEN** a supported Provider emits tool-call IDs, names, and JSON arguments across multiple stream events
- **THEN** Figura assembles them by Provider call index, preserves call order, and returns only complete tool calls in the normalized response

#### Scenario: Reject a Provider without streaming capability
- **WHEN** a selected Provider/model pair does not declare support for the streaming contract
- **THEN** Figura rejects the request before network dispatch and does not fall back to a non-streaming request

#### Scenario: Reject an incomplete stream
- **WHEN** the transport closes or the stream ends without a valid terminal event
- **THEN** Figura returns a bounded incomplete-stream failure and does not expose a normalized response

#### Scenario: Keep Provider-private continuation data separate
- **WHEN** a complete stream includes Provider-private continuation data
- **THEN** Figura returns it only in the private continuation field and excludes it from assistant text and public stream events
