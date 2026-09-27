## Context

See `proposal.md` for motivation and `specs/chart-spec-core/spec.md` for the version 1 behavior contract. Current Figura has a provider-neutral JSON Schema validator, but no chart-domain model, artifact store, chart tool, or renderer. The legacy implementation is a reference for chart semantics; its mutable point shape and permissive unknown-field handling are not carried over.

## Goals / Non-Goals

**Goals:**
- Define a small immutable Python value model for one chart's semantic content.
- Keep parsing, deterministic serialization, and chart-specific readiness checks in one dependency-light domain module.
- Make the same semantic object reusable by a future tool schema, durable object envelope, renderer, and verifier.

**Non-Goals:**
- Registering an Agent tool or changing model prompts/requests.
- Persisting ChartSpec objects, allocating IDs, binding RunInput, or computing an artifact digest.
- Defining provenance, evidence references, GenerationContext, observation, measurement, figures, or collections.
- Rendering, staging, reviewing, publishing, or exposing charts through Gateway/frontend.

## Decisions

### 1. Model chart content separately from the durable ChartSpec envelope

This change defines `ChartSpecData`: the semantic chart body. Its JSON shape is:

```json
{
  "schema_version": 1,
  "metadata": {
    "chart_type": "bar",
    "title": "Quarterly revenue",
    "source": null,
    "note": "USD millions"
  },
  "axes": {
    "x": {"label": "Quarter", "categories": ["Q1", "Q2"]},
    "y": {"label": "Revenue", "min_value": 0}
  },
  "dataset": [
    {"category": "Q1", "value": 12},
    {"category": "Q2", "value": 15}
  ]
}
```

`ChartSpecData` has exactly four top-level fields: `schema_version`, `metadata`, `axes`, and `dataset`. The value model contains no runtime IDs, timestamps, Run IDs, provenance, generation context, storage refs, render status, or publication status. A later assembly/persistence change will define the durable `ChartSpec` envelope and bind `ChartSpecData` to it. This keeps the core independent of not-yet-implemented Evidence and Artifact stores while leaving the data body stable.

### 2. Use typed immutable point variants and tuples

Implement frozen dataclasses in `src/figura/chartspec/`:

- `ChartType`: closed string enum with `bar`, `line`, `pie`, `scatter`.
- `ChartMetadata`: `chart_type`, `title`, `source`, `note`.
- `Axis`: `label`, optional ordered `categories`, optional `min_value`, optional `max_value`.
- `Axes`: `x` and `y` axes.
- `CategoryValuePoint`: `category`, `value`, optional `series`.
- `CoordinatePoint`: `x`, `y`, optional `series`.
- `DataPoint`: Python 3.10 union of the two point classes.
- `ChartSpecData`: `schema_version`, metadata, `Axes | None`, and an immutable tuple of DataPoint values.
- `ChartSpecIssue`: stable `code`, JSON Pointer `field_path`, bounded `message`.
- `ChartSpecParseError`: parse-shape failure carrying bounded issue data, without raw values.

Optional input `title`, `source`, and `note` normalize to `""`, `null`, and `""` respectively. `axes` is required in the canonical input: an object for Cartesian charts and `null` for pie. Optional `series`, category lists, and axis bounds are omitted when absent. The parser does not coerce numeric strings, booleans, enums, or malformed field values. Unknown fields are rejected recursively. Duplicate keys in a raw JSON string are rejected before mapping conversion.

`confidence` is excluded: it describes extraction quality rather than plotted semantics and would be misleading without an Evidence/Measurement contract. `metadata.source` remains display-only and cannot satisfy later provenance checks.

### 3. Separate shape parsing from semantic validation

Expose a strict parser (`ChartSpecData.from_dict` and a JSON text parser) and a pure `validate_chart_spec_data` function. Parsing establishes the versioned typed shape and rejects unknown/missing/wrongly typed fields. Semantic validation returns all detected chart readiness issues in stable order, capped at 32. A shape parse error is a bounded `ChartSpecParseError`; it is not converted into a partially populated object. The future `assemble_spec` handler will translate these domain errors into Figura `ToolFailure` values.

The validator SHALL never repair data. It will not sort line points, fill absent bar values with zero, clamp ranges, invent labels, or decide whether uncertain evidence is acceptable.

### 4. Keep chart rules explicit and renderer-independent

- **Bar:** category/value points only. The x-axis category domain is the declared ordered category list, or first-seen category order if omitted. Every series must have one point for each domain category; duplicate `(category, series)` pairs and undeclared categories fail. A missing series label is treated as one unnamed series only for duplicate/completeness checks. The x-axis cannot have numeric bounds; y bounds are checked against values.
- **Pie:** category/value points only; category is unique, `series` is absent, values are non-negative, and their sum is positive. Axes are null.
- **Line:** x/y points only. Within each series, x values are unique and strictly increasing in input order. A missing series label is one unnamed series. With x categories, those labels map by index to integer x coordinates `0..n-1`; every series must cover every declared position. Without categories, x is numeric. x/y bounds are checked against coordinates.
- **Scatter:** x/y points only; repeated coordinates are valid; x categories are rejected. Bounds are checked against coordinates.
- `axes.y.categories` is rejected in version 1 because Figura's first renderer contract only has an ordered categorical x domain. Category and series text is stripped for semantic comparison, but serialization preserves submitted text unless normalization is required for default optional metadata.

The domain point limit is 512. Text fields and labels are limited to 160 Unicode code points. Canonical serialized content is limited to 256 KiB. These bounds define the reusable domain object; a future provider tool call remains subject to the smaller existing 64 KiB tool-argument bound and may require a lower per-call point budget.

Numeric data and axis bounds must convert to finite IEEE-754 binary64 values (absolute value at most `1.7976931348623157e308`). This matches the numeric range the legacy generation validator and plotting backends can safely consume; oversized Python integers are rejected rather than failing later during rendering. Pie totals use finite-float summation and reject overflow.

### 5. Provide one canonical JSON Schema and semantic validator

Export a version 1 `CHART_SPEC_DATA_SCHEMA` compatible with Figura's supported JSON Schema dialect. Use `anyOf` for the categorical/coordinate point variants and keep `additionalProperties: false` at every object level. JSON Schema handles local shape, enum, string, and collection bounds; `validate_chart_spec_data` handles chart-type relationships, cross-point completeness, ordering, and numeric range semantics. The domain validator remains authoritative for generation readiness. Schema tests will also confirm that the exported schema itself can be accepted by `figura.json_schema.validate_schema_definition`.

Canonical serialization emits keys in the stable declared shape and uses Figura's canonical JSON helper for deterministic compact JSON. Lists remain ordered and are never sorted. Content digest is intentionally deferred until a later change defines whether the durable digest covers only ChartSpecData or the full object envelope including provenance; the render change must then bind output to that exact immutable digest.

## Risks / Trade-offs

- [A pure content object can be mistaken for a persisted ChartSpec] → Name the value `ChartSpecData`, omit identity/storage fields, and document that only a future durable envelope is an artifact.
- [A later renderer may want more visual channels or chart kinds] → Keep version 1 closed and add fields/types only through a deliberate schema-version change.
- [The 512-point domain limit can exceed the 64 KiB model tool-argument limit] → Keep the independent runtime argument limit; set a suitable per-tool maximum in the future assembly contract rather than weakening the domain serialization limit.
- [Category/series completeness rules may reject sparse data] → Require callers to represent missing values explicitly through a separately designed null/missing-data semantic before relaxing this rule; never interpret absence as zero.
- [Python `frozen=True` does not freeze nested lists] → Store all nested collections as tuples and convert to plain lists only when serializing.

## Migration Plan

No data migration is required because no Figura ChartSpec persistence exists. The module is additive and does not change legacy `src/chartagent/` or its store. A later change may introduce a durable ChartSpec envelope referencing this content model; an eventual renderer will consume the validated immutable value.
