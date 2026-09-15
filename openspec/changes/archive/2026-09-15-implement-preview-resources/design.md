## Context

The existing Gateway already stores uploaded attachments and run-owned visual
artifacts behind session/run-scoped routes. The frontend currently turns those
references into direct image URLs in more than one place, while the Tauri
supervisor and frontend build can have different Gateway addresses. Generated
charts also have two identities: a review candidate and a promoted artifact.
See `proposal.md` for the motivation and the delta specs for the observable
contracts.

## Goals / Non-Goals

**Goals:**

- Establish one resource model for metadata, loading, byte validation, failure,
  retry, and cleanup across all preview kinds.
- Make browser development and Tauri Gateway mode use the same effective
  Gateway origin for JSON, SSE, and binary resource requests.
- Preserve session/run authorization and the existing retention policy.
- Make candidate-to-artifact transitions safe across live events and reloads.
- Keep the implementation compatible with mock mode and existing protocol
  identifiers.

**Non-Goals:**

- Changing chart rendering, OCR, review algorithms, or publication policy.
- Sending preview bytes to the model merely because the desktop client displays
  them.
- Introducing a remote object store, authentication system, or third-party
  image viewer.
- Persisting client-generated object URLs in Gateway or SQLite records.

## Decisions

### 1. Use a backend-owned preview resource descriptor

Add a small frontend resource layer that accepts a typed descriptor such as
`attachment`, `observation`, `candidate`, or `artifact`, plus session/run and
opaque resource IDs. The Gateway client remains responsible for constructing
authorized endpoint paths; UI components consume resolved preview state rather
than assembling URLs themselves.

This is preferred over passing raw URLs through every component because raw
URLs become stale during candidate promotion and are difficult to validate or
retry consistently. Existing endpoint shapes and opaque identifiers remain
compatible.

### 2. Load binary previews as blob URLs

The resource layer will request binary content with `fetch`, verify HTTP
success, an allowed image `Content-Type`, a non-empty body, and basic image
decodability through the browser image loader. It will expose a temporary blob
URL to the `<img>` element and revoke it on replacement or unmount.

This is preferred over direct `<img src="...">` loading because it provides
uniform status/error handling and prevents an HTML/JSON error response from
being treated as an image. It also gives the UI one place to support retry.
The trade-off is one additional in-memory copy per displayed preview, bounded
by the number of visible resources and cleaned up deterministically.

### 3. Resolve the effective Gateway origin once

The client boundary will receive or derive one effective Gateway base URL for
the current runtime. Browser development continues to use the launcher-provided
`VITE_CHARTAGENT_GATEWAY_URL`; Tauri mode will use the supervisor's reported
address or an equivalent injected runtime value before making resource calls.
JSON requests, SSE subscriptions, attachment previews, observations, and
generated chart previews must use the same origin.

This is preferred over independently reading environment defaults in each
feature. A single origin avoids a split-brain state where sessions load from
one port but images load from another. If runtime discovery fails, the client
shows unavailable state instead of silently falling back to mock resources.

### 4. Keep candidate and artifact routes lifecycle-aware

The Gateway will retain the existing candidate and artifact storage semantics,
but the client-facing chart reference resolver will prefer `artifactId` when
present and use `candidateId` only while the candidate is still pending and
servable. If a candidate has been promoted, a current artifact reference must
be obtained from the event/history representation before rendering the final
published chart.

Where live and historical payloads can race, the frontend will merge references
by candidate identity and prefer the most progressed representation: published
artifact, then pending candidate, then explicit unavailable/failed metadata.
The server remains the authority for authorization and actual availability.

### 5. Preserve explicit failure classes

The Gateway keeps bounded HTTP error codes for not-found, unavailable,
expired, and invalid requests. The frontend maps those responses to preview
states without exposing local paths or raw response bodies. Retry is offered
for transport and temporary service failures; missing, unauthorized, expired,
or invalid media responses are shown as non-retryable until the owning data
changes.

### 6. Make Tauri origin compatibility explicit

The Gateway's allowed-origin configuration will include the origin used by the
desktop WebView or, where the WebView does not send a conventional HTTP Origin,
binary loading will use the same loopback backend boundary as other client
requests without weakening session/run authorization. Tests will cover the
actual development and Tauri launch configurations rather than assuming only
`localhost:1420`.

## Risks / Trade-offs

- [Tauri origin differs by platform] → derive the effective runtime address
  from the supervisor and cover macOS/WebView request behavior in integration
  tests; keep Gateway loopback-only.
- [Blob URLs increase transient memory use] → limit loading to visible/current
  resources, revoke on lifecycle changes, and never persist blob URLs.
- [Candidate publication races with event delivery] → merge by candidate ID,
  prefer artifact references, and rehydrate current history before declaring a
  preview unavailable.
- [A server error is returned with HTTP 200 or a wrong media type] → require
  both successful HTTP status and an allowed image media type before creating a
  preview URL.
- [Legacy records lack a resource reference] → retain metadata-only rendering
  and explicit unavailable state; do not infer a local path.

## Migration Plan

1. Add resource descriptors and loader behind the existing frontend client
   boundary while keeping mock data unchanged.
2. Update Gateway client mapping and runtime configuration to produce
   descriptors for attachments, observations, candidates, and artifacts.
3. Update attachment, observation, and generated-chart components to consume
   the loader and expose loading/error/retry states.
4. Add server and frontend regression tests, then run the documented Python,
   frontend build, and smoke checks.

The change is backwards-compatible at the JSON/event identifier level. Rollback
can remove the frontend loader integration and retain the existing binary
routes; no database migration or irreversible data transformation is required.
