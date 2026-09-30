## ADDED Requirements

### Requirement: Committed chart renders are readable through their owning Session
The Figura Web Gateway SHALL expose metadata only for committed successful chart renders and SHALL provide a read-only content endpoint addressed by the owning Session, render Run ID, and render tool-call ID. A render summary SHALL contain exactly `callId`, `figureRef` (`runId` and `callId`), `figureTitle`, `figureDigest`, `imageSha256`, `mediaType`, `byteCount`, `width`, and `height`. Summaries SHALL be grouped with their originating render Run in Session detail and Run history. Content reads SHALL verify that the Run belongs to the requested Session, that the referenced call has a committed successful `render_chart_figure` result, and that the stored PNG matches the committed metadata. Successful responses SHALL use `image/png`, `Cache-Control: no-store`, and `X-Content-Type-Options: nosniff`. The Gateway SHALL NOT expose image paths, bytes in JSON, tool arguments, raw tool results, or uncommitted render files.

#### Scenario: Read a Session's committed render summaries
- **WHEN** the browser reads a Session containing one or more committed successful chart renders
- **THEN** each render appears in its originating Run's safe `chartRenders` summary with the documented metadata only

#### Scenario: Read a committed render image
- **WHEN** the browser requests a committed render's content through its owning Session and Run
- **THEN** the Gateway returns the validated PNG bytes with a non-cacheable image response

#### Scenario: Reject a cross-Session or unknown render reference
- **WHEN** the browser requests a render through a Session that does not own its Run or tool call
- **THEN** the Gateway returns a bounded not-found response without disclosing metadata or bytes

#### Scenario: Hide uncommitted render files
- **WHEN** a render image was staged or installed but no successful result has committed
- **THEN** neither Session detail nor the content endpoint exposes that render

#### Scenario: Detect a missing or corrupted render image
- **WHEN** committed metadata refers to a missing, unsafe, invalid, or digest-mismatched PNG
- **THEN** the Gateway returns a bounded storage or integrity error and no image bytes
