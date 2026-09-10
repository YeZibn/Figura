## MODIFIED Requirements

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
