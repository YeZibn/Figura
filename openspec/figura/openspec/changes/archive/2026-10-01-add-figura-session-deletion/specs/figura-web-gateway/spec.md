## ADDED Requirements

### Requirement: Session deletion removes the owning Session as one bounded operation
The Gateway SHALL provide `DELETE /sessions/{sessionId}`. A successful deletion SHALL return `204` and make the Session, its Runs and execution facts, its attachment and Panel resources, and its ChartFigure render images unavailable through Figura APIs. The operation SHALL affect only the addressed Session. The Gateway SHALL reject an unknown Session with a bounded `404` response and SHALL reject deletion while any Run in the Session is `running` with a bounded `409` response. A rejected or failed deletion SHALL NOT be reported as successful. The operation SHALL follow the existing local-Origin and safe-error boundary.

#### Scenario: Delete a terminal Session
- **WHEN** the browser deletes an existing Session whose Runs are all terminal
- **THEN** the Gateway returns `204` and subsequent Session, Run, attachment, Panel, timeline, and chart-render reads cannot retrieve its data

#### Scenario: Preserve another Session during deletion
- **WHEN** the browser deletes one terminal Session while another Session has data
- **THEN** only resources owned by the addressed Session are removed and the other Session remains readable

#### Scenario: Reject deletion while a Run is running
- **WHEN** the browser deletes a Session containing a `running` Run
- **THEN** the Gateway returns a bounded `409` response and leaves the Session and all of its resources available

#### Scenario: Reject an unknown Session
- **WHEN** the browser deletes an unknown Session ID
- **THEN** the Gateway returns a bounded `404` response without disclosing other Session data

#### Scenario: Recover from a failed deletion
- **WHEN** persistent deletion cannot commit
- **THEN** the Gateway returns a bounded failure and the Session remains readable with its associated data intact
