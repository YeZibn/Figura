## Context

The Gateway is launched from `frontend` by the development workflow, while the provider `.env` currently lives at the repository root and is loaded through a relative path. The Gateway health endpoint only proves that the HTTP server is listening; Agent construction is deferred until a run starts, so missing credentials are surfaced late as a generic `agent_unavailable` failure. The browser launcher, Tauri supervisor, and React client also use separate readiness views.

The existing local-only boundary, `agent` Conda environment, mock adapter, asynchronous run protocol, and credential-redacting error contract must remain compatible.

## Goals / Non-Goals

**Goals:**

- Make provider configuration resolution independent of whether the workflow starts from the repository root or `frontend`.
- Give both browser and Tauri workflows one explicit environment-file contract.
- Preserve a fast local HTTP readiness gate while reporting Agent configuration readiness separately.
- Provide stable, non-sensitive reason codes for missing or invalid Agent configuration.
- Keep mock mode, external Gateway ownership, loopback binding, and shutdown behavior unchanged.

**Non-Goals:**

- Validating provider network connectivity or making a model request during Gateway startup.
- Moving credentials into frontend source, Vite variables, SQLite, or HTTP responses.
- Replacing the existing Gateway protocol, session model, streaming events, or Agent tool loop.
- Packaging a production credential-management system for installed desktop builds.

## Decisions

### 1. Use an explicit runtime environment-file contract

The launchers SHALL resolve the repository-level environment file and pass its path through `CHARTAGENT_ENV_FILE`. Python configuration loading SHALL accept that path, with an explicit function argument taking precedence, and SHALL retain process environment precedence over file values. A stable source-tree fallback may be used for direct local commands, but current-working-directory lookup alone is not sufficient.

This keeps the credential file in the Python runtime boundary and avoids duplicating it as `frontend/.env` or exposing it to Vite. Setting the child working directory alone was rejected because it fixes one development path but does not give the Tauri supervisor or future packaged launchers a durable contract.

### 2. Keep HTTP health and Agent readiness as separate dimensions

The existing health response remains HTTP-successful when the Gateway server is running, preserving the launcher port/readiness gate. It gains a bounded `agent` status object containing only a readiness state and safe reason code. The status is based on configuration loading and client construction checks, not a provider network request.

This allows the UI to start and explain a missing local configuration without confusing it with a dead Gateway, while avoiding slow or flaky startup caused by an external provider call. The launcher continues to gate on compatible HTTP health; the client and Tauri supervisor render the Agent sub-status separately.

### 3. Preserve stable failure codes and redact details at the boundary

Provider setup failures continue to use the existing `agent_unavailable` category for run compatibility, with an optional bounded reason such as `missing_configuration`, `invalid_configuration`, or `initialization_failed`. Raw exception strings, credentials, provider responses, and local file contents remain internal. The frontend maps the safe reason to a concise Simplified Chinese action, while unknown reasons use a generic fallback.

### 4. Share status semantics across browser and Tauri clients

The browser client will request the Gateway health payload when Gateway mode starts. The Tauri supervisor will parse the same health fields for its runtime status command. Both clients will show Gateway HTTP availability and Agent readiness independently; neither path may switch to `mockClient` after Gateway mode has been selected.

### 5. Test configuration and readiness as contracts

Python tests will exercise environment precedence and launches from both relevant working directories without printing secret values. Gateway tests will cover health status, safe reason codes, and run-history preservation. Node launcher smoke tests will verify the environment-file contract and existing process cleanup. Rust tests will cover supervisor parsing and the distinction between Gateway availability and Agent readiness. All Python commands and tests use `conda run -n agent`.

## Risks / Trade-offs

- [Risk] A configured API key can still be expired or rejected by the provider after startup. → Keep startup validation configuration-only and report provider request failures separately as Agent execution failures.
- [Risk] Existing clients may ignore the new nested health field. → Preserve the existing top-level `version` and HTTP `status` fields and treat the Agent field as additive.
- [Risk] A missing environment file in a packaged or externally managed runtime remains a user setup issue. → Support an explicit `CHARTAGENT_ENV_FILE` override and return a safe actionable configuration status without exposing the path contents.
- [Risk] Environment values loaded into a long-lived process can become stale after the file changes. → Keep the explicit runtime path, make status refreshable through the existing health request, and document restart/retry as the recovery boundary if the process has already cached configuration.

## Migration Plan

1. Add the shared environment-file resolution and safe Agent readiness payload behind the existing v1 Gateway contract.
2. Update the browser launcher, Tauri development alias, Rust supervisor, and React status mapping together.
3. Run Python, Node, and Rust contract tests, then verify the normal one-step command from both repository root and `frontend`.
4. Roll back by reverting the launcher/configuration and status changes; the existing top-level health fields and mock mode remain compatible during the transition.
