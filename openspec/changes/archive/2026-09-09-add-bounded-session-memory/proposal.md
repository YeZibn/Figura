## Why

The Agent currently retains a complete multimodal history only inside one
process, so sessions cannot be resumed and image/tool payloads grow without a
bounded context policy. Image references are also uploaded eagerly, preventing
the model from deciding when an authorized image should be loaded or reloaded.

## What Changes

- Add opt-in named Agent sessions backed by local SQLite storage while keeping
  the no-session CLI path ephemeral and backward compatible.
- Persist completed Agent runs as structured records and rebuild model context
  from whole run blocks so assistant tool calls are never separated from their
  tool results.
- Bound model context with deterministic summaries of older completed runs and
  recent complete runs; do not invoke another model to create memory summaries.
- Record interrupted and failed runs for inspection while excluding incomplete
  protocol fragments from later model context.
- Add an attachment registry that stores authorized references (ID, canonical
  path, media type, size, and content hash) without persisting base64 or image
  bytes.
- Add a `load_image(attachment_id)` tool that validates session ownership,
  existence, content hash, media type, and size before returning the image as
  an in-memory visual tool observation. The Agent may call it again at any
  later step or after resuming a named session.
- **BREAKING** For Agent CLI attachment turns, `@path` registers and authorizes
  an attachment but no longer injects the image bytes into the first model
  request. The model receives attachment metadata and chooses whether to call
  `load_image`.
- Let model-facing chart sensors address authorized attachments by ID rather
  than receiving arbitrary local paths; retain direct path-based Python sensor
  functions as an internal/programmatic compatibility surface.
- Add CLI operations to create/resume, list, and explicitly delete named Agent
  sessions. Session deletion requires confirmation and never affects source
  image files.
- Never persist provider reasoning, credentials, raw provider responses,
  image base64, generated-image bytes, or unbounded tool content.

## Capabilities

### New Capabilities

- `agent-session-memory`: Durable named Agent sessions, run lifecycle records,
  and bounded reconstruction of valid model context.
- `attachment-access`: Session-scoped attachment registration and model-driven,
  validated image loading through an authorized tool.

### Modified Capabilities

- `agent-loop`: Replace process-only history ownership with an optional memory
  abstraction while preserving ephemeral behavior and native tool ordering.
- `cli-gateway`: Add named-session lifecycle options and register the attachment
  loading tool for Agent sessions.
- `multimodal-input`: Change Agent CLI `@path` handling from eager image upload
  to authorized attachment registration and model-visible attachment IDs.
- `chart-understanding`: Allow registered chart sensor tools to resolve
  session-authorized attachment IDs without exposing arbitrary paths to the
  model.

## Impact

- Affects Agent history ownership, context construction, CLI argument handling,
  attachment parsing, chart-tool registration, and multimodal observations.
- Adds a local SQLite state file using the Python standard library; no external
  database or vector dependency is introduced.
- Requires schema-versioned persistence and migration handling for future
  memory changes.
- Does not add cross-session semantic retrieval, user profiling, cloud sync,
  automatic long-term fact extraction, or persisted execution traces.
