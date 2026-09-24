## Why

Figura currently treats the configured OpenAI-compatible endpoint as the only
provider, while the project needs to restore Qwen support alongside the
existing OpenAI relay. Users should be able to choose the provider from the
frontend without exposing credentials or changing the behavior of an already
running Agent task.

## What Changes

- Add an explicit `openai` / `qwen` provider configuration boundary selected by
  `CHARTAGENT_PROVIDER` for the default and by a bounded provider value for a
  frontend-started run.
- Keep OpenAI requests on the existing `OPENAI_BASE_URL` relay and isolate
  Qwen credentials, endpoint, model, and `enable_thinking` settings under
  `QWEN_*` variables, with documented legacy DashScope aliases.
- Adapt Qwen-compatible responses and requests to the existing normalized LLM
  result, tool-call, reasoning, timeout, and observation contracts.
- Allow the Gateway API and frontend to select a provider per run, snapshot it
  for that run, and expose safe provider/model metadata in health, run events,
  and run history.
- Add a frontend provider selector and keep the mock client on the same API
  contract for offline development.
- Return bounded readiness and validation errors for unavailable or unsupported
  providers without exposing keys, raw endpoints, or provider payloads.

## Capabilities

### New Capabilities

- `provider-selection`: Provider selection, capability reporting, and
  per-run provider snapshot semantics shared by the Gateway and frontend.

### Modified Capabilities

- `llm-client`: Resolve separate OpenAI/Qwen configuration and apply
  provider-specific request and response handling.
- `python-gateway`: Accept a bounded provider on run requests and report safe
  provider readiness and run metadata.
- `desktop-client`: Let users select the provider and send the selection with
  the next run while rendering the effective provider safely.
- `execution-trace`: Preserve provider/model metadata without exposing
  credentials and keep it stable across live and historical run views.

## Impact

- Python client configuration, request construction, normalization, readiness,
  runtime creation, Gateway protocol/service, run persistence, and tests.
- React client API types, Gateway adapter, mock adapter, provider selector, and
  visible run/status presentation.
- `.env.example` and OpenSpec specifications; no new SDK dependency is needed
  because Qwen uses the existing OpenAI-compatible SDK.
