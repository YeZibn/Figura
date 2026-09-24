## Context

See proposal.md - Why. This is the first change in a greenfield project, so there
is no existing code to integrate with. The architecture must support future
additions (agent loop, tool system, MCP, chart reading/generation) by giving them
a stable, controllable LLM calling layer. Technology is already decided: use the
official `openai` Python SDK as the wire transport against the Alibaba Cloud
compatible-mode (OpenAI-compatible) deployment, credentials and endpoint loaded
from `DASHSCOPE_API_KEY` / `DASHSCOPE_BASE_URL` via `python-dotenv` (`.env`).

## Goals / Non-Goals

**Goals:**
- Wrap the `openai` SDK with a thin client layer that owns all the controllable
  logic, so provider quirks stay out of the SDK-touching code and out of callers.
- One normalized result shape across providers: `{ content, reasoning,
  tool_calls, finish_reason, usage, raw }`.
- Config layering with explicit precedence and explicit knobs (thinking toggle,
  retry, timeout).
- Correct isolation of non-standard `reasoning_content` so it never pollutes
  multi-turn assistant history (which causes provider-side 400s).

**Non-Goals:**
- No agent loop, no tool execution/dispatch system, no MCP integration, no chart
  reading/generation in this change. Implementation stops at the LLM client.

## Decisions

**1. `openai` SDK as transport + thin client wrapper.**
Use the official `openai` SDK purely as a transport (it already handles
streaming, HTTP, auth plumbing, tool-arg parsing). Lay the controllable logic —
config layering, knob-to-`extra_body` translation, output normalization,
reasoning isolation, history construction, retry, observation logging — in a
thin client layer above it.
- *Alternatives considered:* hand-rolled HTTP + `httpx` for full control, or
  provider-native SDKs. Rejected: hand-rolled re-implements streaming/tool-arg
  parsing already solved by the SDK; provider-native SDKs fragment the codebase
  per vendor and defeat the "one compatible-protocol client" goal. The SDK's
  OpenAI-compatible mode is the least common denominator against the chosen
  Alibaba compatible-mode endpoint.

**2. Config layering: explicit > env > default, with a typed config object.**
A single config resolver merges explicit params, environment variables, and
defaults into one typed object passed to the SDK client on construction. Only
the highest-priority source per key wins (so partial overrides are safe).
- *Alternative:* rely on `openai`'s own env handling. Rejected: it is not aware
  of our knob semantics and does not expose a clean typed surface for the
  reasoning/tool-call handling.

**3. Normalized result model with `raw` fallback.**
Every call (plain / tools / streaming) returns the same result object. `raw`
carries the untouched provider response so nothing provider-specific is lost
even if normalization misses a field. Tool calls come from the SDK's parsed
`tool_calls` and are surfaced in a normalized list.
- *Notes:* streaming aggregates deltas into the same shape; non-applicable
  fields are empty, never missing.

**4. Reasoning isolation via a history-construction contract.**
When the SDK surfaces non-standard reasoning (captured, for Qwen deep-thinking,
from `extra_body.enable_thinking` responses and exposed as an extra attribute by
the SDK — `reasoning_content`), the client copies it into `reasoning` and into
the observation/trace only. The history builder exposed by the client appends
assistant entries containing only `content`, never reasoning. This is the
single point that enforces the provider-side constraint that reasoning cannot be
echoed back.
- *Risk:* mixing SDK providers where the reasoning field name differs; mitigated
  by normalizing at the single thin layer so `reasoning` is the only name callers
  ever rely on.

**5. Explicit knobs compiled into `extra_body`.**
Provider-specific switches (e.g. `enable_thinking`) are explicit client options;
the client compiles them into the SDK's `extra_body` per call. No magic constants
leak into callers, and toggles are testable independently of the provider.

**6. Retry & timeout as explicit options; observation via callback/log.**
Retry count and timeout are typed options with defaults. A per-call structured
observation entry (model, elapsed, usage, finish_reason) is emitted through a
logging hook; secrets (API key) are never written.

**7. Environment via `.env` + `python-dotenv`; Alibaba compatible-mode default.**
A `load_environment()` helper (using `python-dotenv`) loads `.env` before config
resolution, so `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL`, and `DASH_MODEL` are
available as env sources while keeping the config layer's input contract
unchanged (it still only reads environment names). Default `base_url` points at
the target Alibaba compatible-mode deployment; a default model (`DASH_MODEL`)
lets callers omit `model`.
- *Note:* `.env` is excluded from version control (`.gitignore`); callers may
  also pass explicit params, which still take precedence over env/defaults.

## Risks / Trade-offs

- [Provider-specific quirks (e.g. thinking field naming) vary across vendors]
  → normalized at the single thin layer; `raw` fallback preserves everything.
- [`extra_body` keys may be vendor-namespaced differently] → documented in the
  knob layer and isolated so only the knob compile site knows vendor specifics.
- [Streaming aggregation ordering for reasoning vs content] → gather deltas by
  message/role/chunk and validate against the finished whole.
- [`raw` doubles memory for large responses] → acceptable for a client layer;
  callers may drop it.

## Migration Plan

No pre-existing code or deployment; nothing to migrate or roll back. This change
establishes the first module and its dependency.

## Open Questions

None that would change the specs, approach, or task breakdown.