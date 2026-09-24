## 1. Provider configuration and client policy

- [x] 1.1 Add bounded `openai`/`qwen` provider resolution with
  `CHARTAGENT_PROVIDER`, provider-scoped `OPENAI_*`/`QWEN_*` variables, and
  Qwen-only legacy DashScope aliases; preserve the existing OpenAI relay URL.
- [x] 1.2 Extend the resolved client configuration with provider identity and
  Qwen thinking settings, including explicit validation and safe configuration
  errors.
- [x] 1.3 Implement provider request policies so OpenAI keeps its current
  standard fields and Qwen receives only supported common fields plus
  `extra_body.enable_thinking` when enabled.
- [x] 1.4 Add provider metadata to observations and model trace boundaries while
  keeping credentials, endpoints, and raw provider payloads out of logs.

## 2. Qwen response and compatibility coverage

- [x] 2.1 Verify and, if needed, harden non-streaming and streaming
  `reasoning_content`, content, usage, and tool-call normalization for Qwen.
- [x] 2.2 Add offline client tests for provider precedence, OpenAI relay
  isolation, Qwen thinking toggles, legacy aliases, missing configuration, and
  provider-specific parameter exclusion.
- [x] 2.3 Add compatibility tests for Qwen tools, streamed tool-call deltas,
  multimodal messages, reasoning isolation, and bounded observations.

## 3. Gateway and runtime protocol

- [x] 3.1 Add per-provider readiness discovery with safe reason codes and a
  default provider to the health contract.
- [x] 3.2 Accept and validate optional provider values on synchronous and
  asynchronous run requests; reject client-supplied keys, endpoints, models,
  and arbitrary provider bodies.
- [x] 3.3 Thread the validated provider into runtime/client construction and
  snapshot effective provider/model on managed runs before execution.
- [x] 3.4 Persist and expose provider/model metadata in run summaries, start
  events, model events, and historical event replay without breaking legacy
  records.
- [x] 3.5 Add Gateway tests for selection, unavailable-provider rejection,
  snapshot stability, safe health output, and legacy request compatibility.

## 4. Frontend and mock client

- [x] 4.1 Extend shared client types and Gateway adapter request bodies with an
  optional provider field and safe health capability metadata.
- [x] 4.2 Add an accessible Simplified Chinese provider selector showing
  `OpenAI（中转站）` and `Qwen（DashScope）`, with unavailable-state handling
  and next-run semantics.
- [x] 4.3 Render effective provider/model metadata in run inspection and keep
  legacy runs without metadata valid.
- [x] 4.4 Update the mock adapter to accept provider selection and emit the same
  safe metadata for offline frontend development.
- [x] 4.5 Add or update frontend smoke/build coverage for selection, request
  payload safety, session reload, and active-run switching behavior.

## 5. Documentation and verification

- [x] 5.1 Update `.env.example` and relevant runtime documentation with the
  OpenAI relay, Qwen settings, provider defaults, and legacy alias policy.
- [x] 5.2 Run focused Python tests, full pytest, frontend build, frontend
  smoke checks, and `git diff --check`.
- [x] 5.3 Perform a configured-provider smoke check for both OpenAI relay and
  Qwen without exposing credentials or committing environment files.
