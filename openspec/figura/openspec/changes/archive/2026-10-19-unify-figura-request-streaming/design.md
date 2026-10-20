## Context

See `proposal.md` for motivation and `specs/` for externally observable behavior. Current Provider callers set `stream=False`; the transport buffers a full response, while the stream normalizer separately accumulates deltas into a full response. Ordinary model retries use durable Run attempts, but context compaction owns a separate request binding and attempt counter. Frozen request codecs also encode the non-streaming option. The Gateway has durable sequenced lifecycle events, and the frontend lifecycle controller owns their replay and convergence.

## Goals / Non-Goals

**Goals:**

- Make one streaming request contract the only Provider dispatch path.
- Give every logical Provider request one immutable request record and every transmission one durable attempt record, regardless of whether the request serves an Agent turn or compaction.
- Keep partial output observable while retaining one atomic commit point for model responses, tool calls, continuations, and summaries.
- Distinguish connection/setup failures, slow response opening, active stream inactivity, explicit Provider rejection, and interrupted unknown outcomes without a total generation deadline.
- Replace the prior persisted request shape in one direct SQLite migration and remove runtime legacy decoding and dispatch branches.

**Non-Goals:**

- Change chart-analysis tools, tool execution retry semantics, context budgets, summary format, or compaction prompt content.
- Add generic stream resumption, Provider fallback, speculative tool execution, or retries for malformed completed responses.
- Persist or replay every text token as a durable Run event.
- Guarantee that a client can distinguish silent Provider computation from a half-open network path when neither side emits a heartbeat.

## Decisions

### One streaming-only Provider contract

Every configured Provider adapter consumes its native streaming response and emits one Figura event vocabulary: `response_started`, `text_delta`, private `reasoning_delta`, `tool_call_delta`, `usage`, `heartbeat`, `completed`, and `failed`. Provider-specific parsing remains inside the adapter. The capability profile states whether the selected Provider/model supports this contract and which optional stream fields it returns. A profile without streaming support fails before dispatch; there is no JSON/non-stream fallback.

The normalizer accumulates response content, tool calls by stream index, usage, finish reason, and Provider continuation. `completed` is emitted only after a valid Provider terminal event and local response validation. The existing `ProviderResponse` remains the complete-response value used by Agent code. Stream deltas are not accepted as model facts. The Provider adapters must preserve DeepSeek's missing, null, empty, and fragmented `reasoning_content` distinctions while never projecting reasoning into public text.

### One canonical logical request and one attempt ledger

Replace separate Agent binding and compaction request/attempt accounting with a single logical Provider request record and its physical attempts. The logical record owns immutable request identity and retry policy; the attempt row owns one dispatch lifecycle. Proposed logical-request fields are:

| Field | Meaning |
|---|---|
| `request_id`, `run_id` | Stable identity and owning Run |
| `purpose` | `agent_turn` or `context_compaction` |
| `compaction_operation_id` | Present only when the request belongs to a compaction operation |
| `base_record_sequence`, `base_tool_sequence` | Exact committed Run prefix used to build the request |
| `provider_id`, `model_id`, `endpoint_identity` | Selected Provider and secret-free endpoint identity |
| `request_fingerprint`, `request_contract_version`, `stream_contract_version` | Exact prepared request and its canonical contract |
| `options_json`, `asset_identity`, `prompt_digest`, `tool_registry_digest` | Frozen request options and required assembly inputs |
| `timeout_policy_version`, `retry_policy_version`, `max_attempts` | Frozen transport and retry policy; current allowance remains four physical attempts per logical request |
| `generation_only`, context estimate fields | Replacement eligibility and optional frozen token/capacity/estimator snapshot |
| `created_at` | Logical request creation time |

Proposed attempt fields are `attempt_id`, `request_id`, `attempt_sequence`, `status`, `phase`, `retry_of_attempt_id`, `started_at`, `connected_at`, `request_sent_at`, `response_headers_at`, `first_event_at`, `last_activity_at`, `finished_at`, `failure_phase`, `failure_code`, `failure_category`, `http_status`, bounded `provider_request_id`, `retry_after`, `next_eligible_at`, `request_bytes`, `response_bytes`, and bounded Provider usage. `phase` advances through `connecting`, `sending`, `awaiting_response`, and `streaming`; `status` ends once as `response_committed`, `known_failure`, `outcome_unknown`, or `cancelled`. Raw bodies, secrets, text deltas, reasoning, and partial tool JSON are never stored in these records.

`ContextCompactionOperation` continues to own its frozen source coverage, budgets, summary contract, status, and result revision. It stores the canonical `provider_request_id`; its duplicated Provider request descriptor and `attempt_count` are removed. Attempt counts and retry lineage come from the shared request/attempt records. Normal Agent checkpoints reference the same canonical request/attempt identities for recovery.

### Phase timeouts observe transport; they do not cap generation

Use explicit connect and request-write timeouts for failure before a request is established or transmitted. After transmission, first-response and stream-idle thresholds are observability thresholds, not cancellation deadlines. They update user-facing waiting status and diagnostic timestamps. There is no total generation timeout. Read remains open while transport is live; TCP keepalive and Provider SSE heartbeats are used when available. A peer close, reset, explicit HTTP failure, user stop, or confirmed transport error ends the attempt. Silence without evidence of failure remains waiting rather than being mislabeled as a network error.

The diagnostic record distinguishes transport activity from generated text: a heartbeat updates `last_activity_at` but not `first_event_at` or assistant content. A long wait before headers is therefore visible as a phase and elapsed duration, but Figura does not claim that the Provider is computing unless an actual stream heartbeat or event proves activity.

### One durable retry owner for all Provider requests

The Runtime request coordinator owns attempt claims, durable wait scheduling, stop arbitration, and replacement eligibility. SDK and HTTP transport retries stay disabled. It applies the existing maximum of four attempts per logical request, exponential backoff with jitter, and a valid later `Retry-After`. Each attempt reuses the exact prepared request fingerprint and frozen policy. No total Run request limit is added.

Failures before request transmission are known unsent failures. Explicit Provider error responses are known rejections. Once request bytes may have reached the Provider, a timeout, EOF, or stream reset without a terminal response is outcome-unknown. Figura closes the old attempt and waits for the original owner to be inactive before any replacement. A replacement is a whole-request replay unless a selected Provider later gains a documented idempotency or resume contract; the initial implementation does not implement generic stream resume. Replaying can incur duplicate Provider billing, but cannot duplicate tool effects because tool calls are not committed until a complete response is accepted. A malformed response after a valid terminal event is an invalid response, not a transport retry.

User stop takes precedence over retry. The client closes the local stream, the attempt records cancellation and outcome certainty separately, and no retry is scheduled. A process crash leaves a started attempt; recovery closes it as outcome-unknown before checking the same frozen retry binding.

### Agent and compaction consume the same stream differently

The Agent consumer forwards assistant-visible `text_delta` events for provisional display and accumulates the complete response. It withholds reasoning and tool-call deltas from the browser. It commits the response, continuation, complete tool-call batch, and next checkpoint in one Runtime transaction only after `completed`. Tools never run from partial arguments.

The compaction consumer does not send summary deltas as assistant text. It buffers the summary response privately, validates JSON/fields/source references after `completed`, and installs it with the operation's existing expected-revision compare-and-swap. Any transport, cancellation, or validation failure leaves the prior checkpoint authoritative and follows the current safe fallback path.

### Durable lifecycle and transient text use separate event semantics

Persist only coarse Provider phase transitions as allowlisted `run_progress` events. Durable event IDs remain `run_id:sequence`; the current shared frontend controller remains the sole owner of lifecycle merging, reconnect cursors, history catch-up, and terminal convergence.

Assistant text uses transient `assistant_delta` SSE events without a durable event ID, carrying `run_id`, `attempt_id`, `delta_sequence`, and text. They are scoped to the owning Session, omitted from history reads and SQLite, and contain no reasoning or tool arguments. The frontend accepts only an ordered delta sequence for the current attempt. A retry resets provisional text. After reconnect, a missing sequence causes the partial buffer to be discarded; the client waits for a complete canonical response rather than pretending the gap can be recovered. A terminal refresh replaces provisional text with the committed response.

### Direct data migration; no runtime compatibility path

Add one atomic SQLite schema migration that replaces the current request binding and attempt shape with the canonical Provider request/attempt records, moves context-estimate and retry metadata where present, and updates constraints, codecs, indexes, and triggers. Normalize execution payload storage to the shared configured codec guard so fresh and upgraded databases enforce the same size policy. Preserve committed Run records, continuations, tool facts, checkpoints, completed attempts, and valid context checkpoints. A started or retry-waiting operation frozen under the removed non-streaming request contract cannot be reproduced under the new contract: migration closes a started attempt as outcome-unknown, disables any old retry schedule, marks its owning Run interrupted, and leaves the previous context checkpoint unchanged. It does not retry the old request or synthesize missing phase timestamps. The migration validates foreign keys and the complete Runtime snapshot before commit; any failure rolls back the schema and data together.

After migration, runtime codecs accept only the canonical schema. Remove `stream=False`, non-stream dispatch/normalization, legacy binding readers, and dual Gateway event behavior. This is a one-time data migration, not a runtime compatibility layer. A pre-migration database backup is retained for operator rollback; the new binary does not read the old schema.

## Risks / Trade-offs

- [A Provider lacks compatible SSE behavior or omits expected terminal metadata] → Declare capabilities per configured Provider/model, reject unsupported profiles before dispatch, and add contract tests for Qwen, DeepSeek, and MiMo fixtures.
- [A silent intermediate network path cannot prove whether remote generation is still active] → Do not use total elapsed time or absence of text as failure; expose a waiting phase, collect transport diagnostics, and allow user stop.
- [A whole-request replay can be billed twice after an unknown outcome] → Persist outcome uncertainty and retry lineage, use documented Provider idempotency only when available, and never execute partial tool intents.
- [Transient output is lost across reconnects] → Keep it explicitly provisional, detect delta gaps, clear incomplete text, and converge from the canonical committed Run response.
- [Direct migration interrupts active old-contract work] → Run the migration under exclusive Runtime startup ownership, preserve completed facts and checkpoints, close old in-flight attempts deterministically, and roll back the entire migration on any validation error.
- [A provider stream can remain silent for a long time] → Use phase status and TCP keepalive where available; do not introduce an unrequested generation deadline. User cancellation remains available.

## Migration Plan

1. Land the new Provider event and capability contracts together with the canonical request/attempt records and a versioned SQLite migration.
2. During startup, acquire exclusive Runtime ownership, back up the database, migrate and validate in one SQLite transaction, and fail startup without partial writes if validation fails.
3. Convert completed historical request/attempt facts; mark any old in-flight or retry-waiting request interrupted/outcome-unknown and preserve the last valid compaction checkpoint.
4. Switch every Provider call site to streaming-only dispatch, then remove the non-stream request branch, old binding decoder, duplicate compaction attempt accounting, and obsolete tests.
5. Deploy the matching Gateway and frontend contract together. Rollback requires restoring the database backup and the matching prior application version; the new application does not run in dual-schema mode.

## Open Questions

None. Provider-specific timeout threshold defaults can be selected during implementation without changing the no-total-generation-timeout contract.
