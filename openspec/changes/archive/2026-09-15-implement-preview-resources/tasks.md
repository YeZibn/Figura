## 1. Gateway preview resource contract

- [x] 1.1 Audit and, where needed, tighten the existing attachment, observation, candidate, and artifact binary routes so each validates session/run ownership and returns bounded errors without paths or raw error bodies.
- [x] 1.2 Make binary preview responses explicitly compatible with browser development and Tauri WebView requests, including allowed image media types, cache policy, content length, and effective Origin handling while keeping the Gateway loopback-only.
- [x] 1.3 Add a lifecycle-aware chart preview resolution path or equivalent server lookup so a candidate reference can resolve to its current published artifact after promotion without breaking existing IDs and routes.

## 2. Frontend resource boundary

- [x] 2.1 Add typed preview resource descriptors and a single Gateway/mock resource loader covering attachment, visual observation, generated candidate, and published artifact references.
- [x] 2.2 Resolve the effective Gateway base URL once from launcher/runtime configuration and use it consistently for JSON, SSE, and binary preview requests, including non-default Tauri ports.
- [x] 2.3 Implement binary response validation for HTTP status, allowed image media type, non-empty content, and browser-decodable image data; map failures to bounded retryable or terminal preview states.
- [x] 2.4 Manage temporary blob URLs with deterministic replacement/unmount cleanup and ensure preview display never mutates attachment model-load state or sends an Agent request.

## 3. UI integration

- [x] 3.1 Update the attachment panel to consume the resource loader and render loading, available, unavailable, invalid, and retry states while preserving safe metadata and local pending-upload previews.
- [x] 3.2 Update visual-observation rendering to load authorized observation resources through the same boundary and distinguish expired/missing evidence from an image-load failure.
- [x] 3.3 Update generated-chart rendering and reference merging to prefer published artifacts, use pending candidates only when valid, and preserve explicit review, publication, expired, and unavailable states after reload or out-of-order events.
- [x] 3.4 Keep mock mode on the same presentation contract with local resources and add accessible preview/retry labels in Simplified Chinese.

## 4. Verification and compatibility

- [x] 4.1 Add Python Gateway tests for attachment, observation, candidate, and artifact binary responses, ownership isolation, media validation, expiry, publication resolution, and response headers.
- [x] 4.2 Add frontend tests or smoke contracts for unified URL resolution, blob cleanup, invalid-media handling, retry behavior, Tauri/non-default port configuration, and all preview kinds.
- [x] 4.3 Run `conda run -n agent python -m pytest -q`, `cd frontend && npm run build`, `cd frontend && npm run smoke`, `git diff --check`, and strict OpenSpec validation.
- [x] 4.4 Verify existing attachment IDs, observation IDs, candidate/artifact IDs, lifecycle event names, authorization boundaries, and mock behavior remain compatible.
