## 1. Durable Execution Port

- [x] 1.1 Define the shared `DurableExecutionPort` Protocol and explicit typed signatures for the seven durable operations.
- [x] 1.2 Implement a Gateway per-run port bound to the current `ManagedRun`, session, and history store; map its methods directly to existing durable persistence operations.
- [x] 1.3 Add port contract tests covering all operations, current run/session binding, and promotion of a parent-run staged chart after resume.

## 2. Runtime and Agent Wiring

- [x] 2.1 Replace the seven callback keyword arguments on `GatewayRuntimeFactory`, `GatewayService._build_runtime`, and `create_agent_runtime` with one `durable_execution_port` argument; require it for Gateway runtimes.
- [x] 2.2 Pass the same port through `Agent` to `GeneratedChartVerificationFlow`, replacing the seven stored callback fields.
- [x] 2.3 Update `AgentRunOrchestrator`, model turn execution, and tool execution to commit execution entries through the port.
- [x] 2.4 Update every in-repository runtime factory, Agent constructor, and test double; remove old callback types, parameters, forwarding maps, completeness checks, aliases, and adapters.
- [x] 2.5 Keep non-Gateway Agent construction without a durable port working in its existing non-persistent mode, without adding a NullPort or legacy adapter.

## 3. Recovery and Failure Semantics

- [x] 3.1 Verify staging, verification persistence, promotion, execution-result reuse, staged-reference recovery, and execution commits preserve existing behavior through the port.
- [x] 3.2 Add or update Gateway tests for fresh and resumed runs, per-run port binding, missing Gateway port rejection, and fail-closed publication when persistence fails.
- [x] 3.3 Add or update Agent and verification tests to use a direct fake port and cover execution replay and generated-chart recovery.
- [x] 3.4 Search production and test code for all seven legacy callback names and confirm no old injection entry point or transitional wrapper remains.

## 4. Validation

- [x] 4.1 Run focused Gateway, Agent, verification, and execution-record tests, then run `conda run -n agent python -m pytest -q`.
- [x] 4.2 Run `openspec validate durable-execution-port --strict` and `git diff --check`.
