## 1. Launcher lifecycle cleanup

- [x] 1.1 Refactor owned-child tracking so cleanup can detect and signal a surviving process group even after its direct npm or Conda wrapper exits.
- [x] 1.2 Dispatch graceful termination to the Vite and Gateway process groups before awaiting either group's shutdown, while keeping cleanup idempotent and bounded.
- [x] 1.3 Add forceful escalation and bounded diagnostics for groups that remain alive after graceful shutdown, without discovering or killing unrelated port owners.
- [x] 1.4 Cover frontend bind failure and Gateway startup failure paths so every process created before the failure is cleaned up.

## 2. Lifecycle verification

- [x] 2.1 Add a lifecycle test that starts the exact `npm run dev:gateway` command on isolated ports and waits for Gateway and Vite readiness.
- [x] 2.2 Verify `SIGINT` cleanup releases both configured ports and leaves no owned child process behind.
- [x] 2.3 Verify termination cleanup also handles a direct `SIGTERM` and remains safe when one child has already exited.
- [x] 2.4 Verify a pre-existing frontend listener causes a bounded startup failure, cleans only the newly created Gateway, and preserves the unrelated listener.
- [x] 2.5 Run the lifecycle test repeatedly enough to expose signal timing races and keep the existing launcher/configuration smoke checks passing.

## 3. Documentation and validation

- [x] 3.1 Update the README and frontend smoke checklist to describe the unified shutdown guarantee and the expected `Ctrl-C` workflow.
- [x] 3.2 Run the frontend smoke/build checks and the focused launcher lifecycle checks from the documented Conda `agent` environment where Python is involved.
- [x] 3.3 Validate the completed change with `openspec validate fix-gateway-launcher-shutdown --strict`.
