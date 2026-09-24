## 1. Memory models and interfaces

- [x] 1.1 Add provider-neutral session, run, record, and attachment value objects with bounded field validation and explicit lifecycle states.
- [x] 1.2 Define the memory and attachment storage protocols for starting runs, appending ordered records, building context, completing/failing runs, and resolving attachments.
- [x] 1.3 Implement `InMemoryAgentMemory` with reset/new-session behavior and no filesystem persistence.
- [x] 1.4 Add centralized memory limits and sanitization helpers for text, structured tool results, attachment metadata, and credential-like fields.

## 2. SQLite persistence and lifecycle recovery

- [x] 2.1 Add the versioned SQLite schema (`schema_meta`, `sessions`, `runs`, `records`, and `attachments`) with foreign keys, indexes, and user-only database initialization where supported.
- [x] 2.2 Implement transactional named-session create, resume, list, and delete operations with bounded names and collision-safe behavior.
- [x] 2.3 Implement ordered run and record persistence, including atomic status transitions for `running`, `completed`, `failed`, and `interrupted`.
- [x] 2.4 Mark abandoned `running` runs as `interrupted` when a named session is reopened, without exposing their partial protocol records to future model context.
- [x] 2.5 Reject unsupported newer schema versions without rewriting the database and keep ephemeral Agent startup available when persistence cannot be used.

## 3. Bounded context construction

- [x] 3.1 Implement deterministic serialization and truncation for persisted records while preserving valid JSON and explicit truncation markers for tool content.
- [x] 3.2 Build complete-run context selection that reserves system/current-run capacity and retains only whole assistant-tool-result protocol blocks.
- [x] 3.3 Implement deterministic summaries for omitted completed runs containing bounded user intent, tool names/statuses, result keys/short values, attachment IDs, and terminal answers.
- [x] 3.4 Ensure context reconstruction excludes failed/interrupted runs, provider reasoning, trace data, raw provider responses, binary payloads, and transient image content.
- [x] 3.5 Add unit tests for budget boundaries, oversized records, summary determinism, protocol ordering, and unmatched tool-call prevention.

## 4. Attachment registration and `load_image`

- [x] 4.1 Implement session-scoped attachment registration with canonical paths, supported image MIME detection, bounded byte counting, SHA-256 hashing, and opaque `att_<id>` identifiers.
- [x] 4.2 Persist named-session attachment metadata and keep ephemeral attachment references process-local; never persist source-image bytes, generated-image bytes, or data URLs.
- [x] 4.3 Implement current-file validation for ownership, existence, readability, media type, size, and content hash, with bounded structured errors that do not reveal unauthorized paths.
- [x] 4.4 Add the model-facing `load_image(attachment_id)` tool that returns safe metadata plus an in-memory `GeneratedImage` observation through the existing tool-result transport.
- [x] 4.5 Make repeated loads and post-restart loads work only after fresh validation, and require reattachment when a source file is missing or changed.
- [x] 4.6 Add attachment tests covering registration order, cross-session authorization, changed/missing/oversized files, metadata redaction, ephemeral lifetime, and successful visual observations.

## 5. Attachment-aware chart tools

- [x] 5.1 Add authorized `attachment_id` wrappers for `extract_text` and `measure_bars` that resolve through the active attachment registry before calling existing path-based sensor implementations.
- [x] 5.2 Preserve direct Python path-based sensor compatibility while keeping local canonical paths out of model-visible tool schemas, results, prompts, and traces.
- [x] 5.3 Normalize chart-tool attachment failures into bounded structured errors without uncaught exceptions or visual artifacts.
- [x] 5.4 Verify OCR and bar-measurement overlays continue to use the source image dimensions and remain available as multimodal observations on successful calls.
- [x] 5.5 Add tool-level tests for valid authorized attachments, empty detections, invalid references, changed files, and overlay/result consistency.

## 6. Agent integration

- [x] 6.1 Replace direct mutable message-history ownership with the memory boundary while preserving existing system prompts, provider message ordering, reset behavior, and bounded step limits.
- [x] 6.2 Persist sanitized user, assistant, tool, visual-metadata, terminal, and error records in their actual execution order for named sessions.
- [x] 6.3 Complete named runs only after a final answer or normal bounded-budget outcome, and mark handled provider/tool failures as failed without creating invalid provider context.
- [x] 6.4 Register `load_image`, attachment-aware chart tools, and existing built-in tools in both ephemeral and named Agent modes.
- [x] 6.5 Describe attachment IDs and load semantics in the Agent prompt while leaving image loading and chart-analysis sequence under model control.
- [x] 6.6 Preserve explicit trace output for reasoning/tool calls without persisting reasoning, credentials, raw responses, image bytes, or trace events.
- [x] 6.7 Add offline Agent tests using fake providers for multi-step tool ordering, visual observations, reset, budget termination, error recovery, memory exclusion rules, and resumed context.

## 7. CLI session and attachment gateway

- [x] 7.1 Add Agent-only parsing and validation for `--session`, `--new-session`, `--list-sessions`, and `--delete-session`, including mutually exclusive combinations and bounded errors.
- [x] 7.2 Make list and delete operations initialize only the local store, so they work without constructing `LLMClient` or requiring provider credentials.
- [x] 7.3 Implement resume/create semantics for named sessions and refuse overwrite for `--new-session`; preserve the current ephemeral REPL when no session option is supplied.
- [x] 7.4 Implement deletion confirmation that removes session state and attachment references without deleting referenced source files.
- [x] 7.5 Change REPL `@path` parsing to support unquoted and quoted paths, register valid images in reference order, and send only remaining text plus safe attachment metadata on the first request.
- [x] 7.6 Preserve plain-text input behavior and report invalid attachment references before committing the user turn.
- [x] 7.7 Add CLI tests for option combinations, credential-free management commands, restart/resume, deletion safety, quoted paths, multiple attachments, and eager-byte/path leakage.

## 8. Verification and rollout

- [x] 8.1 Run the complete project test suite and focused memory, attachment, chart-tool, Agent, and CLI tests through `conda run -n agent`.
- [x] 8.2 Add an offline restart trajectory that creates a named session, completes a tool-using chart run, exits, resumes it, reloads an attachment, and verifies bounded valid context.
- [x] 8.3 Add provider smoke coverage for freely planned image loading, chart sensor use, visual self-check observations, descriptive image questions, and U0 ChartSpec restoration.
- [x] 8.4 Document the named-session data directory, lifecycle flags, attachment semantics, trace mode interaction, and Conda `agent` environment in the project usage documentation.
- [x] 8.5 Re-run OpenSpec validation and review the implementation against every scenario before marking the change complete.
