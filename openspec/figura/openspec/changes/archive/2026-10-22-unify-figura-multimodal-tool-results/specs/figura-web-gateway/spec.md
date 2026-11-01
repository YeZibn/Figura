## MODIFIED Requirements

### Requirement: Committed tool interactions are readable as a bounded Run timeline
The Gateway SHALL provide a Session-scoped timeline snapshot for one Run, an on-demand detail read for one tool call, and an on-demand observation-image read when a committed successful OCR or chart-measurement result has an available committed annotation attachment. The timeline SHALL be derived from that Run's committed `ToolCallFact`, `ToolAttemptStartedFact`, and `ToolResultFact` values; it SHALL NOT create duplicate timeline facts or include tool calls from another Run. Steps SHALL be ordered by durable tool-call sequence and grouped by call ID, with every attempt and any matching result associated with the originating call. Snapshot entries SHALL expose only bounded identity, tool name, timestamps, status, and a concise safe summary. Expanded details SHALL expose only bounded tool-specific summaries, attempt statuses and timestamps, safe error summaries, and typed source/observation references; they SHALL NOT return raw argument JSON or raw result JSON. Observation-image reads SHALL verify Session and Run ownership, require a successful supported OCR or measurement result and its authorized source, return a validated PNG with no-store headers, and SHALL read the same saved annotation bytes as Agent image feedback without redrawing or persisting a replacement. These routes SHALL NOT expose provider prompts, continuation, local paths, or image bytes in JSON.

#### Scenario: Read a Run timeline snapshot
- **WHEN** the browser reads the timeline for a Run containing committed tool calls
- **THEN** the Gateway returns one ordered summary per call, grouping its attempts and result without duplicating the tool payload in the snapshot

#### Scenario: Read one tool call's details
- **WHEN** the browser expands a timeline step for a call owned by the requested Session and Run
- **THEN** the Gateway returns only that call's bounded, allowlisted summaries, attempt statuses and timestamps, safe error summary, and available typed observation references

#### Scenario: Reflect a committed tool outcome
- **WHEN** a call has a committed successful or failed `ToolResultFact`
- **THEN** the timeline reports the corresponding completed or failed outcome and never infers success from a call or attempt-start fact alone

#### Scenario: Show an unresolved tool attempt safely
- **WHEN** a tool attempt has started without a committed result
- **THEN** the timeline reports it as running only while the current Gateway still owns the Run execution and otherwise reports a reconciliation-required or unknown state

#### Scenario: Show a call without an attempt
- **WHEN** a tool call has no committed attempt start
- **THEN** the timeline reports it as pending while the Run is active and not started when its Run is terminal

#### Scenario: Read a committed observation image
- **WHEN** the browser requests an observation image for a successful OCR or chart-measurement call with an authorized source
- **THEN** the Gateway reads the saved PNG selected by the committed attachment, validates identity and content fingerprint, and returns the same bytes without invoking an overlay renderer

#### Scenario: Reject a call or image from another Session or Run
- **WHEN** the browser requests timeline details or an observation image using a call ID outside the requested Session and Run
- **THEN** the Gateway returns a bounded not-found response without disclosing the call, source, or image

#### Scenario: Restore the timeline after reload
- **WHEN** the browser reads a completed, failed, interrupted, or still-running Run after reload
- **THEN** the timeline is reconstructed from committed facts and does not invoke, replay, or reconcile any tool

#### Scenario: Omit raw tool payloads from details
- **WHEN** a browser reads the details for a known or unrecognized tool call
- **THEN** the Gateway returns only supported, bounded display summaries and never serializes raw arguments or result payloads

#### Scenario: Fail a missing saved observation without repair
- **WHEN** a committed successful observation has no available attachment or its saved PNG is missing or corrupted
- **THEN** the existing image route returns a bounded not-found or unreadable response and does not redraw, rerun the historical tool or leak storage details
