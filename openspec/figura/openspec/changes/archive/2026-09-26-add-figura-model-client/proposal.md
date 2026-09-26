## Why

Figura needs a model-call boundary before the Run and Agent loop work can be connected. A small, explicit provider layer lets the first implementation support the selected Qwen, DeepSeek, and Xiaomi MiMo models while containing their request, reasoning-continuation, and error differences in one server-side contract.

## What Changes

- Add a Figura-specific provider configuration and factory for three allowlisted provider/model pairs: `qwen` / `qwen3.8-flash`, `deepseek` / `deepseek-flash`, and `mimo` / `mimo-v2.6-flash`.
- Translate bounded text, image, and function-tool requests into each provider's OpenAI-compatible Chat Completions format, then normalize streaming and non-streaming responses.
- Preserve ordered tool calls and provider-private continuation data needed for multi-turn thinking/tool requests, without exposing private reasoning in ordinary response fields or logs.
- Return bounded provider-neutral failures that distinguish known rejection from unknown remote outcome; disable implicit SDK retries and provider fallback.
- Keep Run persistence, attachment authorization/storage, ToolRegistry ownership, Agent orchestration, Gateway, CLI, and frontend provider selection for later changes.

## Capabilities

### New Capabilities
- `model-provider`: Configure and call Figura's allowlisted model providers through a normalized, server-side request/response boundary.

### Modified Capabilities

## Impact

- New package area: `src/figura/` provider configuration, adapters, normalized request/response types, and failure mapping.
- Uses the repository's existing `openai` Python SDK dependency; no new provider SDK is required.
- Document provider-specific configuration in `.env.example`; credentials remain in the process environment and never enter client DTOs.
- Figura's OpenSpec store gains a `model-provider` capability. No ChartAgent code, specs, or runtime behavior changes.
