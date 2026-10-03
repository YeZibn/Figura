## Purpose

Defines a shared physical JSON payload protection contract across Figura execution boundaries, keeping protocol correctness and memory protection distinct from normal task size or cumulative Run quotas.

## ADDED Requirements

### Requirement: Execution JSON uses one configurable complete-payload guard
Figura SHALL protect new execution JSON payloads with one deployment-configurable UTF-8 encoded size limit, defaulting to 32 MiB, and a maximum actual JSON container depth of 64 with the root at zero. It SHALL apply the same contract to complete Run input, registered model-visible tool surface, tool observation, complete model-response transition, continuation envelope, durable execution fact and structured Provider request. A transition SHALL include all its calls and continuation for admission and SHALL be rejected atomically if oversized. The guard SHALL NOT accumulate bytes across a Run or Session, clip content, or impose independent generic message, instruction, tool, call, property or enum counts. Schema-declared domain constraints and proven vendor protocol requirements SHALL remain enforced.

#### Scenario: Accept an observation above the old limit
- **WHEN** a valid tool observation exceeds 256 KiB but its complete envelope is within the shared guard and registered Schema
- **THEN** Figura accepts it without applying the deleted result-size micro limit

#### Scenario: Reject a combined oversized response
- **WHEN** each call is individually small but a full response, its calls and continuation exceed the shared limit together
- **THEN** Figura rejects the entire transition without partial response or call facts

#### Scenario: Keep task size separate from payload size
- **WHEN** a Run accumulates many individually valid committed execution facts
- **THEN** Figura does not reject the next fact because of the cumulative bytes, tools, attempts, tokens or elapsed Run time

### Requirement: JSON admission preserves strict semantics and opaque associations
Figura SHALL reject duplicate keys, non-finite numbers, unsupported JSON values, invalid Unicode, malformed structure and excess depth before trusted invocation or commit. It SHALL preserve Schema validation and exact opaque tool-call/result identity, nonempty valid UTF-8 IDs, Run ownership, uniqueness and call order. It SHALL NOT impose an arbitrary independent call-ID length limit or truncate identity values. Encoding and byte accounting SHALL use stable compact UTF-8 JSON, while list order and exact original argument strings remain intact.

#### Scenario: Preserve a long valid call ID
- **WHEN** a Provider returns a valid call ID longer than 256 bytes within a valid complete payload
- **THEN** Figura preserves the full ID through intent, result and history association without truncation or a duplicate character-based limit

#### Scenario: Reject invalid JSON without effects
- **WHEN** arguments contain duplicate keys or non-finite constants
- **THEN** validation rejects them without invoking a handler or weakening its Schema

### Requirement: Images and public projections keep their own protection boundaries
Provider structured-request JSON accounting SHALL represent images by ordered media type, byte count and content digest rather than counting base64 bytes twice. Actual image content SHALL still satisfy existing source authorization, format, individual byte, aggregate byte and decode protections; genuine vendor image limits SHALL be checked by that Provider. Figura SHALL NOT enforce a generic sixteen-image or sixteen-attachment-reference count. Public lifecycle events and display summaries SHALL retain bounded allowlisted privacy contracts and SHALL NOT publish unrestricted execution payloads because the private limit increased.

#### Scenario: Send more than sixteen small images
- **WHEN** seventeen authorized images satisfy the existing image byte/decode protections and selected Provider's actual supported contract
- **THEN** Figura does not reject them solely because of a generic image count of sixteen

#### Scenario: Reject image bytes independently
- **WHEN** images exceed the existing aggregate raw image byte guard
- **THEN** Figura rejects the request before claim even if its structured JSON portion is small

#### Scenario: Protect public events
- **WHEN** a large private response or tool result commits
- **THEN** its event retains only allowlisted progress/lifecycle fields within the existing 16 KiB event protection

### Requirement: Guard changes preserve supported committed history
Supported older payload versions SHALL remain readable with unchanged facts and ownership semantics. Lowering a deployment admission limit SHALL affect new writes without making previously accepted facts unreadable. Migration SHALL remove conflicting old private payload ceilings atomically while preserving referential integrity, immutable facts, Session aggregate deletion and rollback. Untrusted network JSON SHALL be read with a bound before unrestricted parsing or allocation, not protected only after the full response has been materialized.

#### Scenario: Lower an admission limit
- **WHEN** a deployment lowers its new-write limit after accepting a larger valid payload
- **THEN** the existing payload remains readable and future oversized admissions are rejected

#### Scenario: Fail migration
- **WHEN** the migration transaction fails
- **THEN** the old schema version and all committed facts remain unchanged

#### Scenario: Reject a large network body early
- **WHEN** an incoming execution JSON body exceeds the applicable physical guard
- **THEN** reception or bounded parsing rejects it without retaining an unrestricted raw payload
