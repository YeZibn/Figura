# Proposal: add-image-input

## Why

The configured model endpoint is multimodal (qwen3.8-flash can see images), but
the current pipeline cannot deliver an image to it: `Agent.run` only accepts a
plain string, and the CLI REPL only reads text lines. Chart understanding (the
next change) requires the agent to actually look at chart images, so the
multimodal input path must exist first.

## What Changes

- Add an image content-part builder: given a local image path, produce an
  OpenAI-format multimodal content list
  (`[{"type":"text",...},{"type":"image_url","image_url":{"url":"data:image/...;base64,..."}}]`)
  with MIME type detected from the file.
- `Agent.run` accepts either a plain string or a multimodal content list as the
  user turn; the value is passed through into history and to the client
  unchanged. Existing string behavior is untouched.
- The agent REPL (`--agent`) recognizes an `@<path>` token in the input line:
  the referenced image is attached to that turn as a content part, and the
  remaining text becomes the text part. Plain input without `@` behaves exactly
  as before.
- No changes to the LLM client (it already forwards message content verbatim),
  no changes to tools, no streaming.

## Capabilities

### New Capabilities

- `multimodal-input`: building OpenAI multimodal user content from local image
  files (base64 data URL, MIME detection, bounded error handling) and exposing
  it through the CLI `@path` reference syntax.

### Modified Capabilities

- `agent-loop`: `Agent.run` input widens from string-only to
  string-or-multimodal-content; history and client forwarding semantics
  unchanged.

## Impact

- New module: `src/chartagent/multimodal.py` (image part builder).
- Modified: `src/chartagent/agent.py` (run signature), `src/chartagent/cli.py`
  (`@path` parsing in the agent REPL).
- Dependencies: stdlib only (`base64`, `mimetypes`, `pathlib`). No new packages.
- Known cost accepted for U0: base64 images persist in in-memory history and
  are re-sent every turn; history slimming is out of scope.
