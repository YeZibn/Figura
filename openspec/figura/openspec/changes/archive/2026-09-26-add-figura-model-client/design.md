## Context

See `proposal.md` for motivation and scope. `src/figura/` currently contains only its package marker. The repository already depends on the OpenAI Python SDK; ChartAgent has a provider-aware client, but Figura is a separate implementation and must not import ChartAgent runtime or config.

## Goals / Non-Goals

**Goals:**

- Make the provider layer independently callable before RunCoordinator, ToolRegistry, and AttachmentStore are integrated.
- Keep the selected provider/model mapping bounded and keep all credentials and provider-specific request translation on the server.
- Represent images and tool calls in a provider-neutral input/output contract and preserve private continuation data in memory for future turns.
- Make retry and failure behavior explicit so SDK defaults cannot resend an uncertain request.

**Non-Goals:**

- Choosing Figura's product-wide default provider or exposing provider selection in the CLI, Gateway, or frontend.
- Persisting requested/actual provider values, profile versions, assistant responses, or continuation data in Run/ExecutionRecord.
- Implementing attachment authorization/storage, the Agent loop, PromptAssembler, concrete Figura tools, VLM review, or automatic failover.
- Claiming that supported image input implies acceptable chart-analysis quality; that requires a later real-model evaluation.

## Decisions

### 1. Use one Figura provider boundary and explicit provider policies

Add a Figura-owned provider package with configuration, request/response types, a factory, three provider policies, and bounded failure normalization. Each call names its provider explicitly; the factory resolves only these pairs:

| Provider | Model ID | Base URL resolution |
|---|---|---|
| `qwen` | `qwen3.8-flash` | Required `FIGURA_QWEN_BASE_URL`, because the Qwen endpoint depends on region/workspace; `FIGURA_QWEN_API_KEY` must belong to that endpoint's region. |
| `deepseek` | `deepseek-flash` | `FIGURA_DEEPSEEK_BASE_URL`, defaulting to `https://api.deepseek.com`; credential from `FIGURA_DEEPSEEK_API_KEY`. |
| `mimo` | `mimo-v2.6-flash` | `FIGURA_MIMO_BASE_URL`, defaulting to the documented pay-as-you-go API `https://api.xiaomimimo.com/v1`; credential from `FIGURA_MIMO_API_KEY`. A Token Plan deployment overrides the URL and uses its matching key. |

Model IDs are code-owned constants in this change rather than arbitrary environment or caller values. Timeout and thinking settings use provider-specific `FIGURA_<PROVIDER>_*` variables. Missing credentials or required endpoint means that profile is unavailable; the factory reports configuration status without making a network request. There is no client-level default provider: the future application/Run layer will choose that policy.

Alternative considered: reuse ChartAgent's global provider configuration and infer a provider from whichever API key exists. Rejected because it couples the new runtime to the legacy application and gives ambiguous behavior when multiple credentials are configured.

### 2. Keep the provider input transient and independent from Run storage

Define a typed, in-memory `ProviderRequest` containing:

| Field | Meaning |
|---|---|
| `provider_id` | Required allowlisted provider ID. |
| `model_id` | Required model ID matching that provider's fixed profile. |
| `instructions` | Ordered system/developer instruction content prepared by the caller; provider policy maps it to supported instruction channels without silently dropping it. |
| `messages[]` | Ordered user/assistant/tool conversation messages. Assistant messages may carry tool calls and a private continuation object; tool messages identify their `tool_call_id`. |
| `tools[]` | Optional function schemas with name, description, JSON Schema parameters, and optional strictness requirement. |
| `options` | Versioned allowlist: `thinking_mode`, optional `reasoning_effort`, required `max_completion_tokens`, and `stream`. No arbitrary `extra_body`, endpoint, or credential is accepted here. |

Image content blocks carry `media_type` and in-memory bytes only at the provider boundary. Upstream code later resolves and authorizes an AttachmentRef, then supplies those bytes; this change does not resolve IDs or read local paths. Adapters encode the bytes as provider-compatible Base64 image content at send time. MiMo supports Base64 image input; a public URL is not required.

Alternative considered: make the provider package consume `RunExecutionContext`, `PromptBundle`, or Attachment IDs directly. Rejected because those owners are later changes and would force the first provider change to depend on incomplete persistence and authorization systems.

### 3. Normalize the response but retain continuation privately

`ProviderResponse` contains `assistant_content`, ordered `tool_calls[]` (`call_id`, `name`, original argument string), normalized `finish_reason`, and optional bounded numeric usage counters and provider response ID. It does not contain unrestricted SDK `raw` output.

An assistant message and response may also carry a private `ProviderContinuation` with a provider ID, format version, and only the provider fields required for continued reasoning/tool interaction. For the selected models this includes the returned reasoning content when the provider requires or recommends replay. The next request maps that value back to the correct assistant message field without modifying or merging it into visible content. Logs, traces, and public DTOs omit the continuation. Persistence and controlled refs belong to the later ExecutionRecord/ArtifactStore work.

Alternative considered: discard all reasoning data and retain only visible assistant content. Rejected because DeepSeek thinking with tools requires replay, while Qwen and MiMo document replay behavior for their selected thinking models; dropping it can fail or degrade multi-turn calls. This design does not expose chain-of-thought to end users.

### 4. Translate only supported provider-specific thinking and tool fields

The common options are semantic. Provider policies own their wire representation:

| Provider | Thinking translation | Important constraint |
|---|---|---|
| Qwen | Use the current supported `reasoning_effort`/thinking controls for `qwen3.8-flash`; retain/replay reasoning according to the model's documented `preserve_thinking` behavior. | Do not combine mutually exclusive effort and thinking-budget parameters. |
| DeepSeek | Map the thinking toggle to `thinking.type` and pass optional supported `reasoning_effort`. | With tool requests, replay all required historical `reasoning_content`. |
| MiMo | Map the toggle to `thinking.type`; do not synthesize an effort setting. | In thinking mode, omit caller temperature/top-p fields; use `tool_choice=auto` and do not promise forced selection. |

The initial profile default is thinking enabled for all three selected models, matching their current API defaults and the old Figura client defaults where applicable. It is sent explicitly and can be disabled by server configuration; it is not a frontend option in this change. `reasoning_effort` is optional and omitted unless configured. The request always supplies a bounded `max_completion_tokens` value from the caller/runtime policy.

Tool schemas are passed through a provider-specific compatibility check. Unsupported strict/schema features produce a safe incompatibility error; the adapter never removes `required`, `enum`, or constraints to make a request pass. Tool invocation and argument validation remain the responsibility of the later ToolRegistry/Agent changes.

Alternative considered: expose one shared vendor-neutral raw body or accept caller-provided `extra_body`. Rejected because vendor fields are not interchangeable and arbitrary bodies bypass allowlisting and safety checks.

### 5. Use the existing OpenAI SDK transport with automatic retries disabled

All three selected APIs expose OpenAI-compatible Chat Completions. Reuse the installed `openai` dependency for HTTP/SSE transport, while each provider policy builds its own request body and parses provider-specific fields. Configure the SDK with `max_retries=0`; the provider client itself does not automatically retry any error and does not fail over to another provider.

Map failures to bounded categories and fields such as `failure_code`, `http_status`, `outcome_known`, `transient`, and `safe_message`. A timeout, connection loss, or incomplete stream with no definitive response has unknown outcome and is never automatically resent. A definitive rejection is reported distinctly. A future Run-level retry policy may decide whether a known rejection is safe to retry; it is outside this change.

Alternative considered: inherit SDK retry defaults. Rejected because a retry after timeout or partial stream can duplicate provider work and billing without the caller knowing the first outcome.

### 6. Keep the first change independently verifiable

The factory will expose configuration-only availability and deterministic request construction. Offline transport tests will use a mocked SDK to verify all three request policies, streamed/non-streamed normalization, continuation replay, and error classification. A credentialed real-provider smoke test is optional and is not required for a local configuration to be reported as present.

The provider package will be callable directly from Python in this change. RunCoordinator will later freeze the selected provider/model in `Run`; no placeholder Run persistence, Gateway route, CLI command, or frontend selector is added here.

## Risks / Trade-offs

- [Provider-compatible APIs differ in role, image, tool-schema, and streaming details] → Keep those translations inside provider policies and reject unsupported cases explicitly.
- [Thinking continuation contains private model output] → Keep it in typed in-memory fields only, exclude it from visible content and all logs, and add durable storage only behind a later controlled ref design.
- [Qwen endpoint and key must match region/workspace; MiMo Token Plan has a different matching key/URL] → Require the Qwen base URL and make the MiMo URL override explicit; never return raw URLs in availability output.
- [Thinking defaults may raise latency or usage] → Make the setting server-configurable and send its value explicitly; leave effort unset unless configured.
- [Model aliases can be repointed by a provider] → Record the API model ID in future Run snapshots; do not claim it pins the provider's underlying weights.
- [Disabling automatic retries can turn transient failures into visible errors] → Prefer a truthful unknown-outcome report; later Run policy can add safe retry behavior for definitive failures.

## Migration Plan

This is additive to the new Figura package and does not alter ChartAgent configuration, data, or behavior. Add provider environment-variable names to `.env.example` without secret values. Rollback consists of removing the new Figura provider package and its example configuration; no persisted records or schema migration are introduced by this change.
