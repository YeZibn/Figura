## ADDED Requirements

### Requirement: Session deletion removes owned Panel images and records
Figura SHALL remove every Panel record and private Panel PNG owned by a permanently deleted Session. Panel metadata and content reads for the deleted Session SHALL fail as not found. If the Session deletion transaction rolls back, staged Panel images SHALL be restored and remain readable.

#### Scenario: Remove a Session's Panels
- **WHEN** a Session with committed Panels is permanently deleted
- **THEN** its Panel metadata and PNG files are unavailable and Panels belonging to other Sessions remain readable

#### Scenario: Restore Panels after a failed Session deletion
- **WHEN** the Session deletion transaction fails after Panel files have been staged
- **THEN** Figura restores the staged Panel files and retains their metadata and readable content
