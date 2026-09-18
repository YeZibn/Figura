## 1. Provider configuration and client contract

- [x] 1.1 Add `deepseek` to provider validation and resolve provider-scoped `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`, timeout, retry, thinking, and reasoning-effort settings with `https://api.deepseek.com` and `deepseek-flash` defaults.
- [x] 1.2 Extend the OpenAI-compatible request builder with DeepSeek-specific thinking enable/disable fields and reasoning effort while preserving OpenAI and Qwen request isolation.
- [x] 1.3 Normalize DeepSeek `reasoning_content`, streamed deltas, usage, finish reasons, and standard tool calls into the existing result contract.
- [x] 1.4 Add a provider-aware assistant history path that replays DeepSeek `reasoning_content` only for required thinking-plus-tools follow-ups while keeping ordinary records, answers, and traces content-only.
- [x] 1.5 Update `.env.example` and provider-facing configuration documentation with the official `deepseek-flash` model ID, safe defaults, and secret-handling guidance.

## 2. Gateway and runtime integration

- [x] 2.1 Extend Gateway provider validation, readiness probing, health output, and safe error mapping to include `deepseek` without exposing keys, endpoints, or raw provider errors.
- [x] 2.2 Ensure accepted DeepSeek runs snapshot `provider=deepseek` and `model=deepseek-flash` in run metadata, checkpoints, and trace model boundaries without changing existing provider behavior.
- [x] 2.3 Keep DeepSeek-private reasoning out of transcript projection, ordinary run records, event payloads, and default trace output while retaining only the bounded context needed for an in-process or authorized checkpoint continuation.

## 3. Desktop provider selection

- [x] 3.1 Extend frontend provider types, labels, selector options, session persistence, and mock health data with `DeepSeek（V4.1 Flash）`.
- [x] 3.2 Render DeepSeek availability, effective provider/model metadata, and unavailable states consistently in Gateway and mock modes.
- [x] 3.3 Update frontend smoke assertions and user-facing Simplified Chinese labels without exposing provider credentials or arbitrary model parameters.

## 4. Regression and compatibility tests

- [x] 4.1 Add client configuration tests for DeepSeek defaults, explicit-over-environment precedence, missing credentials, invalid provider values, and provider-scoped isolation.
- [x] 4.2 Add request-shape tests for DeepSeek non-thinking, thinking, reasoning effort, image content, and standard tool definitions; assert that Qwen and OpenAI-specific fields do not leak.
- [x] 4.3 Add non-streaming and streaming normalization tests for DeepSeek content, `reasoning_content`, usage, and tool calls.
- [x] 4.4 Add Agent-loop tests proving DeepSeek tool follow-ups replay provider-required reasoning internally while Qwen reasoning remains excluded and traces/transcripts remain bounded.
- [x] 4.5 Add Gateway tests for DeepSeek readiness, provider selection, run snapshot metadata, unavailable configuration, and safe health/error responses.
- [x] 4.6 Run frontend build and smoke checks covering provider selection, health state, session persistence, and run metadata rendering.

## 5. Verification and rollout

- [x] 5.1 Run focused Python tests, the full pytest suite, `git diff --check`, and the frontend build/smoke commands in the canonical `agent` environment.
- [x] 5.2 When `DEEPSEEK_API_KEY` is configured locally, run bounded real-provider smoke checks for text, one-image visual understanding, one Tool Call, and a thinking-plus-multi-turn Tool Call.
- [x] 5.3 Verify existing OpenAI and Qwen runs remain selectable and functional, and that an absent DeepSeek key leaves only DeepSeek unavailable without blocking Gateway startup.
