## Context

See `proposal.md` for the motivation and scope. The current implementation
has three relevant boundaries: `ChartSpec.validate()` owns general structural
checks, chart assembly and `render_chart` add separate chart-specific checks,
and `ToolResult`/Gateway own bounded image transport and persistence. The
change must preserve Matplotlib as the single authoritative renderer, keep
generated images in memory until the existing artifact boundary, and avoid
introducing a second frontend rendering path or a new runtime dependency.

## Goals / Non-Goals

**Goals:**

- Make generation eligibility deterministic and consistent across assembly,
  standalone validation, and rendering.
- Preserve categorical and coordinate data without implicit values or
  unreported clipping.
- Audit the rendered Matplotlib figure before it is closed, then verify the
  encoded PNG before publishing it.
- Distinguish blocking semantic/artifact failures from usable but imperfect
  layout or font warnings.
- Add validation diagnostics without exposing image bytes, local paths, or
  provider data.

**Non-Goals:**

- No visual-language-model review, render/re-understand loop, or automatic
  Agent retry in this phase.
- No new chart types, style schema, interactive editing, or frontend chart
  renderer.
- No full source-image-to-generated-data comparison; that requires retaining
  source provenance and is a later semantic-fidelity phase.
- No broad glyph-coverage redesign or automatic pie-label redesign; existing
  bounded CJK font diagnostics remain in place.

## Decisions

### D1: Keep base structure separate from generation semantics

Keep `ChartSpec.validate()` as the dependency-light structural validator, and
add one pure generation-validation layer that receives a `ChartSpec` and
returns located, severity-aware issues. Assembly, `validate_spec`, and
`render_chart` all call this layer. The renderer-specific layout and PNG
checks remain downstream because they require a Matplotlib figure or encoded
bytes.

The compatibility surface remains intact: `validate_spec` continues to
return `ok` and `issues`, and render failures continue to return a bounded
structured error. New issue fields such as a stable code and severity are
additive. The shared semantic layer must not import Matplotlib, so it can be
unit-tested and reused by every entry point without circular dependencies.

### D2: Treat category membership as semantic data

For bar charts, a category is matched using its trimmed canonical label and a
point is identified by the pair `(category, series)`, with an omitted series
treated as the default series. Duplicate pairs are blocking errors.

If a declared category set or the union of categories requires a value for a
series and that pair is absent, validation fails. The renderer will no longer
use an implicit zero to fill the missing cell. A caller that means zero must
provide an explicit point with value `0`; a later change can add an explicit
missing-data representation if the ChartSpec needs one.

This makes grouped bars a complete category-by-series matrix and avoids
publishing a visual claim that was not present in the data. The original label
text is retained for display; canonicalization is used only for matching and
duplicate detection.

### D3: Apply numeric axis ranges or reject them

Validate `min_value` and `max_value` as finite values with a strict increasing
range. Numeric x and y ranges are supported for line and scatter charts; the
numeric y range is supported for bar charts, while a numeric range on the
categorical bar x-axis is rejected as unsupported. Every plotted value must
fall within an explicitly declared range, otherwise rendering fails rather
than clipping data.

After plotting, the renderer applies the accepted bounds to the corresponding
axis. With no explicit bound, Matplotlib autoscaling remains unchanged. This
keeps the existing default behavior while making a provided range observable
and trustworthy.

### D4: Audit the figure before encoding and closing it

The renderer performs an internal audit after layout and a canvas draw, while
the `Figure` and `ChartSpec` are both available. The audit has two parts:

- Fidelity checks compare chart-type-specific artists with the requested data:
  bar heights and count, line x/y arrays per series, scatter offsets, pie
  wedge count and proportions, category ticks, and series legends.
- Layout checks measure visible titles, axis labels, tick labels, data
  annotations, and legends in display coordinates. Material clipping or
  content outside the fixed canvas is reported. A simple non-content check
  also catches an encoded chart that is effectively blank.

The audit uses a small pixel tolerance for renderer rounding. It does not use
PNG pixel snapshots as the semantic oracle. Layout findings are classified by
severity: a minor crowding issue can return a warning, while clipped data,
unreadable critical labels, or a fidelity mismatch blocks publication.

### D5: Verify the encoded artifact independently

After `savefig`, the output is checked against the existing byte and requested
dimension limits. The PNG is verified with Pillow, fully loaded after
verification, checked for the expected PNG format and exact dimensions, and
checked for non-empty/non-blank content. Only after these checks pass is the
content wrapped in `GeneratedImage`.

The Gateway continues to own storage, authorization, retention, and SHA-256
integrity checks. No local path or raw image bytes are added to the JSON
diagnostics, and no database schema change is needed.

### D6: Return a stable, bounded validation summary

Successful render results add a compact validation object to the existing
structured chart metadata:

```json
{
  "status": "passed|warning",
  "checks": {
    "semantic": "passed|warning",
    "fidelity": "passed|warning",
    "layout": "passed|warning",
    "readability": "passed|warning",
    "artifact": "passed"
  },
  "issues": [
    {
      "code": "bounded-code",
      "severity": "warning",
      "location": "figure.legend",
      "message": "bounded diagnostic",
      "auto_fixed": false
    }
  ]
}
```

The exact issue list is bounded in count and text length. `failed` is used in
the internal/result error path when a blocking issue prevents an artifact;
successful results use `passed` or `warning`. Existing font fallback remains
a readability warning. No automatic layout repair is claimed in this phase,
so `auto_fixed` is always false unless a future bounded repair path is added.

### D7: Do not add a public image-validation tool yet

The audit belongs inside `render_chart`, where the source spec, figure artists,
and output bytes are simultaneously available. A separate public validator
would need an artifact lifecycle contract and would be unable to reliably
recover the original semantic input from PNG bytes. Keeping it internal also
ensures an invalid result cannot briefly enter the Gateway artifact store.

## Risks / Trade-offs

- [Strictly rejecting incomplete grouped bars changes behavior for previously
  accepted ambiguous specs] -> Preserve explicit zero values, return located
  errors, and add regression tests documenting the breaking rule.
- [Matplotlib versions and CJK font metrics can produce slightly different
  bounding boxes] -> Use the fixed Agg backend, a small pixel tolerance, and
  geometry assertions instead of exact PNG snapshots.
- [A declared axis range can make labels or annotations collide with the
  boundary] -> Validate data containment first, classify minor presentation
  issues as warnings, and fail only when critical content is clipped.
- [PNG verification adds a second decode and memory cost] -> Keep the existing
  output byte limit, perform verification before constructing the result, and
  avoid retaining duplicate long-lived buffers.
- [A shared validator can become coupled to renderer details] -> Keep it pure
  and ChartSpec-based; figure artist inspection stays in the renderer audit.
- [A visually valid chart can still reflect incorrectly inferred source data]
  -> Keep source comparison and round-trip visual review explicitly out of
  scope, while preserving confidence fields for a later semantic phase.

## Migration Plan

1. Add the shared generation-semantic validation and route assembly,
   standalone validation, and rendering through it.
2. Update rendering to apply accepted axis ranges, reject ambiguous missing
   bar cells, run the figure audit, and perform complete PNG verification.
3. Add the validation summary additively to successful tool results while
   preserving existing `ok`, `issues`, error strings, artifact kind, and
   Gateway persistence behavior.
4. Run focused chart tests, the full Python suite, strict OpenSpec validation,
   and `git diff --check`.

Rollback is code-level: disable the new audit and shared generation checks if
necessary. Existing persisted artifacts require no migration and remain
readable because their artifact kind and binary contract are unchanged.
