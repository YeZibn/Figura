## MODIFIED Requirements

### Requirement: CLI attaches images with @path references

The agent REPL SHALL parse unquoted `@<path>` tokens and quoted
`@"<path with spaces>"` tokens in the input line. Each valid reference SHALL
be registered as an authorized attachment in matching order, and the
model-visible user text SHALL contain the remaining user text plus opaque
attachment IDs and safe metadata. The CLI SHALL NOT eagerly include image bytes,
base64 data URLs, or arbitrary local paths in that first model request. Input
without an attachment reference MUST behave exactly as before as a plain string
user turn.

#### Scenario: Single image reference

- **WHEN** the user enters `read this chart @/tmp/sales.png` in the agent REPL
- **THEN** the Agent receives the user text and one registered attachment ID,
  while the first model request contains no image bytes or local path

#### Scenario: Plain text unchanged

- **WHEN** the user enters a line containing no attachment reference
- **THEN** the Agent receives the original plain string without attachment
  metadata or multimodal conversion

#### Scenario: Multiple image references

- **WHEN** the user enters a line with two valid image attachment references
- **THEN** two attachment IDs and their safe metadata appear in the same order
  as the references, without eager image content

#### Scenario: Quoted image path containing spaces

- **WHEN** the user enters `compare @"/tmp/chart one.png" with @/tmp/two.png`
- **THEN** both files are registered in reference order and the remaining user
  text is `compare with`

