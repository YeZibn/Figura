## MODIFIED Requirements

### Requirement: Tauri manages the local Gateway lifecycle

The desktop runtime SHALL start the configured local Python Gateway when the workspace is launched in Gateway mode, keep the Gateway bound to the loopback interface, and track Gateway HTTP availability separately from Agent readiness through starting, ready, unavailable, and stopped states. Mock mode SHALL remain independent of the Gateway process.

#### Scenario: Gateway mode reaches readiness

- **WHEN** the desktop client starts with Gateway mode enabled and the configured local runtime and Agent configuration are available
- **THEN** Tauri starts one owned Gateway process, waits for a compatible HTTP health response, and exposes both a ready Gateway state and a ready Agent state to the React client

#### Scenario: Gateway starts but Agent configuration is unavailable

- **WHEN** the Gateway responds to HTTP health checks but the Agent cannot be configured because required provider configuration is missing or invalid
- **THEN** the desktop client remains in Gateway mode, exposes the Gateway as available and the Agent as unavailable, shows a Simplified Chinese actionable configuration message, and does not silently switch to mock data

#### Scenario: Gateway startup fails

- **WHEN** the Gateway cannot be launched or does not become healthy within the bounded startup window
- **THEN** the desktop client shows a Simplified Chinese unavailable state with an actionable runtime error and does not silently switch to mock data

#### Scenario: Mock mode does not start Python

- **WHEN** the desktop client starts in mock mode
- **THEN** it remains usable without a Python process, provider credentials, or a running Gateway

### Requirement: Development runtime honors the agent environment contract

Development and test startup paths that execute Python project code SHALL use the Conda environment named `agent` or an explicitly configured equivalent, SHALL resolve model configuration through an explicit runtime configuration contract or a stable project fallback rather than only the current working directory, and SHALL not depend on a machine-specific absolute interpreter path.

#### Scenario: Standard development startup from the frontend directory

- **WHEN** a developer starts the local desktop runtime using the documented project command from the `frontend` directory
- **THEN** the Python Gateway runs with the `agent` environment, loads the same project configuration used from the repository root, and the client can verify separate Gateway and Agent readiness states through health

#### Scenario: Configured runtime is unavailable

- **WHEN** the configured Python or environment cannot be resolved
- **THEN** startup fails with a bounded diagnostic that identifies runtime availability without exposing credentials or unrelated filesystem contents

### Requirement: Development provides one-step Gateway client startup

The development workspace SHALL provide one documented command that starts the Gateway-mode client and its local Python Gateway as one supervised workflow. Startup SHALL wait for a compatible Gateway HTTP health response before reporting the local service ready, SHALL expose Agent configuration readiness separately, SHALL use the `agent` Conda environment by default, and SHALL clean up only processes created by that workflow when it exits. After a termination signal or a child startup failure, the workflow SHALL signal all processes it owns, wait for their bounded termination, and SHALL NOT exit while an owned child process remains running.

#### Scenario: Unified browser development startup

- **WHEN** a developer runs the documented Gateway development command
- **THEN** the Gateway starts in the `agent` environment, the React client starts in explicit Gateway mode after HTTP readiness, the runtime passes the configured environment-file contract to the Gateway, and the client does not use mock data

#### Scenario: Unified startup reports missing Agent configuration

- **WHEN** the Gateway HTTP service becomes ready but the Agent configuration check reports an unavailable Agent
- **THEN** the launcher keeps the Gateway-mode client available, the client shows the safe Agent configuration diagnosis, and the workflow does not claim that the Agent is ready or silently switch to mock mode

#### Scenario: Unified startup cannot reach HTTP readiness

- **WHEN** the Gateway process cannot start or does not become healthy within the bounded startup window
- **THEN** the launcher reports a bounded Chinese-language error, does not claim the local service is ready, and does not silently switch to mock mode

#### Scenario: Unified startup exits

- **WHEN** the developer stops the unified development workflow with `Ctrl-C` or the workflow receives a termination signal
- **THEN** the launcher signals the Gateway and client processes it created, waits for both process groups to terminate, and leaves their configured ports available without terminating an unrelated process

#### Scenario: Client startup fails after Gateway readiness

- **WHEN** the Gateway becomes ready but the client cannot bind its configured frontend port
- **THEN** the launcher reports the client startup failure, terminates the Gateway process it created, and preserves any unrelated service that occupied the port

#### Scenario: Tauri Gateway development alias

- **WHEN** a developer starts the documented Tauri Gateway-mode command
- **THEN** Tauri starts with Gateway mode enabled, passes the same environment-file contract as the browser workflow, and remains the owner responsible for the Gateway child's startup, readiness, and shutdown cleanup
