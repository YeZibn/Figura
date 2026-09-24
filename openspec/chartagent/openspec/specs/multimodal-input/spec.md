# multimodal-input Specification

## Purpose

Deliver local image files to a multimodal model as OpenAI-format user content,
and let the CLI attach an image to a turn with an `@<path>` reference, so the
agent can see images without the model ever handling raw file bytes.

## Requirements

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

 The agent REPL SHALL parse unquoted `@<path>` tokens and quoted
 `@"<path with spaces>"` tokens in the input line. Each reference SHALL be
 registered as a session-scoped attachment in matching order. The first
 model-visible turn SHALL contain only remaining text, opaque attachment IDs,
 and safe metadata; it SHALL NOT eagerly include image bytes, data URLs, or
 arbitrary local paths. Input without an attachment reference MUST behave
 exactly as before as a plain string user turn.

#### Scenario: Single image reference

- **WHEN** the user enters `read this chart @/tmp/sales.png` in the agent REPL
- **THEN** the agent receives the user text and one opaque attachment ID, while
  the first model request contains no image bytes or local path

#### Scenario: Plain text unchanged

- **WHEN** the user enters a line containing no attachment reference
- **THEN** the agent receives the original plain string without attachment
  metadata or multimodal conversion

#### Scenario: Multiple image references

- **WHEN** the user enters a line with two image attachment references
- **THEN** two attachment IDs and safe metadata appear in the same order without
  eager image content

#### Scenario: Quoted image path containing spaces

- **WHEN** the user enters `compare @"/tmp/chart one.png" with @/tmp/two.png`
- **THEN** the first attachment resolves to `/tmp/chart one.png`, the second
  resolves to `/tmp/two.png`, and the remaining user text is `compare with`
