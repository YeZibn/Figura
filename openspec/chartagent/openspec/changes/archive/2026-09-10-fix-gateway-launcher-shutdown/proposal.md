## Why

The documented `npm run dev:gateway` workflow can leave its detached Vite or Python Gateway child process alive after `Ctrl-C`. The next startup then fails because port 1420 is still occupied, so the one-step development workflow does not reliably release the processes it owns.

## What Changes

- Make the unified Gateway development launcher own and shut down both child process groups as one lifecycle.
- Ensure `SIGINT` and `SIGTERM` cleanup waits for Vite and Gateway termination before the launcher exits.
- Preserve strict port behavior and do not terminate unrelated services already using a configured port.
- Add an end-to-end launcher lifecycle check through the documented npm command, including startup, signal shutdown, and port release.
- Keep the existing mock workflow and Gateway protocol unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `desktop-runtime`: Require the documented unified Gateway development workflow to release all processes it created after termination signals.

## Impact

- `frontend/scripts/dev-gateway.mjs` process ownership, signal handling, and shutdown sequencing.
- Frontend launcher smoke or integration test scripts and development documentation.
- Local development process lifecycle only; no Gateway API or persisted session data changes.
