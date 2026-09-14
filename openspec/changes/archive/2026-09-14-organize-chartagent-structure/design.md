## Context

The current implementation keeps the Agent loop, runtime construction,
attachment authorization, and generated-chart review in four large top-level
modules. The `tools` package mixes the tool protocol, registry, result
normalization, built-in tools, chart algorithms, registration functions, and
external protocol conversion. Several broad module names also make ownership
unclear: `generation.py`, `geometry.py`, `data.py`, `files.py`, and
`register.py` each contain responsibilities that belong to different layers.

The reorganization must preserve the existing runtime contracts described in
`proposal.md`, including import compatibility, tool identity and schemas,
result serialization, review lifecycle events, persistence, and Gateway
behavior. Existing tests and downstream callers also import some implementation
modules directly, so a physical move cannot be treated as a simple rename.

## Goals / Non-Goals

**Goals:**

- Establish explicit package boundaries for agent orchestration, runtime
  composition, attachment services, review services, and tool infrastructure.
- Give each implementation module one capability-oriented ownership area.
- Separate domain services from model-facing `Tool` factories and external
  protocol adapters.
- Preserve current package-level and module-level import paths during the
  migration through thin compatibility exports where needed.
- Make dependency direction and registration ownership testable.
- Allow the reorganization to be delivered incrementally, with each step
  remaining runnable and reversible.

**Non-Goals:**

- No changes to tool behavior, descriptions, parameters, tool names, or result
  payloads; those belong to the separate tool-contract work.
- No changes to the Agent's review-gate policy, lifecycle state machine,
  persistence schema, frontend protocol, or Gateway API.
- No new chart sensors, rendering features, model providers, or runtime
  dependencies.
- No immediate removal of compatibility modules used by existing consumers.

## Decisions

### 1. Convert the four top-level modules into focused packages

The current public module names become packages with explicit exports from
their `__init__.py` files:

```text
chartagent/
├── agent/
│   ├── __init__.py
│   ├── loop.py              # Agent turn loop and tool-call orchestration
│   ├── messages.py          # provider/history message assembly
│   ├── observations.py      # observation projection and status helpers
│   ├── review_gate.py       # generated-candidate gate integration
│   └── tool_schema.py       # Agent-facing tool schema projection
├── runtime/
│   ├── __init__.py
│   ├── factory.py           # create_agent_runtime and composition root
│   ├── models.py            # AgentRuntime and runtime-owned types
│   ├── prompts.py           # AGENT_SYSTEM_PROMPT
│   └── readiness.py         # provider/config readiness probe
├── attachments/
│   ├── __init__.py
│   ├── registry.py          # AttachmentRegistry lifecycle and lookup
│   ├── policy.py            # supported types and size/authorization rules
│   └── metadata.py          # metadata and content-integrity helpers
└── review/
    ├── __init__.py
    ├── models.py            # candidate, issue, result, and status types
    ├── policy.py            # review policy selection and bounded limits
    ├── evidence.py          # evidence collection and normalization
    ├── evaluator.py         # deterministic candidate evaluation
    └── manager.py           # ChartReviewManager state transitions
```

`chartagent.agent`, `chartagent.runtime`, `chartagent.attachments`, and
`chartagent.review` remain importable at their existing paths. Their package
exports reproduce the old public symbols; internal callers are migrated to
the focused modules. A legacy import that targets the old module path is
handled by a compatibility export during the move rather than by changing
the public API in the same change.

The split follows responsibility, not merely file size. In particular,
`AttachmentRegistry` remains a domain service and `ChartReviewManager` remains
the owner of review lifecycle state. Neither service constructs model-facing
tools after the split.

### 2. Use a layered tools layout with one registration boundary

The canonical tools layout is:

```text
tools/
├── core/
│   ├── definition.py        # Tool metadata and canonical schema
│   ├── registry.py          # registration and dispatch
│   ├── result.py            # ToolResult and media observations
│   └── presentation.py      # display/catalog metadata
├── adapters/
│   ├── attachment.py        # load_image Tool factory
│   ├── chart.py             # attachment-authorized chart Tool wrappers
│   └── review.py            # review_generated_chart Tool factory
├── builtins/
│   ├── filesystem.py        # read/list file tools
│   ├── json.py              # JSON tools
│   └── catalog.py           # built-in tool catalog and registration
├── chart/
│   ├── observation/         # OCR and chart-specific visual sensors
│   ├── specification.py     # ChartSpec assembly/validation tools
│   ├── rendering.py         # ChartSpec rendering and render audit
│   ├── validation.py        # generation validation rules
│   └── catalog.py           # chart tool catalog and registration
└── integrations/
    ├── openai.py            # OpenAI function-tool projection
    └── mcp.py               # MCP manifests and conversion
```

There is one composition-level registration path: the runtime creates a
registry, registers the built-in catalog, then registers adapter and chart
catalogs. Catalog modules own lists of tools; adapters own construction of
tools that bridge a domain service to the model. A domain service may be used
directly by the Agent, Gateway, or tests without importing the adapter layer.

The current singular `tools.builtin` package and direct modules such as
`tools.registry`, `tools.tool`, `tools.result`, and
`tools.mcp_converter` remain thin compatibility modules that re-export the
canonical implementation. Likewise, old chart module paths such as
`tools.chart.generation`, `tools.chart.geometry`, and
`tools.chart.register` remain importable while their implementations move to
`rendering`, `observation/bars`, and `catalog` respectively. This avoids
breaking existing tests, plugins, and monkeypatch paths while making the new
layout the only place where implementation logic is added.

### 3. Move shared ChartSpec identity below rendering and review

The stable `chart_spec_digest` helper moves to `chartagent.spec.identity`.
Rendering, review, and any future chart provenance code depend on this lower
level identity module rather than depending on one another. The existing
`chartagent.review.chart_spec_digest` import remains a re-export.

Review evidence that invokes chart sensors uses a narrow provider boundary:
the evaluator can receive sensor callables from the chart catalog/composition
layer, and the compatibility path may use lazy imports during transition.
Chart sensors and rendering code never import the review manager. This keeps
the dependency direction acyclic while preserving the current mandatory review
gate behavior.

### 4. Keep compatibility exports deliberately thin

Compatibility modules contain imports and `__all__` declarations only. They do
not duplicate implementations, register tools as an import side effect, or
introduce alternate state stores. Canonical package `__init__.py` files expose
the stable public symbols, while internal code imports from the owning module.

The compatibility surface includes:

- top-level package exports from `chartagent.__init__`;
- `Agent`, runtime factory/types, `AttachmentRegistry`, and review models and
  manager from their existing paths;
- current `tools` exports and direct registry/result/tool imports;
- current built-in and chart catalog entry points used by tests and callers.

The implementation will add import checks that import both canonical and
compatibility paths in a fresh interpreter, ensuring that compatibility is not
accidentally provided only because another module was imported first.

### 5. Migrate in dependency order and validate after each layer

The migration proceeds from low-level modules to composition roots:

1. Add `spec.identity` and the `tools/core` modules, retaining old exports.
2. Add built-in and chart canonical modules/catalogs, then move adapter
   factories out of domain services.
3. Split attachment and review packages, keeping their public re-exports.
4. Split runtime composition and prompt/readiness modules.
5. Split the Agent loop and its helper concerns.
6. Update Gateway/CLI/internal imports to canonical modules and remove only
   implementation duplication from compatibility shims.
7. Add structural import tests and run the targeted, full, and frontend/Gateway
   validations required by the repository.

Each stage keeps the old import path available and runs the relevant tests
before the next stage. No database or serialized-data migration is required.
Rollback is a source revert at the stage boundary; because compatibility
exports are retained, a partial deployment does not require coordinated
consumer changes.

## Risks / Trade-offs

- **[Risk]** Moving a module changes import initialization order and creates a
  circular dependency. **-> Mitigation:** keep low-level `spec` and `tools/core`
  dependency-free, inject or lazily import review sensor providers, and add a
  fresh-interpreter import matrix test.
- **[Risk]** A catalog is registered twice after both old and new entry points
  are active. **-> Mitigation:** make the runtime the sole registration owner,
  keep compatibility modules re-export-only, and assert the expected unique
  tool-name set in registry tests.
- **[Risk]** Direct consumers or tests depend on old module-level symbols or
  monkeypatch paths. **-> Mitigation:** retain thin shims for the existing
  paths and verify representative direct imports before removing any duplicate
  implementation.
- **[Risk]** Domain services accidentally regain model-facing concerns during
  the move. **-> Mitigation:** keep `load_image` and `review_generated_chart`
  factories under `tools/adapters`, and add dependency/ownership checks for
  service modules.
- **[Risk]** A refactor changes an opaque protocol even when visible behavior
  appears unchanged. **-> Mitigation:** snapshot tool names/schemas, result
  shapes, lifecycle event names, public exports, and Gateway startup behavior
  before and after the move.
- **[Trade-off]** Compatibility shims temporarily increase the number of
  files and names. **-> Mitigation:** document each shim's canonical target and
  defer removal to a separate breaking-change decision rather than mixing it
  into this structural refactor.
