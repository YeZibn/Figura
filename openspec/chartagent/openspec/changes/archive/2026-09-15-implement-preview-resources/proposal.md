## Why

Figura currently persists uploaded images, visual observations, review
candidates, and published chart artifacts, but the desktop client cannot
reliably display them in real Gateway/Tauri mode. Preview URLs are assembled
in several places, depend on a static Gateway address, and do not provide a
consistent fallback when a resource is unavailable or changes from candidate
to published artifact.

## What Changes

- Introduce one client-side preview resource contract and loader for uploaded
  attachments, temporary visual observations, generated candidates, and
  published chart artifacts.
- Resolve preview resources against the active Gateway runtime configuration,
  including Tauri-managed and non-default loopback ports, instead of relying
  only on a build-time URL.
- Make Gateway binary preview responses usable from the desktop WebView with
  explicit origin/transport compatibility and bounded media validation.
- Provide a stable generated-chart preview resolution path that can follow a
  candidate reference through review and publication without leaving stale
  candidate URLs.
- Display loading, unavailable, expired, unauthorized, and invalid-media
  states distinctly, with retry behavior where a retry can recover the
  resource; preserve metadata when image bytes are no longer available.
- Add end-to-end regression coverage for upload previews, observation previews,
  candidate previews, published chart previews, reloads, Tauri/Gateway URL
  configuration, and failure states.

## Capabilities

### New Capabilities

### Modified Capabilities

- `attachment-access`: expose a reliable, authorized binary preview resource
  for a registered image and explicit unavailable behavior.
- `attachment-workspace`: render uploaded attachment previews through the
  unified resource loader with loading, failure, and retry states.
- `multimodal-tool-observations`: expose visual observation resources in a form
  the desktop client can load reliably while preserving expiration boundaries.
- `execution-trace`: make generated candidate and published artifact preview
  references resolvable across lifecycle transitions and reloads.
- `desktop-client`: provide a unified preview experience for uploaded,
  observed, candidate, and generated chart images in Gateway and Tauri modes.

## Impact

- Python Gateway routing, binary response headers, resource resolution, and
  generated-artifact lookup in `src/chartagent/gateway/`.
- Frontend API/resource loading, runtime configuration, attachment panel,
  execution timeline, and generated-chart result components in
  `frontend/src/`.
- Gateway, frontend, and desktop-runtime regression tests; no new external
  provider or image-processing dependency is required.
