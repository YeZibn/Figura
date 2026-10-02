## 1. Expose ChartRender PNG bytes through the Figura client

- [x] 1.1 Add a typed Figura client operation that reads a committed ChartRender PNG from the existing Session/Run/call content route and maps failed responses to bounded client errors.
- [x] 1.2 Expose the binary read through the Figura workspace API so presentation components do not issue Gateway fetches directly.

## 2. Add full-size preview and download to every render card

- [x] 2.1 Connect each ChartRender thumbnail to the existing full-size preview, preserving Run grouping, fit/zoom controls, keyboard dismissal, and focus return.
- [x] 2.2 Add an independent PNG download action per render card using a safely sanitized Figure-title filename and the client binary read.
- [x] 2.3 Show localized per-render download progress and bounded failures, and release temporary browser object URLs after download starts.

## 3. Preserve Figura and legacy mode boundaries

- [x] 3.1 Keep the existing Gateway content route, render persistence, and ChartAgent/mock client behavior unchanged.
