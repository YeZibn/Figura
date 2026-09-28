## ADDED Requirements

### Requirement: Figura displays committed Panels as read-only Run output
Figura mode SHALL display committed Panels associated with their originating Runs using Panel names and image previews retrieved through the Figura client. The frontend SHALL load Panel image bytes on demand through the client API and SHALL NOT persist base64 image content, local paths, or tool-result payloads in browser storage. Panel presentation SHALL provide no manual region editing, semantic review, or measurement controls in this change. Existing ChartAgent and mock modes SHALL retain their current behavior.

#### Scenario: Display Panels created by a completed Run
- **WHEN** the user opens a Figura Session containing a Run that committed Panel outputs
- **THEN** the UI displays each Panel's name and image preview grouped under its originating Run

#### Scenario: Load a Panel preview on demand
- **WHEN** a Panel enters the visible UI region
- **THEN** the Figura client fetches its image through the Session-scoped Gateway route and renders the returned PNG without storing image bytes in Session metadata

#### Scenario: Session has no committed Panels
- **WHEN** the user opens a Session with no committed Panel outputs
- **THEN** the UI continues to show the existing Session conversation and attachment UI without a Panel section

#### Scenario: Keep other frontend modes unchanged
- **WHEN** the frontend runs in mock or ChartAgent mode
- **THEN** it does not call Figura Panel routes and preserves those modes' existing client behavior
