## Context

The low-level multimodal builder accepts text plus image paths and emits one
text part followed by base64 image parts. The agent REPL currently removes all
`@path` tokens before calling that builder, while `extract_text` and
`measure_bars` require the model to provide an `image_path`. The live smoke
avoids the mismatch with a separate path-bearing prompt and a prescriptive
system prompt, so it does not exercise the normal REPL contract.

The generic `Agent` already forwards multimodal content, advertises registered
tools, and allows the model to plan freely. This change should connect those
existing pieces rather than add an orchestration layer.

## Goals / Non-Goals

**Goals:**

- Give the model enough attachment metadata to call existing local-image tools.
- Keep REPL and live-smoke turn construction on one shared code path.
- Support quoted paths containing spaces alongside the current syntax.
- Provide useful chart-domain defaults without imposing a workflow.
- Preserve byte-for-byte plain-string turns when no image is attached.

**Non-Goals:**

- Sandboxing or replacing path-based tools with opaque attachment references.
- Enforcing tool selection, call order, ChartSpec output, or validation.
- Adding a dedicated chart-understanding CLI mode or a higher-level session API.
- Expanding chart types, CV/OCR capability, or history management.

## Decisions

### D1: Add a shared agent-turn builder beside the raw multimodal builder

Add a helper in `multimodal.py` that receives user text and ordered image paths,
formats a clearly delimited list of local paths into the text part, and delegates
image encoding to the existing `build_user_content`. The agent REPL and live
smoke both use this helper.

`build_user_content` remains unchanged as the raw programmatic primitive, so
existing callers and its exact text-part contract remain compatible. Formatting
path metadata in standard text is supported by every OpenAI-compatible endpoint
and does not rely on provider-specific content fields.

Alternative considered: append the original `@path` expression unchanged. This
mixes attachment syntax with user intent and is ambiguous for multiple or quoted
paths. A separate labeled block gives the model an explicit image-part order.

### D2: Expose paths in attachment order without constraining their use

The generated text ends with a stable block equivalent to:

```text
Attached local image paths (matching image order):
1. /tmp/first.png
2. /tmp/second.png
```

The helper uses the same path sequence for this block and for image encoding.
It does not instruct the model to call a tool. The existing `image_path` tool
schemas and dispatch behavior remain unchanged.

Alternative considered: opaque attachment references with a resolver. That
would avoid disclosing local paths but requires contextual dispatch, tool-schema
changes, and attachment lifecycle state. The user explicitly prefers free tool
planning, and the current tool surface already accepts local paths, so that
larger security boundary is deferred.

### D3: Parse quoted and unquoted references in the CLI layer

Replace the current unquoted-only expression with parsing that recognizes both
`@/tmp/chart.png` and `@"/tmp/chart one.png"`. Matching removes the complete
reference, keeps paths in encounter order, then applies the existing whitespace
normalization to the remaining user text. Unterminated quoted references are
left as text rather than guessed.

Parsing remains in `cli.py`; neither `Agent` nor the raw multimodal builder owns
command-line syntax.

### D4: Use an advisory ChartAgent system prompt

The default prompt for `run_agent_repl` identifies the agent as a chart-capable
assistant and briefly describes visual inspection, OCR, geometry measurement,
ChartSpec assembly, and validation as available choices. It explicitly tells
the model to select tools only when useful and to answer naturally unless the
user requests structured output.

An explicitly supplied `system` value still overrides the default. The generic
chat REPL and `Agent` defaults outside this entry point do not change.

Alternative considered: encode the U0 smoke's required sequence in the default
prompt. This was rejected because it would force unnecessary extraction and
ChartSpec work for descriptive image questions.

### D5: Live acceptance observes outcomes, not a fixed trajectory

The live smoke uses the shared turn builder and the REPL's default system prompt.
Its user message requests data restoration but does not repeat the path or name
a tool sequence. Acceptance checks that the returned ChartSpec validates and its
dataset matches ground truth. Called tools may be reported diagnostically but
their exact sequence is not an assertion.

Offline tests remain deterministic: they verify parsing, path/image ordering,
prompt defaults, and forwarding. The live test remains manual because model tool
choice is intentionally nondeterministic.

## Risks / Trade-offs

- [Local paths are sent to the configured model endpoint] -> Limit metadata to
  paths the user explicitly attached and document this behavior; opaque refs are
  a future security-focused change.
- [A free model may skip useful tools or return unvalidated data] -> Keep tool
  descriptions and the advisory domain prompt clear, and measure reliability in
  the live smoke without presenting it as a hard guarantee.
- [Quoted parsing does not implement full shell syntax] -> Support only the
  documented double-quoted form and leave malformed references untouched.
- [Live acceptance may fluctuate across model versions] -> Preserve strong
  offline contract tests and report the actual tool trace when a smoke fails.

## Migration Plan

No data migration is required. Existing plain turns and direct
`build_user_content` callers remain unchanged. Rollback consists of reverting
the REPL helper call, parser, default prompt, and smoke changes together.
