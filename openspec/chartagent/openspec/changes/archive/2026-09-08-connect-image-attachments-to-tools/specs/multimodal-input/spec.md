## MODIFIED Requirements

### Requirement: CLI attaches images with @path references

The agent REPL SHALL parse unquoted `@<path>` tokens and quoted
`@"<path with spaces>"` tokens in the input line. Each referenced image SHALL
be attached to that user turn as an image content part, and the model-visible
text SHALL contain the remaining user text plus the resolved local image paths
in matching order so image tools can address them. Input without an attachment
reference MUST behave exactly as before as a plain string user turn.

#### Scenario: Single image reference

- **WHEN** the user enters `read this chart @/tmp/sales.png` in the agent REPL
- **THEN** the agent receives a multimodal content list containing the user text,
  the local path `/tmp/sales.png`, and the corresponding image

#### Scenario: Plain text unchanged

- **WHEN** the user enters a line containing no attachment reference
- **THEN** the agent receives the original plain string without attachment
  metadata or multimodal conversion

#### Scenario: Multiple image references

- **WHEN** the user enters a line with two image attachment references
- **THEN** the model-visible paths and image content parts appear in the same
  order as their references

#### Scenario: Quoted image path containing spaces

- **WHEN** the user enters `compare @"/tmp/chart one.png" with @/tmp/two.png`
- **THEN** the first attachment resolves to `/tmp/chart one.png`, the second
  resolves to `/tmp/two.png`, and the remaining user text is `compare with`
