# Design: add-image-input

## Context

The agent loop (`agent.py`) and REPL (`cli.py`) are string-only today. The
endpoint is multimodal, so the only missing pieces are: a way to encode a local
image as an OpenAI content part, a widened `Agent.run` signature, and `@path`
parsing in the agent REPL. The client already forwards message content verbatim
and needs no change.

## Decisions

### D1: Standalone builder in `src/chartagent/multimodal.py`

- `build_user_content(text: str, image_paths: Sequence[str]) -> list[dict]`
  returns the OpenAI content list: text part first, then one image part per
  path in order.
- MIME via `mimetypes.guess_type` with an `image/...` allowlist check; unknown
  or non-image extensions raise `ValueError` naming the path.
- Encoding: whole-file `base64.b64encode`; no chunking, no resizing (U0 images
  are small synthetic charts).
- Rationale: one pure function, stdlib-only, trivially testable; the CLI and
  any future programmatic caller share it.

### D2: `Agent.run` widens its parameter type, not its behavior

- Signature becomes `run(self, user_input: str | list[dict])`; the append and
  forwarding code is unchanged (OpenAI types accept both). No content inspection
  inside the loop — the agent is transport, not policy.

### D3: `@path` parsing lives in the CLI, not the agent

- Regex `@(\S+)` over the input line; strip matched tokens from the text part,
  collect paths in order, call `build_user_content`.
- Zero matches → pass the original string (today's behavior, byte-identical).
- File errors are caught in the REPL loop and printed as
  `agent> [error] ...` — the turn is not sent, the session stays alive
  (mirrors the existing transient-error policy).
- Rationale: keeping parsing out of `Agent` preserves its single responsibility
  and lets library callers build content themselves.

### D4: Accepted cost — images persist in history

Base64 payloads stay in `self._messages` and are re-sent every turn. Accepted
for U0 (short single-turn sessions); slimming strategies (drop-after-read,
placeholder substitution) are deferred and explicitly out of scope.

## Risks

- Endpoint may reject data URLs in favor of hosted URLs — smoke-tested once
  during implementation; if rejected, this change is the place to add a
  fallback, not a new abstraction.
- `mimetypes` can be wrong for `.jpg` on some systems — the allowlist check
  plus explicit extension→MIME mapping for png/jpeg/gif/webp covers U0 formats.
