## 1. Domain model and versioned shape

- [x] 1.1 Add `src/figura/chartspec/` with the closed `ChartType`, immutable `ChartMetadata`, `Axis`, `Axes`, categorical/coordinate point variants, and `ChartSpecData` value types.
- [x] 1.2 Define version 1 fields, defaults, optional-field serialization, text/list bounds, and the 256 KiB canonical content limit in one domain contract.
- [x] 1.3 Add the exported `CHART_SPEC_DATA_SCHEMA` using only Figura's supported JSON Schema dialect and reject unknown properties at every object level.

## 2. Strict parsing and canonical serialization

- [x] 2.1 Implement mapping and JSON-text parsers that reject duplicate JSON keys, unsupported versions, missing required fields, unknown fields, invalid point variants, coercions, and oversized input without echoing submitted values.
- [x] 2.2 Implement deterministic `to_dict` and canonical JSON serialization that preserves dataset/category order and applies documented optional metadata defaults.
- [x] 2.3 Return bounded parse issues with stable codes and JSON Pointer paths; ensure parse failures never produce partially accepted ChartSpecData values.

## 3. Chart-specific semantic validation

- [x] 3.1 Implement bounded multi-issue validation for point counts, finite numeric values, labels, axis bounds, and applicability of axis fields.
- [x] 3.2 Implement bar category domain, duplicate `(category, series)`, and per-series category completeness checks without filling missing values.
- [x] 3.3 Implement pie uniqueness, no-series, non-negative value, and positive-total checks.
- [x] 3.4 Implement line per-series x uniqueness/order and categorical integer-position mapping; implement scatter category rejection while preserving repeated points.
- [x] 3.5 Keep issue order deterministic, cap issues at 32, bound paths/messages, and ensure validation does not mutate or repair its input.

## 4. Focused behavior coverage

- [x] 4.1 Add focused tests for valid round-trips, canonical equality, every supported chart type, and immutable nested collections.
- [x] 4.2 Add parser tests for duplicate keys, unsupported versions, missing/unknown fields, wrong data-point variants, coercion attempts, and size limits.
- [x] 4.3 Add semantic tests for bar completeness, pie values/totals, line ordering/category positions, scatter duplicates, numeric bounds, and stable bounded issue paths.
- [x] 4.4 Verify the exported schema is accepted by Figura's schema-definition validator and agrees with the domain parser on local field shapes.
