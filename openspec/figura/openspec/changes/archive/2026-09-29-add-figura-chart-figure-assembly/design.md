## Context

See [proposal.md](proposal.md) for motivation and scope. Today `src/figura/chartspec/` owns a pure, versioned `ChartSpecData` model for one chart. `RunExecutionState` is a read-only projection with four fields, while Runtime already persists each model tool call's complete `arguments_json` and its committed result. Tool arguments are limited to 64 KiB. There is no Figure table, renderer, or generated-image store in the new Figura implementation.

The Figure capability is the first stage of a larger chart flow: assemble structured canvas content, then render it, then expose a preview. This change establishes the content and Run-fact boundary only.

## Goals / Non-Goals

**Goals:**

- Put single-chart content and multi-chart canvas content under the same `src/figura/charts/` owner.
- Let the Agent assemble 1–4 ordered charts with one explicit 1- or 2-column layout.
- Keep each child ChartSpec independently parseable and semantically validated by the existing rules.
- Preserve selected measurement call references at the Figure child that uses them.
- Make successful Figure content addressable and reconstructable from existing Runtime facts across Runs in one Session.
- Give later Agent actions a compact Figure index without copying every full ChartSpec into derived state.

**Non-Goals:**

- Drawing or exporting PNG/SVG output, creating artifact storage, or previewing Figures in the Gateway or frontend.
- Adding a Figure database table, a new Runtime fact kind, mutable Figure updates, review/publication states, generic Evidence objects, or a source-authorization layer.
- Verifying that model-authored data values exactly match cited measurements. The tool checks that references exist and succeeded; it does not prove numerical fidelity.
- Adding a layout editor, arbitrary coordinates, responsive sizing, more than two columns, or more than four charts.
- Changing `ChartSpecData` fields, chart-type semantics, or its standalone 256 KiB canonical serialization limit.

## Decisions

### One Charts domain owns both models

Move the current `src/figura/chartspec/` package to `src/figura/charts/` and update all in-repository imports atomically. Do not leave a `chartspec` compatibility package. Keep model responsibilities in focused files instead of creating a separate top-level Figure domain:

```text
src/figura/charts/
  __init__.py       # package boundary; APIs are exposed by their owner subpackages
  limits.py         # shared text and bounded-issue limits
  chartspec/        # single-chart model, schema, codec, validation, errors, and limits
  chartfigure/      # canvas model, schema, codec, validation, errors, and limits
```

`ChartFigure` composes existing `ChartSpecData`; it does not alter that model. Pure parsing and validation in `charts/` SHALL depend only on shared JSON/schema utilities. It SHALL NOT import Runtime, Agent, Tools, Sources, or storage. Runtime reference resolution belongs to the tool handler because it needs the executing Session's committed facts.

The public Figure shape is:

```json
{
  "schema_version": 1,
  "title": "销售概览",
  "layout": {"columns": 2},
  "charts": [
    {
      "chart_id": "revenue",
      "chart_spec": {
        "schema_version": 1,
        "metadata": {"chart_type": "bar", "title": "收入"},
        "axes": {
          "x": {"label": "月份", "categories": ["Jan", "Feb"]},
          "y": {"label": "金额"}
        },
        "dataset": [
          {"category": "Jan", "value": 20},
          {"category": "Feb", "value": 30}
        ]
      },
      "measurement_refs": [{"run_id": "run-opaque", "call_id": "call-opaque"}]
    }
  ]
}
```

`title` and `measurement_refs` normalize to `""` and `[]` when omitted. `chart_spec.metadata.title` is the child chart title, so `ChartFigureItem` has no duplicate title field. `layout.columns` is explicit; row count is derived. Chart and reference array order is significant. A `measurement_refs` array may be empty for a chart that is not based on a measurement result; the model must not describe such a chart as measurement-backed.

The complete field inventory is normative in `specs/chart-figure-assembly/spec.md`. The bounds are 1–4 child charts, one or two columns no greater than child count, unique local chart IDs of 1–64 ASCII characters, and 0–16 distinct measurement references per child. The complete serialized Figure is limited to 64 KiB for use as a tool argument. This limit is independent of the existing 256 KiB limit for a standalone ChartSpecData value.

### Keep structural validation and Runtime resolution at their owners

`charts` parses strict JSON, validates every child with the existing ChartSpec validator, and checks Figure-only constraints such as unique chart IDs and layout. Its Figure validator remains deterministic and side-effect free. It can check that a measurement reference has the required `run_id` and `call_id` shape, but it cannot resolve those IDs.

`src/figura/tools/implementations/assemble_chart_figure.py` owns the model-callable handler and its input/result schemas. Before success, the handler obtains a fresh same-Session `RunExecutionState` and resolves every supplied `(run_id, call_id)` to a committed successful bar, line, scatter, or pie measurement. It rejects the whole canvas if any supplied reference fails. A validation or lookup error is represented through the existing bounded `ToolExecutionError` contract, including `field_path` where available. The handler does not query arbitrary Runtime tables or access image bytes directly.

The tool takes the Figure JSON directly, without an extra wrapper object, and uses the existing `MAX_ARGUMENT_BYTES` limit. It is registered as `replay_safe`: it validates and summarizes without a separate side effect. The registry advances from `figura-web-v4` to `figura-web-v5` because the model-visible tool set has changed.

### Use Runtime tool facts as the durable Figure record

The original tool arguments already contain the full ordered Figure, so Runtime's `ToolCallFact.arguments_json` remains its durable content. The successful `ToolResultFact` contains:

```json
{
  "figure_ref": {"run_id": "origin-run", "call_id": "origin-call"},
  "figure_digest": "<64 lowercase SHA-256 hex characters>",
  "title": "销售概览",
  "charts": [
    {"chart_id": "revenue", "chart_type": "bar", "title": "收入"}
  ]
}
```

The digest is SHA-256 over the canonical serialized Figure. `(run_id, call_id)` is the Figure reference; it is stable for that committed call and needs no new generated ID. The complete input and its successful result are committed through the existing tool-execution transaction. Only the successful result makes a Figure accepted. A later renderer can resolve the call, parse its arguments again, and verify the digest before rendering.

### Add a summary projection to RunExecutionState

Add `chart_figures` as the fifth and final top-level field of the frozen `RunExecutionState`. Each item contains `figure_ref`, `figure_digest`, Figure `title`, and ordered summaries `{chart_id, chart_type, title}`. Reconstruct it by pairing successful `assemble_chart_figure` result facts with their tool calls in earlier terminal Runs and the target Run, ordered by Run ordinal and tool-call position. Failed calls, started attempts without a result, and other-Session facts are excluded.

The projection stores only the result summary; it does not duplicate the full Figure. The Agent request builder includes every accepted Figure summary and its reference in a text inventory on each Provider request. Full Figure content continues to appear in the ordinary tool-call history. This follows the existing derived-state approach and leaves Runtime facts as the single source of truth.

The inventory is not truncated. Each entry is small and the existing Session history is already complete and unbounded; this change does not add a second history budget or discard old Run content.

### Keep the tool registry rollout explicit

The new tool belongs to a new registry version, `figura-web-v5`. Completed v4 tool calls remain paired with their persisted results in Session history and remain readable. The current executor requires a pending tool call's registry version to match the active registry, so a v4 Run interrupted with an unresolved tool execution cannot be resumed by v5. Roll out after existing v4 Runs have reached terminal state; do not rewrite their immutable facts or add an old-registry compatibility executor in this change.

## Risks / Trade-offs

- **A large Figure can exceed the 64 KiB tool argument limit** → Reject it before execution with a bounded size error; retain the current global tool bound rather than widening every tool payload.
- **Measurement references prove identity and successful execution, not value correctness** → Preserve them as selected-reference metadata and make no fidelity claim; numerical verification is a separate capability.
- **The prompt inventory grows with the number of accepted Figures** → Keep each item to the compact result summary and preserve all entries to honor complete Session history; no full dataset is duplicated into the inventory.
- **Moving `chartspec` breaks internal imports until all callers move together** → Update source, tests, exports, and docs in one implementation change and leave no compatibility package.
- **A v4 Run may be paused on a pending tool action during rollout** → Complete running v4 Runs before switching the registry to v5; this is the only migration requirement because completed history remains readable.

## Migration Plan

1. Confirm no Run is still executing or waiting on an unresolved v4 tool call.
2. Move the existing Chartspec package into `src/figura/charts/`, update all internal imports, and add Figure values/codecs/validation.
3. Register `assemble_chart_figure` in the v5 registry and use existing durable tool facts for content and result persistence.
4. Extend the RunExecutionState projection and Provider inventory, then update the Charts documentation and global overview.
5. Verify old terminal Run histories still project and that the new Figure content round-trips and is reconstructed from facts.
