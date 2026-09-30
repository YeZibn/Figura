## ADDED Requirements

### Requirement: Figura displays committed chart renders as read-only Run output
Figura mode SHALL display committed successful chart-render previews grouped under their originating Runs, using the Figure title and PNG dimensions from safe render metadata. The frontend SHALL request PNG bytes on demand through the Figura client API and SHALL NOT persist base64 image content, local paths, or raw tool results in browser storage. Chart previews SHALL be read-only and SHALL NOT add editing, review, publication, retry, or render-configuration controls. Existing ChartAgent and mock modes SHALL retain their current behavior.

#### Scenario: Display committed chart renders
- **WHEN** the user opens a Figura Session containing Runs with committed chart renders
- **THEN** each preview is grouped under the Run that created it and labeled with the referenced Figure title

#### Scenario: Load a preview on demand
- **WHEN** a committed chart preview enters the visible UI region
- **THEN** the Figura client loads its PNG through the Session-scoped Gateway content route without storing the bytes in Session metadata or browser storage

#### Scenario: Session has no committed chart renders
- **WHEN** the user opens a Figura Session with no committed successful chart renders
- **THEN** the workspace displays the existing conversation and any other supported Run output without an empty chart-preview section

#### Scenario: Preserve non-Figura frontend modes
- **WHEN** the frontend runs in mock or ChartAgent mode
- **THEN** it does not call Figura chart-render routes and preserves those modes' existing behavior
