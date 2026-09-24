## Purpose

Deliver local image files to a multimodal model as OpenAI-format user content,
and let the CLI attach an image to a turn with an `@<path>` reference, so the
agent can see images without the model ever handling raw file bytes.

## ADDED Requirements

### Requirement: Image content part from a local file

The system SHALL build an OpenAI multimodal content list from a local image
file: a text part plus an `image_url` part whose URL is a base64 data URL with
a MIME type detected from the file.

#### Scenario: Valid PNG produces a data URL part

- **WHEN** the builder is called with the path of an existing PNG file and a
  text prompt
- **THEN** the result is a content list whose first entry is
  `{"type":"text","text":<prompt>}` and whose second entry is
  `{"type":"image_url","image_url":{"url":"data:image/png;base64,<payload>"}}`
- **AND** decoding `<payload>` yields the exact bytes of the file

#### Scenario: MIME type follows the file extension

- **WHEN** the builder is called with a `.jpg` (or `.jpeg`) file
- **THEN** the data URL prefix is `data:image/jpeg;base64,`

### Requirement: Bounded errors for bad image references

The system SHALL report image-reference failures as structured errors without
raising uncaught exceptions into the caller's turn.

#### Scenario: Missing file

- **WHEN** the builder is called with a path that does not exist
- **THEN** it raises a `FileNotFoundError` (or returns a structured error in
  tool contexts) naming the path, and no partial content list is produced

#### Scenario: CLI references a nonexistent image

- **WHEN** the agent REPL input contains `@path` and `path` does not exist (or
  is not a readable file)
- **THEN** the REPL prints an error line for that turn and keeps the session
  alive, without sending anything to the model

### Requirement: CLI attaches images with @path references

The agent REPL SHALL parse `@<path>` tokens in the input line: each referenced
image is attached to that user turn as an image content part, and the remaining
text forms the text part. Input without `@` MUST behave exactly as before
(string user turn).

#### Scenario: Single image reference

- **WHEN** the user enters `read this chart @/tmp/sales.png` in the agent REPL
- **THEN** the agent receives a multimodal content list containing the text
  `read this chart` and the image at `/tmp/sales.png`

#### Scenario: Plain text unchanged

- **WHEN** the user enters a line containing no `@` token
- **THEN** the agent receives the plain string exactly as today

#### Scenario: Multiple image references

- **WHEN** the user enters a line with two `@<path>` tokens
- **THEN** the content list carries the text part followed by both image parts
  in reference order
