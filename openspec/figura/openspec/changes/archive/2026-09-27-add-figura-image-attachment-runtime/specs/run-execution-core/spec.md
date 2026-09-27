## MODIFIED Requirements

### Requirement: Run creation commits immutable input and initial progress atomically
Figura SHALL accept a bounded, nonempty text input, an optional ordered list of at most 16 unique attachment IDs, and an explicit allowlisted, locally configured provider/model pair. Every attachment ID SHALL identify a retained, validated image owned by the Run's Session. A successful creation SHALL atomically persist the Run, one immutable input record containing the text and ordered attachment IDs, an initial checkpoint pointing to the next model action, a creation idempotency mapping, and a bounded creation event. Provider network access SHALL NOT occur during this operation.

#### Scenario: Create a text-only Run
- **WHEN** a caller supplies valid text, an empty attachment list, an existing Session, an explicit available provider/model pair, and an idempotency key
- **THEN** Figura commits a `running` Run whose first record contains the requested values, whose Run row contains the resolved provider/model pair, and whose checkpoint points to a model action after record sequence 1

#### Scenario: Create a Run with authorized images
- **WHEN** a caller supplies valid text and an ordered list of distinct retained image IDs owned by the existing Session, an explicit available provider/model pair, and an idempotency key
- **THEN** Figura commits the ordered IDs in the immutable input record with the Run, checkpoint, idempotency mapping, and creation event in one transaction

#### Scenario: Reject unsupported input or provider selection
- **WHEN** a request has empty text, an invalid or unavailable attachment ID, a duplicate ID, more than 16 IDs, an unsupported or unavailable provider/model pair, or an unknown Session
- **THEN** Figura rejects creation before writing any Run, record, checkpoint, idempotency mapping, or event for that request

#### Scenario: Reject an attachment owned by another Session
- **WHEN** a request contains an attachment ID that belongs to a different Session
- **THEN** Figura rejects creation without disclosing the attachment's metadata and without writing any Run facts or events

### Requirement: Run creation is idempotent within its Session
Figura SHALL scope creation idempotency to the Session and a digest of the caller's key. Reusing a key with the same normalized text, ordered attachment IDs, and provider/model selection SHALL return the original Run; reusing it with different request content, attachment IDs, attachment order, or provider/model selection SHALL fail without creating another Run. Raw idempotency keys SHALL NOT be retained in durable facts or public events.

#### Scenario: Repeat the same create request
- **WHEN** a caller repeats a create request with the same Session, key, text, ordered attachment IDs, and provider/model selection
- **THEN** Figura returns the original Run and creates no new record or event

#### Scenario: Reuse a key for different input
- **WHEN** a caller reuses a Session-scoped key with changed text, attachment IDs or their order, or provider/model selection
- **THEN** Figura reports an idempotency conflict and leaves the existing Run unchanged
