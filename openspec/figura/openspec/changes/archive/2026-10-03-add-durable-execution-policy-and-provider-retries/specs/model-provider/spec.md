## MODIFIED Requirements

### Requirement: Provider calls support bounded text, image, and function-tool inputs
Figura SHALL translate its bounded call input into the selected provider's supported OpenAI-compatible Chat Completions request. The shared execution-payload contract SHALL protect complete structured requests; Figura SHALL NOT enforce generic message, instruction, tool, call, image-count or small text/Schema byte limits. Optional completion limits SHALL be positive integers when explicitly selected and SHALL otherwise be omitted from the outbound request; there SHALL be no universal 4096 default or 131072 maximum. Provider-specific output parameter names, genuine ranges and supported capabilities SHALL remain local to the selected Provider contract. Image content SHALL retain the existing source byte/decode protections. The input SHALL preserve message order, role, and tool-call/tool-result association. Image bytes SHALL be encoded only for the outbound request and SHALL NOT be written into ordinary logs or response metadata. A tool schema or input content that cannot be represented without weakening its constraints SHALL be rejected explicitly.

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

### Requirement: Provider failures are bounded and do not trigger implicit retries or fallback
Figura SHALL classify provider failures using bounded provider-neutral metadata that distinguishes a known rejection from an unknown remote outcome. The SDK SHALL NOT retry requests implicitly, and the transport SHALL NOT retry implicitly. The durable execution owner alone SHALL apply the explicit provider-request-retries contract; Figura SHALL NOT switch to another provider. Failure metadata SHALL distinguish outcome certainty, recognized temporary category and safe optional retry delay. Unrecognized exceptions SHALL NOT automatically be classified temporary. Raw provider exception bodies, credentials, and unrestricted response data SHALL NOT be exposed through the normalized failure.

#### Scenario: Request times out with an unknown remote outcome
- **WHEN** a timeout or transport interruption occurs without a definitive provider response
- **THEN** Figura reports an unknown outcome, does not itself resend the request or select fallback, and allows only the durable owner to assess a guarded generation-only replacement

#### Scenario: Provider returns a definitive rejection
- **WHEN** a provider returns a definitive error response
- **THEN** Figura reports a bounded failure category and safe message without exposing raw credentials or exception content

#### Scenario: Configure a long I/O timeout
- **WHEN** a Provider timeout is finite and positive but exceeds 600 seconds
- **THEN** Figura accepts the configuration without imposing a Run deadline; the timeout retains its I/O waiting semantics
