## Purpose

为本地 Figura 用户提供一个与普通会话隔离的评测工作台，使独立评测批次、case 诊断、阶段时间线、报告和视觉证据可以通过安全的只读 Gateway 资源在前端被发现和复盘。

## ADDED Requirements

### Requirement: Gateway exposes an isolated evaluation catalog

The local Gateway SHALL expose a read-only evaluation catalog backed by the canonical data root's `evaluations/` directory. The catalog SHALL list only valid evaluation bundles and SHALL return bounded metadata including `evaluation_id`, status, provider, model, start/end timestamps, case count, case status counts, and first-failure summaries. Evaluation entries SHALL remain separate from the ordinary `/sessions` collection and SHALL NOT be copied into the default session database.

#### Scenario: User opens the evaluation workspace with existing bundles

- **WHEN** the client requests the evaluation collection
- **THEN** the Gateway returns valid evaluation summaries ordered by most recent update
- **AND** the response contains no absolute local paths, credentials, raw database content, or image bytes

#### Scenario: No evaluations exist

- **WHEN** the canonical data root has no valid evaluation bundle
- **THEN** the Gateway returns an empty evaluation collection with a successful bounded response
- **AND** the ordinary session collection remains unchanged

#### Scenario: Evaluation bundle is running or partial

- **WHEN** an evaluation index reports `running`, `partial`, or `blocked`
- **THEN** the catalog exposes that exact status and the available bounded metadata
- **AND** it does not infer completion or remove already persisted case information

#### Scenario: Evaluation directory is malformed

- **WHEN** an entry below `evaluations/` is missing a valid index, has an unsupported schema, or cannot be read safely
- **THEN** the Gateway excludes it from the normal catalog or returns a bounded diagnostic entry according to the catalog policy
- **AND** it does not expose the malformed path or fail the entire Gateway service

### Requirement: User can inspect an evaluation and its cases

The Gateway SHALL expose read-only detail resources for a selected evaluation and case. A detail response SHALL include the evaluation metadata, case status, session/run references, expected sample metadata, stage timeline, first confirmed failure, bounded summary/diagnostic references, and available report metadata. The response SHALL preserve `not_reached`, `not_observed`, `failed`, and partial states instead of presenting an incomplete run as successful.

#### Scenario: User selects a completed or partial evaluation

- **WHEN** the client requests a valid evaluation detail
- **THEN** the Gateway returns the batch metadata and all available case summaries without requiring the caller to open the evaluation's SQLite database

#### Scenario: User selects one case

- **WHEN** the client requests a valid case belonging to an evaluation
- **THEN** the Gateway returns its run reference, ordered stage states, bounded error summary, report references, and available evidence references
- **AND** an unknown evaluation or case returns a bounded not-found response

#### Scenario: Case history is requested

- **WHEN** the client requests the ordered history for a case with a persisted run
- **THEN** the Gateway returns mapped run events and stable evaluation-scoped visual resource references
- **AND** it does not return the underlying `sessions.db` or local filesystem paths

### Requirement: User can expand bounded read-only run details

The evaluation workspace SHALL allow a user to expand the read-only run record for a selected case and inspect available user input, model-visible replies, tool call metadata, bounded tool arguments, bounded tool results, measurement-repair details, and evaluation-scoped visual resource references. Expanded entries SHALL preserve their event or record sequence, timestamp, and tool `call_id` when available so that a tool call can be correlated with its result without exposing the underlying database.

#### Scenario: User expands a tool call and result

- **WHEN** the user expands a tool call or tool result in the existing read-only run timeline
- **THEN** the client requests and displays the available tool name, call identifier, sanitized arguments, sanitized structured result, status, and related visual evidence
- **AND** the user can distinguish the tool invocation from the tool's returned result

#### Scenario: User expands conversation content

- **WHEN** a case has persisted user or model-visible conversation records
- **THEN** the client displays those records in run order alongside the execution timeline
- **AND** missing conversation records do not hide the available event timeline or case diagnosis

#### Scenario: Detail data is truncated or unavailable

- **WHEN** a detailed argument, result, or conversation record was truncated during persistence, exceeds the detail limit, or is unavailable in the bundle
- **THEN** the client displays an explicit truncated/unavailable marker and preserves the remaining timeline
- **AND** it does not fabricate missing content or expose an arbitrary local file as a fallback

#### Scenario: Detailed content crosses a sensitive-data boundary

- **WHEN** an expanded record contains credentials, absolute local paths, hidden reasoning, raw binary data, or unbounded provider payload fields
- **THEN** the Gateway redacts, omits, or replaces those fields with bounded markers before returning the detail
- **AND** the client continues to use evaluation-scoped resource references for images

### Requirement: Evaluation resources are safe and previewable

The Gateway SHALL serve only allowlisted evaluation resources addressed by opaque or server-issued resource identifiers. Supported resources MAY include the input image, panel crops, visual observations, generated artifacts, report images, and bounded report/diagnostic text. Resource responses SHALL validate evaluation ownership, case/run ownership, media type, file existence, and configured size limits before returning content.

#### Scenario: User previews an available evaluation image

- **WHEN** the client requests an available input, panel, observation, artifact, or report image using its evaluation-scoped resource reference
- **THEN** the Gateway returns the image bytes with a validated supported media type
- **AND** the client can open it through the shared interactive preview without learning its local path

#### Scenario: Resource is missing or unauthorized

- **WHEN** a resource ID is unknown, belongs to another evaluation/case, is missing, changed, oversized, or has an unsupported media type
- **THEN** the Gateway returns a bounded unavailable/not-found error
- **AND** the client does not render a broken preview or fall back to a local path

#### Scenario: Caller attempts path traversal or sensitive-file access

- **WHEN** a request tries to address `..`, an absolute path, `.env`, `sessions.db`, or an unregistered file
- **THEN** the Gateway rejects the request without reading or exposing the target

### Requirement: Desktop client provides an independent evaluation workspace

The desktop client SHALL provide a distinct evaluation navigation mode and SHALL not render evaluation batches as ordinary conversations or sessions. The workspace SHALL include an evaluation list, selected evaluation details, case navigation, status text, stage timeline, failure explanation, report content, and visual evidence previews. Evaluation views SHALL be read-only in this change and SHALL not expose ordinary message composition or session deletion actions as evaluation mutations.

#### Scenario: User switches from sessions to evaluations

- **WHEN** the user activates the evaluation workspace
- **THEN** the client requests the evaluation catalog and displays it separately from the session list
- **AND** switching back to sessions preserves the existing active session state

#### Scenario: User inspects a case

- **WHEN** the user selects a case in an evaluation
- **THEN** the client shows its status, run references, ordered stages, bounded errors, report, and available evidence images
- **AND** technical identifiers remain visible where they help correlate a diagnosis

#### Scenario: Evaluation has no available records

- **WHEN** the evaluation catalog is empty or a selected bundle has no readable cases
- **THEN** the client shows a Simplified Chinese empty or unavailable state with a retry/refresh action
- **AND** the normal session workspace remains usable

### Requirement: Evaluation workspace refreshes safely

The client SHALL provide an explicit refresh action for evaluation data and SHALL poll selected evaluations only while their status is non-terminal, using bounded backoff or a bounded interval. Polling SHALL stop when an evaluation reaches `completed`, `partial`, or `blocked`, when the user leaves the evaluation workspace, or when the Gateway becomes unavailable. Refresh failures SHALL preserve the last readable snapshot and show an explicit stale/unavailable state.

#### Scenario: Running evaluation becomes terminal

- **WHEN** a selected evaluation changes from `running` to a terminal status
- **THEN** the client refreshes the final batch and case details
- **AND** it stops polling without duplicating cases or timeline events

#### Scenario: Gateway is temporarily unavailable

- **WHEN** a catalog or detail refresh cannot reach the local Gateway
- **THEN** the client keeps the last successful evaluation snapshot visible
- **AND** it shows a bounded retryable error instead of clearing the evaluation record

### Requirement: Reports and evidence remain separate from raw storage

The evaluation workspace SHALL render bounded Markdown/JSON summaries through safe client presentation and SHALL present report images through evaluation resource references rather than interpreting local Markdown file paths as browser URLs. Raw SQLite databases, unbounded provider payloads, credentials, and unrestricted report file contents SHALL remain unavailable to the client.

#### Scenario: Report contains image evidence

- **WHEN** a case has a Markdown report and registered report images
- **THEN** the client renders the report text and an evidence gallery using authorized resource references
- **AND** opening an image preserves its case and evaluation context

#### Scenario: Report is absent or truncated

- **WHEN** a bundle has no custom report or a report exceeds the bounded display limit
- **THEN** the client falls back to the standard summary/diagnostic view and indicates the report limitation
- **AND** it does not expose arbitrary files from the evaluation directory
