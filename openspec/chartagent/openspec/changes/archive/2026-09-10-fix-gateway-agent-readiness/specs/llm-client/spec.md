## MODIFIED Requirements

### Requirement: OpenAI-compatible endpoint configuration layering

The client SHALL resolve connection and behavior configuration with the precedence: explicit parameters > process environment variables > values loaded from an explicitly supplied runtime environment file or stable project fallback > default values. The client MUST support `DASHSCOPE_API_KEY` as the environment-variable credential source, MUST use `DASHSCOPE_BASE_URL` (falling back to a built-in default Alibaba compatible-mode endpoint) as `base_url`, and MUST allow an explicit `base_url` to override any default endpoint. A default model (`DASH_MODEL`) SHALL be configurable and usable when a call omits `model`. Environment loading MUST produce the same result when the Gateway is launched from the repository root or the `frontend` directory, and MUST NOT log credential values.

#### Scenario: Explicit parameters take precedence over environment variables

- **WHEN** a caller supplies an explicit `base_url` and API key while the corresponding environment variables are also set
- **THEN** the client uses the explicit values and issues calls against the explicit endpoint / credential

#### Scenario: Process environment takes precedence over the runtime environment file

- **WHEN** a runtime environment file contains provider settings and the same setting is already present in the process environment
- **THEN** the process environment value wins and the file value is not used for that key

#### Scenario: Runtime configuration is stable across launch directories

- **WHEN** the Gateway is launched from the repository root or the `frontend` directory with the documented runtime configuration contract
- **THEN** the client resolves the same provider key, endpoint, and model values without requiring a duplicate `frontend/.env` file

#### Scenario: Defaults used when nothing is configured

- **WHEN** no explicit parameter and no relevant environment variable or environment file value is set
- **THEN** the client falls back to built-in default values for the endpoint and behavior settings, and reports missing credentials through the existing bounded configuration error when an authenticated client is constructed
