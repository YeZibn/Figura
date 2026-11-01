## MODIFIED Requirements

### Requirement: Provider calls support bounded text, image, and function-tool inputs
Figura SHALL translate bounded inputs into the selected Provider's explicitly supported OpenAI-compatible Chat Completions contract. Each allowlisted Provider/model SHALL declare whether native multimodal tool results are supported. A supported result SHALL preserve one tool_call_id and ordered text/image parts inside that logical tool result. Figura SHALL preserve message order, role, exact opaque tool-call/result association, and originating image resource identity. Internal TOOL image content SHALL NOT be prohibited by a universal user-only rule.

The shared execution-payload contract SHALL protect complete structured requests without generic message, instruction, tool, call, image-count or small text/Schema limits. Optional completion limits SHALL be positive integers when selected and otherwise omitted; there SHALL be no universal 4096 default or 131072 maximum. Provider-specific parameter names, genuine ranges and capabilities SHALL stay local to its contract. Images SHALL retain existing source byte/decode protections and be encoded only for outbound requests, never ordinary logs or metadata.

Unsupported tool-result images or unrepresentable schemas SHALL cause an explicit local unsupported_capability before attempt claim or dispatch. Figura SHALL NOT silently append plain user images, strip media, relax constraints, switch Provider/model or select another API protocol. Known unsupported visual tool configurations SHALL be rejected before the ordinary model action that would expose the visual tool surface. Native capability enablement for each configured model SHALL have exact-contract evidence and an actual image-recognition acceptance result; HTTP success alone SHALL NOT be reported as visual acceptance.

#### Scenario: Text conversation is sent
- **WHEN** a caller submits ordered text messages
- **THEN** the selected provider receives the same semantic roles and message order through its supported request format

#### Scenario: Authorized image bytes are included
- **WHEN** a caller supplies an in-memory image with a supported media type
- **THEN** Figura encodes it in the provider-supported image content format without publishing a local path or image bytes to logs

#### Scenario: Function tools are included
- **WHEN** a caller supplies supported function tool schemas
- **THEN** Figura sends the schemas and normalizes returned tool calls; if the provider cannot represent a schema faithfully, Figura rejects the request instead of relaxing it

#### Scenario: Omit an unspecified completion limit
- **WHEN** no explicit completion limit is configured for the selected Provider
- **THEN** Figura omits the output-limit wire parameter and uses the Provider service default without reserving cumulative Run tokens

#### Scenario: Honor an explicit supported completion limit
- **WHEN** a positive explicit output limit is supported by the selected Provider
- **THEN** Figura sends it using that Provider's actual parameter contract rather than a universal maximum

#### Scenario: Send a native multimodal tool result
- **WHEN** the selected fixed model supports native tool-result images and a result has one or more authorized image blocks
- **THEN** the outbound tool result contains its text and image parts under the same tool_call_id with no extra plain user image message

#### Scenario: Reject unsupported tool-result images without fallback
- **WHEN** the selected model cannot faithfully represent multimodal tool results
- **THEN** Figura reports unsupported_capability before claim or dispatch and neither drops images nor changes the result into ordinary user input

#### Scenario: Validate real image visibility before enabling support
- **WHEN** a Provider accepts a minimal two-call image task whose textual metadata does not reveal the answers
- **THEN** support is enabled only after the model identifies each image's visible feature and associates it with the correct call, with unsupported or unverified models explicitly reported
