## Context

See `proposal.md` for motivation. The current Agent owns one mutable list of
OpenAI message dictionaries, the CLI eagerly converts every `@path` into a
base64 image content part, and image sensors receive model-visible local paths.
The existing `ToolResult`/`GeneratedImage` transport already provides the right
boundary for returning an image from a tool without placing its bytes in JSON.

The design must preserve native assistant-tool-result ordering, the ephemeral
default, reasoning isolation, and the model's freedom to choose tools. It also
must avoid adding another cross-cutting responsibility directly to the current
Agent and CLI modules.

## Goals / Non-Goals

**Goals:**

- Give Agent history a replaceable memory boundary with in-memory and SQLite
  implementations.
- Recover named sessions without replaying incomplete tool protocol fragments.
- Keep model context bounded while retaining whole run/tool groups.
- Treat user image paths as explicit authorization records and let the model
  load or reload an attachment through a normal tool call.
- Reuse the current generated-image observation path for loaded source images.
- Keep storage and attachment policies testable without a provider connection.

**Non-Goals:**

- Semantic/vector retrieval, user profiles, automatic long-term fact writing,
  model-generated summaries, trace persistence, cloud sync, or multi-user
  access.
- Persisting image payloads or reconstructing old generated overlays after a
  restart.
- Replacing the deterministic OCR and geometry implementations.

## Decisions

### 1. Put persistence behind Agent memory and attachment interfaces

Introduce a memory package with provider-neutral session, run, record, and
attachment value objects. The Agent depends on an `AgentMemory`-style interface
for beginning a run, appending records, building context, and completing or
failing a run. `InMemoryAgentMemory` remains the default;
`SQLiteAgentMemory` is selected only for a named session.

An `AttachmentRegistry` interface owns registration, lookup, validation, and
metadata formatting. Both memory modes expose one: ephemeral attachments live
only in process, while named-session references use SQLite.

This keeps SQL and filesystem policy out of the loop. Alternative considered:
have the CLI preload and save `Agent.messages`. Rejected because it would
persist provider-shaped messages, make crash recovery ambiguous, and allow
base64 image content to cross the storage boundary.

Suggested module ownership is:

```text
memory/models.py       session, run, record, attachment value objects
memory/store.py        storage protocols and in-memory implementation
memory/sqlite.py       schema, transactions, named-session operations
memory/context.py      deterministic summaries and bounded context builder
attachments.py         registration, validation, and load_image tool factory
```

### 2. Store provider-neutral records in a schema-versioned SQLite database

Use stdlib `sqlite3` at `$CHARTAGENT_DATA_DIR/sessions.db`, with
`~/.chartagent` as the default data directory. Create the directory and database
with user-only permissions where the platform supports them. Enable foreign
keys, use transactions for lifecycle changes, and set a finite busy timeout.

Schema version 1 contains:

```text
schema_meta(version)
sessions(id, name UNIQUE, created_at, updated_at)
runs(id, session_id, ordinal, status, terminal_kind, created_at, updated_at)
records(id, run_id, sequence, kind, payload_json, created_at)
attachments(id, session_id, run_id, ordinal, canonical_path,
            filename, media_type, byte_count, sha256, created_at)
```

Session names are labels, not paths, and are bounded before insertion. Foreign
keys cascade from session deletion into runs, records, and attachment
references. Source files are outside database ownership and are never deleted.

Alternative considered: one JSONL file per session. Rejected because atomic
run-state transitions, unique names, cascading deletion, and interrupted-run
recovery are simpler and less error-prone in SQLite.

### 3. Treat one Agent.run call as the durable recovery unit

At the beginning of a named-session run, create a `running` row and append the
sanitized user/attachment records. Append assistant, tool, and visual-metadata
records in their actual order. Mark the run `completed` only after a final
answer or the normal budget result; mark it `failed` when an exception is
handled. On opening a session, convert abandoned `running` rows to
`interrupted` in one transaction.

Only completed prior runs enter a model request. The current running run is
assembled from valid in-process records. This lets storage retain diagnostic
information about failures without sending unmatched tool messages back to the
provider.

### 4. Bound context by run and protocol blocks, not individual messages

Define centralized memory limits for stored text, structured tool results,
summary text, recent-history context, and attachment metadata. Tool content is
kept valid JSON when truncated and carries an explicit truncation marker.

The context builder reserves space for the system prompt and current run, then
walks completed runs newest-first. A full run is retained only when all of its
required messages fit. Older runs are represented by a deterministic summary
containing bounded user intent, tool names and statuses, structured result
keys/short values, attachment IDs, and the terminal answer. No provider call is
made for summarization.

An assistant message containing tool calls, all matching native tool messages,
and the attributed visual-metadata notice form one indivisible block. A block
is retained or summarized as a whole. Transient image content is never part of
an older run's reconstructed context.

Use a configurable serialized-character budget in the first version. A precise
provider tokenizer is intentionally deferred; deterministic conservative
counting is more portable and has no new dependency.

### 5. Make @path registration-only and make image loading a normal tool

The CLI resolves and validates every referenced path before committing any
attachment from that input. Registration resolves the canonical path, checks a
supported image media type and byte limit, computes SHA-256 while reading in
bounded chunks, and creates an opaque `att_<id>` identifier. Model-visible
metadata includes the ID, filename, media type, and byte count but never the
canonical path or hash.

`load_image` accepts only `attachment_id`. The tool looks up the reference in
the active registry, verifies session ownership, rechecks file existence,
readability, media type, byte count, and hash, and then returns:

```text
ToolResult(
  data={attachment_id, filename, media_type, byte_count, status},
  images=(GeneratedImage(current_bytes, media_type, caption),),
)
```

The existing Agent observation transport sends that image to the next model
turn and keeps bytes out of the JSON tool result, durable memory, and trace.
Every invocation, including a reload after restart, performs current
validation. A changed file requires a new explicit user attachment.

Alternative considered: automatically reload historical attachments on
resume. Rejected because resuming a text session must not silently upload a
local file. Alternative considered: `load_image(path)`. Rejected because it
would expose unrestricted filesystem reads to the model.

### 6. Bind chart tools to authorized attachment resolution

Keep the current path-based OCR and geometry functions as programmatic sensor
implementations. Register model-facing wrappers whose schemas require
`attachment_id`; wrappers resolve and validate the authorized reference, then
call the existing sensor with its internal canonical path. The model never
receives that path.

This avoids duplicating OCR/geometry code and preserves direct Python tests.
The load tool and chart wrappers share the same attachment validation service,
so changed, missing, oversized, and cross-session references have consistent
structured errors.

### 7. Keep session management out of provider startup

Agent CLI options are:

```text
--session NAME          resume or create NAME
--new-session NAME      create NAME and fail if it exists
--list-sessions         print metadata and exit
--delete-session NAME   confirm, delete state, and exit
```

These options require `--agent`; create/resume options are mutually exclusive
with management-only options. Listing and deletion initialize the local store
but not `LLMClient`, so they work without API credentials. No session option
retains the current ephemeral REPL.

`load_image` and attachment-aware chart tools are registered in both ephemeral
and named Agent modes. A load call counts as a normal tool-calling turn and
therefore remains subject to the existing bounded Agent step budget; no tool
receives a special unbounded execution path.

### 8. Apply a memory-specific sanitization boundary

Do not persist `NormalizedResult.raw`, provider reasoning, provider
configuration, trace events, data URLs, or bytes. Reuse common bounded/redaction
primitives where appropriate, but keep a memory policy separate from trace
rendering because stored records must remain valid inputs for context
reconstruction.

Credential-like structured keys are redacted. Free-form user and assistant
text is stored only because named sessions are explicit opt-in; the system does
not claim to detect every secret embedded in natural language. Session deletion
is the explicit removal mechanism.

## Risks / Trade-offs

- [The model may fail to call `load_image`] -> Describe attachment IDs and tool
  semantics in the Agent prompt, keep behavior freely planned, and cover tool
  use with provider smoke rather than forcing a call in infrastructure.
- [Tool-only first image access adds a model turn] -> Count it normally and
  retain a configurable bounded step budget; do not create a bypass loop.
- [A source image moves or changes after registration] -> Validate path and hash
  on every load and require explicit reattachment.
- [Deterministic summaries lose nuance] -> Keep the durable bounded transcript,
  prefer recent complete runs in model context, and defer semantic retrieval.
- [SQLite corruption or incompatible schema] -> Use transactions and schema
  version checks; fail without modifying an unsupported newer database and
  leave ephemeral mode available.
- [Free-form session text may contain secrets] -> Keep persistence opt-in,
  enforce user-only local permissions, avoid provider/config fields, and provide
  explicit deletion.
- [Changing @path breaks eager multimodal assumptions] -> Preserve the
  programmatic image-content builder, update CLI tests and prompts, and provide
  `load_image` as the documented Agent path.

## Migration Plan

1. Add memory models, in-memory behavior, SQLite schema version 1, and storage
   tests without changing the Agent default.
2. Route Agent history through the memory boundary and prove ephemeral message,
   tool-order, answer, budget, reasoning, and trace behavior remain equivalent.
3. Add attachment registration and `load_image`, then switch CLI `@path` to
   registration-only metadata.
4. Add attachment-aware wrappers for OCR and bar measurement while retaining
   direct path-based sensor functions.
5. Add CLI session lifecycle commands, context bounding, restart recovery, and
   end-to-end offline/provider smoke tests.

Rollback keeps the database and source files untouched: omit session options to
use ephemeral mode, or revert the CLI attachment switch to the preserved direct
multimodal builder. An unknown newer database version is never downgraded or
rewritten automatically.
