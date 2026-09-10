# desktop-runtime Specification

## Purpose

Provide a Tauri-owned local runtime boundary that starts and supervises the Python Gateway for the desktop workspace, reports readiness clearly, and shuts down only the process owned by the current desktop instance.

## Requirements

### Requirement: Tauri manages the local Gateway lifecycle

The desktop runtime SHALL start the configured local Python Gateway when the workspace is launched in Gateway mode, keep the Gateway bound to the loopback interface, and track the owned process through starting, ready, unavailable, and stopped states. Mock mode SHALL remain independent of the Gateway process.

#### Scenario: Gateway mode reaches readiness

- **WHEN** the desktop client starts with Gateway mode enabled and the configured local runtime is available
- **THEN** Tauri starts one owned Gateway process, waits for a compatible health response, and exposes a ready state to the React client

#### Scenario: Gateway startup fails

- **WHEN** the Gateway cannot be launched or does not become healthy within the bounded startup window
- **THEN** the desktop client shows a Simplified Chinese unavailable state with an actionable error and does not silently switch to mock data

#### Scenario: Mock mode does not start Python

- **WHEN** the desktop client starts in mock mode
- **THEN** it remains usable without a Python process, provider credentials, or a running Gateway

### Requirement: Desktop shutdown is scoped to the owned Gateway

When the desktop application closes, the runtime SHALL request graceful shutdown of the Gateway process it started and SHALL NOT terminate an unrelated Gateway or process using the same machine.

#### Scenario: Application closes after starting Gateway

- **WHEN** the user closes a desktop instance that owns a Gateway process
- **THEN** the runtime releases the process it owns and the next desktop launch can bind the configured local endpoint without a stale child process

#### Scenario: Application connects to an externally managed Gateway

- **WHEN** the desktop client is configured to use an already running compatible Gateway it did not start
- **THEN** application shutdown leaves that external process running

### Requirement: Development runtime honors the agent environment contract

Development and test startup paths that execute Python project code SHALL use the Conda environment named `agent` or an explicitly configured equivalent, and SHALL not depend on a machine-specific absolute interpreter path.

#### Scenario: Standard development startup

- **WHEN** a developer starts the local desktop runtime using the documented project command
- **THEN** the Python Gateway runs with the `agent` environment and the client can verify its compatible version through health

#### Scenario: Configured runtime is unavailable

- **WHEN** the configured Python or environment cannot be resolved
- **THEN** startup fails with a bounded diagnostic that identifies runtime availability without exposing credentials or unrelated filesystem contents

### Requirement: Development provides one-step Gateway client startup

The development workspace SHALL provide one documented command that starts the Gateway-mode client and its local Python Gateway as one supervised workflow. Startup SHALL wait for a compatible Gateway health response before reporting the client ready, SHALL use the `agent` Conda environment by default, and SHALL clean up only processes created by that workflow when it exits. After a termination signal or a child startup failure, the workflow SHALL signal all processes it owns, wait for their bounded termination, and SHALL NOT exit while an owned child process remains running.

#### Scenario: Unified browser development startup

- **WHEN** a developer runs the documented Gateway development command
- **THEN** the Gateway starts in the `agent` environment, the React client starts in explicit Gateway mode after health readiness, and the client does not use mock data

#### Scenario: Unified startup cannot reach readiness

- **WHEN** the Gateway process cannot start or does not become healthy within the bounded startup window
- **THEN** the launcher reports a bounded Chinese-language error, does not claim the client is ready, and does not silently switch to mock mode

#### Scenario: Unified startup exits

- **WHEN** the developer stops the unified development workflow with `Ctrl-C` or the workflow receives a termination signal
- **THEN** the launcher signals the Gateway and client processes it created, waits for both process groups to terminate, and leaves their configured ports available without terminating an unrelated process

#### Scenario: Client startup fails after Gateway readiness

- **WHEN** the Gateway becomes ready but the client cannot bind its configured frontend port
- **THEN** the launcher reports the client startup failure, terminates the Gateway process it created, and preserves any unrelated service that occupied the port

#### Scenario: Tauri Gateway development alias

- **WHEN** a developer starts the documented Tauri Gateway-mode command
- **THEN** Tauri starts with Gateway mode enabled and remains the owner responsible for the Gateway child's startup, readiness, and shutdown cleanup
