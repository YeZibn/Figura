## ADDED Requirements

### Requirement: Generated chart preview references follow candidate publication

Generated chart lifecycle events SHALL expose enough bounded identity and
status information for a client to resolve both an unpublished candidate and
its later published artifact. When a candidate is promoted, subsequent
historical or live representations SHALL provide a current artifact reference
or a stable preview resolution that does not depend on a stale candidate URL.

#### Scenario: Pending candidate has a preview resource

- **WHEN** a generated chart candidate is persisted for review
- **THEN** its event contains the candidate identity and the client can request
  the candidate image for an authorized owning run while it remains available

#### Scenario: Published artifact replaces a candidate

- **WHEN** a review promotes a candidate to a published or warning publication
  state
- **THEN** the resulting event and later history expose the published artifact
  identity and preview resource, and the client does not continue relying only
  on the old candidate resource

#### Scenario: Historical lifecycle can resolve the current image

- **WHEN** the client reloads a run after candidate publication or receives a
  lifecycle event out of order
- **THEN** it can resolve the current preview using the available bounded
  reference and displays an explicit pending or unavailable state when no
  current bytes can be served
