## Context

`LLMClient` already calls the OpenAI Python SDK's Chat Completions surface, and
the Agent loop already represents tool calls as standard assistant/tool
messages. The incompatibility is concentrated in the client boundary:
configuration is named for DashScope, thinking is compiled to
`extra_body.enable_thinking`, output limits use `max_tokens`, and response
normalization assumes Qwen's optional `reasoning_content` field. The current
Gateway and desktop protocols consume the client's normalized result and do
not need to know which upstream endpoint is selected. See `proposal.md` for
the motivation and `specs/llm-client/spec.md` for the behavioral contract.

## Goals / Non-Goals

**Goals:**

- Make the client emit a predictable OpenAI Chat Completions request that can
  be inspected by a relay or provider without Qwen-only fields.
- Establish `OPENAI_*` as the canonical configuration namespace while keeping
  existing DashScope variables as an explicitly lower-priority migration path.
- Preserve the Agent's tool loop, streaming aggregation, reasoning isolation,
  raw response access, and Gateway event contract.
- Make standard reasoning effort, completion limits, usage collection, retry,
  and timeout behavior directly testable with the existing fake transport.

**Non-Goals:**

- Migrating the Agent loop to the Responses API. That would require changing
  the existing message/tool history contract and is not needed to use an
  OpenAI-compatible Chat Completions relay.
- Removing legacy DashScope environment variables immediately.
- Adding provider-specific extensions to the standard request path or
  implementing a second provider abstraction.
- Changing Gateway routes, SSE event names, session persistence, or desktop
  runtime ownership behavior.

## Decisions

### 1. Keep Chat Completions as the upstream protocol

The client will continue to call `chat.completions.create`. The request
builder will always provide `model`, `messages`, and `stream`, add `tools` only
when supplied, request streaming usage with `stream_options`, and add
`reasoning_effort` / `max_completion_tokens` only when explicitly configured.

The Responses API was considered, but it uses `input`, different tool-call
items, and different output/token-limit fields. Introducing it now would
force changes through the Agent history and tool dispatch code without fixing
the current relay compatibility issue.

### 2. Resolve canonical and legacy configuration per key

`resolve_config` will use this order for each setting independently:

1. explicit constructor or call value;
2. `OPENAI_API_KEY`, `OPENAI_BASE_URL`, or `OPENAI_MODEL`;
3. the corresponding `DASHSCOPE_*` / `DASH_MODEL` alias;
4. the built-in default.

`OPENAI_TIMEOUT` and `OPENAI_MAX_RETRIES` remain the standard behavior
variables. Numeric parsing will distinguish `None`/empty input from zero so a
configured `0` survives resolution. The default base URL will become
`https://api.openai.com/v1`; a relay or compatible deployment must be selected
through `OPENAI_BASE_URL` or an explicit parameter.

The existing stable `.env` discovery and `CHARTAGENT_ENV_FILE` override remain
unchanged. Documentation and `.env.example` will show the canonical names
first and label DashScope names as compatibility aliases.

### 3. Replace the Qwen thinking toggle with standard request parameters

`ClientConfig` and `LLMClient.chat` will expose an optional
`reasoning_effort` value and an optional `max_completion_tokens` value. The
old `enable_thinking` and `max_tokens` arguments will be removed from internal
call sites and smoke scripts. No request will synthesize `extra_body` merely
because a model is thought to support reasoning.

This keeps provider defaults available when `reasoning_effort` is omitted and
lets a relay reject unsupported effort values at the provider boundary rather
than silently translating them to a Qwen-only boolean.

### 4. Normalize standard and compatibility response metadata together

Non-streaming normalization will continue to read standard `message.content`,
`message.tool_calls`, `finish_reason`, and `usage`. It will optionally inspect
`reasoning_content` only when present, so OpenAI responses without textual
reasoning remain valid. Streaming normalization will aggregate content,
optional reasoning deltas, ordered tool-call fragments, finish reason, and the
final usage-only chunk. The untouched completion or ordered chunk list remains
in `raw`.

Observation entries will derive a small sanitized usage summary from the
normalized usage object (prompt, completion, total, and reasoning-token counts
when available). They will never serialize `raw`, request messages, or
credentials.

### 5. Keep the Gateway boundary unchanged

The Agent and Gateway continue to consume `NormalizedResult`; no upstream
request fields or provider response objects cross the Gateway contract. This
limits the change to the LLM client, its direct callers, configuration sample,
and tests, while preserving desktop mock/gateway behavior.

### 6. Verify with offline contract tests plus an opt-in real smoke test

The fake OpenAI transport will assert canonical request construction, alias
precedence, zero retry resolution, standard reasoning and token-limit fields,
tool calls, stream usage, and optional reasoning metadata. Existing tests that
assert `extra_body.enable_thinking` will be replaced with assertions that the
standard field is present and `extra_body` is absent. The smoke script will
read canonical configuration and use `reasoning_effort` so it can validate an
OpenAI relay without depending on Qwen variable names.

All Python verification and dependency operations use the Conda environment
named `agent`, for example `conda run -n agent pytest`.

## Risks / Trade-offs

- [Risk] Some OpenAI-compatible relays accept Chat Completions but do not
  implement `reasoning_effort` or `stream_options.include_usage`.
  -> [Mitigation] Omit optional fields unless requested, preserve raw responses,
  and make the real smoke test explicit; the standard path will fail visibly
  instead of silently sending Qwen extensions.
- [Risk] Existing `.env` files continue to contain only DashScope names.
  -> [Mitigation] Keep lower-priority aliases during migration and update the
  sample/configuration documentation to canonical names.
- [Risk] Removing `enable_thinking` and `max_tokens` breaks callers that still
  pass them.
  -> [Mitigation] Update all repository call sites and tests in the same
  change, document the migration, and let Python raise an immediate argument
  error for stale internal usage.
- [Risk] Provider reasoning text remains non-standard and may be absent even
  when reasoning tokens are billed.
  -> [Mitigation] Treat textual reasoning as optional, preserve usage details
  when exposed, and retain history isolation for any compatibility field.

## Migration Plan

1. Update the client configuration/request builder and migrate repository
   callers, tests, smoke scripts, and `.env.example`.
2. Run the offline suite with `conda run -n agent pytest` and validate the
   OpenSpec change.
3. For a configured relay, set `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and
   `OPENAI_MODEL`, then run the updated smoke command.
4. Roll back by reverting the client/configuration commit and restoring the
   previous DashScope-only sample variables; no database or Gateway protocol
   migration is required.
