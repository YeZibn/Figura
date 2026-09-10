## 1. Gateway protocol and session projection

- [x] 1.1 Define typed gateway request, response, error, session-summary, and completed-text-transcript models independent of SQLite and provider classes.
- [x] 1.2 Add bounded session-store queries needed to list and resolve durable named sessions by opaque session ID without exposing raw database rows.
- [x] 1.3 Implement completed-run projection that produces ordered user and final assistant text records and excludes interrupted or failed runs.
- [x] 1.4 Add unit tests for protocol validation, session ordering, ID resolution, transcript projection, and safe handling of absent or partial data.

## 2. Agent service and local HTTP gateway

- [x] 2.1 Extract reusable named-session Agent construction from the CLI so the gateway and CLI register equivalent built-in, chart, and attachment-loading capabilities.
- [x] 2.2 Implement gateway service operations for health, listing sessions, creating sessions, reading a session transcript, and executing a non-empty text message synchronously.
- [x] 2.3 Implement a loopback-only HTTP/JSON server entry point with versioned routes, request-size limits, JSON parsing, local-development CORS allowlist, and configurable safe host/port defaults.
- [x] 2.4 Map validation, duplicate-name, not-found, provider-configuration, and Agent execution failures to bounded structured HTTP errors without tracebacks or sensitive content.
- [x] 2.5 Add API tests with fake Agent/client dependencies for successful lifecycle and message flows, malformed requests, invalid input, errors, loopback defaults, and response sanitization.

## 3. Desktop gateway adapter

- [x] 3.1 Implement a frontend `gatewayClient` that maps gateway session and transcript JSON into the existing `ChartAgentClient` and frontend protocol types.
- [x] 3.2 Add explicit Vite environment configuration for `mock` and `gateway` modes, keeping mock as the default and surfacing gateway failures rather than silently switching data sources.
- [x] 3.3 Update workspace state and presentation for gateway loading and structured error responses while preserving current mock-mode behavior and Simplified Chinese user-visible copy.
- [x] 3.4 Add repeatable frontend adapter tests or smoke coverage for gateway session listing, creation, retrieval, text submission, loading, and failure states.

## 4. Verification and developer workflow

- [x] 4.1 Document loopback gateway and browser-client startup commands, using `conda run -n agent` for all Python commands and the explicit frontend mode configuration.
- [x] 4.2 Run the Python gateway tests, existing Python regression suite, frontend build, frontend smoke checks, and strict OpenSpec validation.
- [x] 4.3 Manually verify mock and gateway browser workflows without a Tauri window, including session creation, persisted-session reload, successful text turn with configured provider, and bounded unavailable-provider feedback.
