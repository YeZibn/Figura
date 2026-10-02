## Context

See [proposal.md](proposal.md) for the motivation and [specs/figura-web-client/spec.md](specs/figura-web-client/spec.md) for the behavior contract. `ChartRenderGallery` already receives every committed render for a Run and builds its Session/Run/call-scoped content URL. It currently renders a plain `<img>`. Figura already mounts `InteractivePreview`, which accepts a direct fallback URL and provides fit/zoom, Escape dismissal, and focus restoration. The Figura client currently parses JSON responses only; downloads need a binary read through that client rather than direct Gateway requests from a React component.

## Goals / Non-Goals

**Goals:**

- Open the exact selected ChartRender from every Run gallery in the existing full-size preview.
- Download each committed PNG on demand through the Figura client contract.
- Keep client state limited to transient download status and browser-created object URLs.
- Keep rendering, storage, and authorization in their current Figura Gateway and storage boundaries.

**Non-Goals:**

- Change attachment or Panel preview/download behavior.
- Add editing, review, publication, retry, render configuration, or a separate child-chart export.
- Change the Gateway route, response metadata, render persistence, or ChartAgent/mock contracts.

## Decisions

### Reuse the existing full-size preview

Pass `onPreview` into `ChartRenderGallery` and render each successful thumbnail through the existing `PreviewImage` interaction with its exact content URL as the fallback URL. `FiguraApp` already owns `activePreview` and mounts `InteractivePreview` with a null loader; the direct fallback URL makes this route work without introducing another image loader or modal. The existing preview control owns zoom, fit, Escape handling, and focus restoration.

Alternatives considered: add a Figura-specific modal or duplicate the dialog in the gallery. Both duplicate the existing viewer and its accessibility behavior without adding a distinct Figura requirement.

### Keep download actions in the Figura render gallery

Give every render card a separate `下载 PNG` action. The image itself remains the preview trigger, so the download button does not intercept or ambiguously trigger preview. Keep the shared `InteractivePreview` and legacy `GeneratedChartView` behavior unchanged.

On activation, the card calls a typed `getChartRenderContent(sessionId, runId, callId)` operation exposed by the Figura client and workspace API. The client owns the fetch, maps non-success responses to a bounded `FiguraClientError`, and returns PNG bytes as a `Blob`. The component creates a temporary object URL, clicks a download anchor, and revokes the URL after the browser starts the download. No React component issues a Gateway fetch directly.

The filename is the Figure title with path separators, control characters, and platform-invalid filename characters replaced or removed, followed by `.png`. If the sanitized title is empty, use `figura-chart.png`. Preserve Unicode titles.

Alternatives considered: add `Content-Disposition` behavior or a new Gateway download route. The existing content route already returns the verified PNG and the frontend has the title needed for naming, so a new server contract is unnecessary. Adding download behavior to the generic modal would also change a shared surface used by ChartAgent and attachment previews when a Figura-gallery action is sufficient.

### Read only the existing committed render resource

Use the existing route addressed by Session ID, originating Run ID, and render call ID for both preview and download. The Gateway continues to verify ownership and committed PNG integrity. The client does not add image bytes, paths, or download URLs to DTOs, local storage, or durable Run state.

## Risks / Trade-offs

- **Cross-origin binary reads can fail if the local frontend origin is not allowed** → The `dev:figura` launcher already supplies its loopback Vite origins to the Gateway. Keep the binary read inside the Figura client and show a bounded download error if the request still fails.
- **Large images temporarily occupy browser memory during download** → Fetch only after an explicit user action and release the browser-created object URL after starting the download.
- **Figure titles can contain unsafe or empty filename text** → Sanitize the title and use the documented stable fallback.
- **One Figure may contain several child charts** → Preserve the existing render unit: each committed ChartRender previews and downloads its complete composite PNG.

## Migration Plan

No data migration is required. Existing committed render summaries and PNGs immediately gain preview and download controls after the frontend update. Rolling back the frontend removes the controls without changing or deleting render data.
