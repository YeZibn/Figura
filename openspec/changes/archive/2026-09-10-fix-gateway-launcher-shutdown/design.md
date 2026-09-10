## Context

The existing browser development launcher starts the Gateway through `conda run` and the React client through `npm run dev`. Both children are detached into their own process groups so the launcher can target only processes it created. In an interactive `npm run dev:gateway` session, `Ctrl-C` reaches both the outer npm process and the Node launcher. The launcher currently cleans the client group before starting Gateway cleanup, and it can be terminated by the outer npm process while that asynchronous sequence is still in progress. A direct child wrapper can also exit while descendants in its process group remain alive.

## Goals / Non-Goals

**Goals:**

- Make termination cleanup signal every owned child group promptly and wait for all of them to finish.
- Handle descendants that remain after a direct `npm` or `conda` wrapper exits.
- Keep startup failure cleanup bounded and preserve unrelated processes using configured ports.
- Verify the exact documented npm workflow, not only direct Node invocation.

**Non-Goals:**

- Changing the Gateway HTTP/SSE protocol, session data, or frontend port policy.
- Automatically killing a compatible Gateway that was not created by this workflow.
- Changing Tauri's separate runtime supervisor contract.

## Decisions

### Signal all owned process groups before waiting

Cleanup will dispatch termination to the client and Gateway process groups in parallel, then wait for their individual exit or bounded timeout. This prevents a slow or already-exiting Vite/npm wrapper from delaying the Gateway signal until the outer npm process has already ended the launcher.

### Treat the process group as the ownership boundary

The direct child handle is not sufficient because `npm` and `conda run` create descendants. Cleanup will continue to inspect the process group associated with each owned child even when the direct wrapper has already emitted an exit event. Escalation to a forceful signal remains limited to a group that is still alive and was created by the launcher.

### Keep cleanup idempotent and terminal

The launcher will allow repeated signal paths and startup failures to converge on one cleanup promise. The launcher will not report completion or exit normally until all owned groups are gone or a bounded cleanup failure has been reported.

### Test through the public npm command

The lifecycle test will start `npm run dev:gateway` on isolated ports, wait for both health/readiness signals, send `SIGINT` to the launcher process group, and assert that both ports are released. It will also cover frontend bind failure after Gateway readiness and verify that a pre-existing listener is not terminated.

## Risks / Trade-offs

- [Risk] A process-group identifier could be reused after the original child exits. → Check group liveness and the tracked child lifecycle before signaling, and never discover or kill arbitrary listeners by port alone.
- [Risk] A child may ignore graceful termination or contain a hung descendant. → Use bounded waits followed by forceful termination of the owned group, then report a bounded cleanup failure.
- [Risk] Signal behavior differs between Unix and Windows. → Preserve the platform-specific direct-child fallback and run the lifecycle contract on the supported local platform while keeping existing Windows branches covered by unit checks.
- [Risk] The outer npm process may still interrupt the launcher during shutdown. → Dispatch both group signals before the first asynchronous wait and keep the launcher cleanup path idempotent.

## Migration Plan

No data migration is required. Update the launcher and its lifecycle tests, then use the existing `npm run dev:gateway` command unchanged. If the launcher fails to start, no owned process should remain after the bounded cleanup window.
