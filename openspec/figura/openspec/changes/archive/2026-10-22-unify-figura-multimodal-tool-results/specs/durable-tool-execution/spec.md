## MODIFIED Requirements

### Requirement: Tool outcomes and checkpoint progress commit atomically
Figura SHALL persist every known success or failure as one bounded tool-execution fact associated with the exact call and attempt. Successful facts SHALL contain the business JSON object and ordered validated attachment descriptions; failed facts SHALL contain the safe error, null result, and an empty attachment array. The complete observation and encoded fact SHALL satisfy the shared execution-payload contract without independent 256/512 KiB ceilings.

Required media SHALL be installed and validated before publishing the result. Appending the result with all its attachment descriptions, advancing the tool-fact sequence and checkpoint, and issuing existing safe progress notification SHALL be one database transaction. Files without a committed result SHALL NOT become visible resources. A file/database failure SHALL NOT publish partial attachment metadata or advance the checkpoint. Previously committed results and descriptors SHALL be returned from durable state without invoking the handler or reconstructing images again. Unknown business effects SHALL retain the existing declared-effect recovery behavior.

#### Scenario: Commit a successful tool result
- **WHEN** the current attempt returns a successful bounded object result and the expected revision is current
- **THEN** Figura appends the result fact and advances the checkpoint to the next call or, after the batch, to a model action in the same transaction

#### Scenario: Commit a failed tool result
- **WHEN** the current attempt returns a bounded structured failure
- **THEN** Figura persists the failure against the same call ID and attempt ID and advances progress atomically without retrying the handler

#### Scenario: Repeat a result commit
- **WHEN** a caller tries to commit another result for an attempt that already has a committed result
- **THEN** Figura rejects the duplicate transition and retains the original result and checkpoint

#### Scenario: Stop after image installation before result commit
- **WHEN** a process stops after installing a candidate image but before its result transaction commits
- **THEN** no public or Agent resource is published, the existing checkpoint still identifies unresolved work, and eligible recovery cannot mix a recomputed business result with an older uncommitted image

#### Scenario: Recover a committed multimodal result
- **WHEN** a committed result and its matching image files already exist when execution resumes
- **THEN** the existing result and attachment descriptors are reused without duplicate handler execution or new result facts
