## Why

Figura already persists successful chart renders and shows them as thumbnails, but users cannot open an individual render at full size or download it from Figura mode. Completing these actions makes every generated Figure available for inspection and local use.

## What Changes

- Let each committed ChartRender thumbnail open its own full-size PNG in the existing preview experience, with fit and zoom controls.
- Provide a PNG download action for each committed render, using its Figure title as the safe filename.
- Keep renders grouped by their originating Run. A Figure containing multiple child charts remains one complete rendered canvas and one downloadable PNG.
- Align the supported-action requirement with shipped Figura Session deletion and chart-render output, while retaining restrictions on unavailable evaluation and recovery actions.
- Reuse the existing Session-scoped chart-render content route; do not add storage, database, or Gateway fields or routes.
- Preserve ChartAgent and mock mode behavior.

## Capabilities

### New Capabilities

<!-- None. -->

### Modified Capabilities

- `figura-web-client`: committed chart renders support per-image full-size preview and PNG download in Figura mode.

## Impact

- Frontend: `ChartRenderGallery`, Figura client/workspace binary-content methods, preview wiring, and gallery download controls.
- Figura Gateway and persistence: no behavior changes; the existing render metadata and content route are sufficient.
- ChartAgent and mock client contracts: unchanged.
- OpenSpec: reconcile the older client requirement that forbids chart preview with the later requirement that displays committed chart renders.
