## Context

See `proposal.md` for the motivation and externally visible scope. The
current client uses one OpenAI SDK transport, resolves OpenAI and legacy
DashScope variables globally, and the Gateway creates a runtime from process
configuration. The frontend already submits bounded JSON run requests and
renders durable run events, so provider selection can be added to those
existing boundaries without exposing provider credentials.

## Goals / Non-Goals

**Goals:**

- Keep the existing OpenAI request path pointed at the deployment's configured
  relay through `OPENAI_BASE_URL`.
- Add Qwen as a provider strategy over the existing OpenAI-compatible SDK,
  including `extra_body.enable_thinking` and `reasoning_content` handling.
- Make provider selection explicit, bounded, validated before execution, and
  immutable for each accepted run.
- Keep frontend, Gateway, mock client, trace, and persisted run metadata on one
  compatible protocol.

**Non-Goals:**

- Direct browser-to-provider requests or frontend-managed API keys.
- A general multi-provider plugin marketplace or arbitrary provider request
  bodies.
- Changing Agent prompts, tool schemas, review gates, image handling, or
  reasoning-history isolation.
- Automatic provider failover during a run.

## Decisions

### 1. Resolve provider first, then provider-scoped configuration

Introduce a small provider-aware configuration result with a bounded provider
identifier, credentials, endpoint, model, timeout/retry values, and Qwen
thinking settings. `CHARTAGENT_PROVIDER` selects the default and remains
`openai` by default. A run-level provider override is validated against the
same allowlist and passed to runtime construction; it cannot override any
other configuration field.

OpenAI reads `OPENAI_*` only and keeps the existing relay URL supplied by the
deployment. Qwen reads `QWEN_*`, with `DASHSCOPE_*` aliases only as Qwen
migration fallbacks. This replaces the current global OpenAI/DashScope
fallback mixing, which could route an OpenAI run to an unintended endpoint.

Alternative rejected: infer the provider from whichever key exists. That makes
two configured providers ambiguous and prevents a reliable frontend selector.

### 2. Use a request policy rather than scattered provider branches

The client builds common Chat Completions fields first, then applies a
provider policy. The OpenAI policy preserves the current relay behavior. The
Qwen policy adds `extra_body.enable_thinking` only when enabled and excludes
OpenAI-only reasoning fields unless later validated for Qwen. The existing
normalizers remain the shared response boundary; `reasoning_content` is
already recognized for both message and streaming delta objects.

Alternative rejected: let callers pass arbitrary `extra_body`. It would leak
provider-specific parameters across providers and make configuration
validation impossible.

### 3. Make provider selection a run-level snapshot

The frontend maintains a selected provider for the active session and sends it
on the next run request. The Gateway validates and resolves it before creating
the Agent runtime, then records provider/model in the run summary and start or
model events. Existing runs never observe later frontend changes. Session
selection persistence is represented by safe session/client state; legacy runs
without metadata remain renderable.

Alternative rejected: mutate a long-lived Gateway-wide client. It would create
cross-session races and make concurrent runs change provider unexpectedly.

### 4. Keep readiness per provider and secrets server-side

Health reports only provider identifiers, availability, safe reason codes, and
the default provider. The browser never receives keys, raw endpoints, or raw
provider exceptions. The Gateway may reject an unavailable selection before
starting Agent execution while leaving the HTTP service and existing history
available.

### 5. Extend the existing request/event contract compatibly

Add optional `provider` to synchronous and asynchronous message/run bodies so
older clients continue to use the configured default. Add optional provider
and model fields to run summaries and event payloads. The frontend and mock
adapter understand the fields, while unknown/missing metadata remains safe to
render.

## Risks / Trade-offs

- [Qwen compatibility may differ for streaming usage or tool-call deltas] →
  Add offline request/normalization tests and an explicit provider smoke test;
  do not claim readiness based on network connectivity.
- [A Qwen thinking turn may increase latency and token cost] → Keep thinking
  configuration explicit, show only provider/model in the UI, and preserve the
  existing bounded run behavior.
- [A configured key may still be expired or rejected] → Readiness remains
  configuration-only; provider request failures use the existing safe run
  failure contract.
- [A frontend provider change could be mistaken as changing an active run] →
  snapshot provider at acceptance and label the selector as applying to the
  next run.
- [Legacy DashScope variables could accidentally affect OpenAI] → Scope aliases
  to Qwen resolution and add precedence/isolation tests.

## Migration Plan

1. Add the new provider variables while preserving existing OpenAI relay
   variables and legacy DashScope aliases.
2. Deploy the provider-aware client and Gateway with default `openai`, so
   existing clients and requests continue to work without a provider field.
3. Deploy the frontend selector and mock protocol support.
4. Roll back by removing the selector/override behavior and leaving
   `CHARTAGENT_PROVIDER=openai`; old requests remain valid because provider is
   optional.

## Open Questions

None. The provider identifiers, server-side secret boundary, OpenAI relay
constraint, Qwen request field, and run snapshot semantics are resolved for
implementation.
