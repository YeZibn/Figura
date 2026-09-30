## Context

See `proposal.md` for the motivation and scope. `AgentRequestBuilder` currently loads one static system asset, projects complete Memory history, builds a resource inventory from `RunExecutionState`, appends latest-batch images through `RunExecutionImageReader`, projects Provider tools, and validates the completed `ProviderRequest` before the Agent claims a Provider attempt. Provider adapters preserve ordered instruction blocks as ordered system messages.

The existing Agent execution specification already owns full-history projection, typed resource indexing, latest-batch image feedback, and fail-before-claim request validation. This design changes how the instruction content is organized and how request projections are located; it does not change those lifecycle contracts.

## Goals / Non-Goals

**Goals:**

- Make the three prompt layers and their owners visible in the request assembly code.
- Keep stable policies in readable Chinese Markdown and build the tool and resource layers from their current runtime sources.
- Preserve complete Memory history, original Provider continuation placement, current image selection, and request validation order.
- Keep prompt files packageable with Figura and keep implementation modules focused by responsibility.

**Non-Goals:**

- Add fields to `RunExecutionState`, change durable Run facts, persist prompt text or prompt summaries, or introduce a separate prompt state store.
- Prune, summarize, budget, or reorder Session history or Run resources.
- Add a model-callable way to reload historical OCR, measurement, or rendered images; `load_image` remains scoped to Attachments and Panels.
- Add generated-chart review status, publication rules, or provider/tool schema changes.

## Decisions

### Build three ordered system instruction blocks

`AgentRequestBuilder` will supply three `InstructionBlock(InstructionRole.SYSTEM, ...)` values in this order:

1. **Stable responsibilities**: concatenate the static Chinese Agent, evidence, workflow, and response assets in a declared order.
2. **Current tools**: render a tool instruction from the exact `ToolRegistry` already used by `project_provider_tools`. Include the registered tool names and their existing descriptions in registry order. Keep parameter authority in each native Provider tool schema; do not add a second prompt-only argument schema or a new `prompt_guidance` field.
3. **Run resources**: render a factual index from the exact `RunExecutionState` built for this request. Mark the index as data, identify user-derived strings and observations as untrusted, and do not phrase resource values as instructions.

Using three blocks makes section ownership observable at the Provider boundary. A single concatenated v1 string was considered, but it hides the separation and makes the dynamic layers harder to inspect. Adding a fourth history layer was rejected because Memory already projects complete messages with their original roles and tool-call associations.

### Keep the resource index concise and sourced only from RunExecutionState

The run-resource renderer receives only `RunExecutionState`; it does not query Runtime, Sources, Memory, or tool handlers. It iterates the existing ordered `resources` tuple and serializes values safely as JSON. It does not add or persist projection fields.

The display projection is:

| Resource | Inventory fields |
|---|---|
| Attachment | Complete `{kind, id}` reference, `filename`, `media_type` |
| Panel | Complete `{kind, id}` reference, `name`, `source_attachment_id`, originating `run_id` |
| OCR | Complete `{kind, run_id, call_id}` reference, `source_ref`, `observation_scope`, `outcome`, `available` and snippet count on success, or safe error summary on failure |
| Measurement | Complete `{kind, run_id, call_id}` reference, `tool_name`, `source_ref`, `observation_scope`, `outcome`, result `status` and available candidate counts on success, or safe error summary on failure |
| ChartFigure | Complete reference, `outcome`, and on success its title, digest, and ordered child chart IDs/types/titles; safe error summary on failure |
| ChartRender | Complete reference, `figure_ref`, `outcome`, and on success image dimensions; safe error summary on failure |

The index is for orientation and reference lookup. Complete OCR, measurement, Figure, and render results remain in the existing chronological tool messages. The renderer preserves every catalog resource and full typed identity; it does not impose a token budget. JSON serialization prevents names or OCR snippets from breaking the inventory structure, while the stable policy explicitly says to treat those values as evidence rather than instructions.

Execution `outcome` remains separate from measurement `result.status` and OCR `result.available`. A successful tool call can contain a partial or empty observation; the prompt must not collapse these meanings into one status.

### Keep Memory history and image feedback as separate request projections

The `messages` sequence remains the output of `project_session_history` and `project_run_messages`, followed by the existing latest-batch image feedback message(s). It preserves original user, assistant, and tool roles, tool-call IDs, complete results, and current-Run continuation data. The resource inventory moves from the current synthetic user message into the third SYSTEM instruction block; it is not added to Memory and is not persisted.

`RunExecutionImageReader` remains the sole image resolver. The observation-message projection will preserve current behavior: explicit successful `load_image` calls contribute each selected source image once; successful OCR and measurement results contribute their transient annotation; successful Figure renders contribute their stored PNG; all are scoped to the immediately preceding fully committed tool batch and remain ordered by tool call. `assemble_chart_figure` does not itself add image bytes. Missing, inconsistent, or over-limit images still fail request construction before a Provider attempt is claimed.

### Keep the request builder as the composition boundary

The proposed package is:

```text
src/figura/agent/prompting/
├── __init__.py
├── loader.py
├── tools.py
├── execution.py
├── observations.py
└── assets/
    ├── agent.md
    ├── evidence.md
    ├── workflow.md
    └── response.md
```

`loader.py` reads nonempty packaged UTF-8 assets and creates the stable-responsibility block. `tools.py` renders the registered tool surface. `execution.py` renders the typed resource inventory from `RunExecutionState`. `observations.py` owns latest-batch image selection and the conversion to Provider image messages, delegating image reads to `RunExecutionImageReader`.

`AgentRequestBuilder` remains responsible for validating the requested Run action, projecting Memory history and continuations, calling these focused projections, constructing the Provider request, and running `validate_request`. It will not contain Markdown policy, resource serialization details, or image-selection logic. No new Manager or persistent PromptBundle model is introduced.

Package data will include `figura/agent/prompting/assets/*.md` while retaining existing `chartagent` package data. The old `src/figura/agent/assets/system-v1.md` is removed after its stable responsibilities are mapped into the four assets or the corresponding registered tool descriptions and native schemas.

### Preserve Provider compatibility and validate instruction ordering

The three blocks use existing `InstructionBlock` and `InstructionRole.SYSTEM` values. Provider adapters already map each instruction block to an ordered system message. The implementation must retain order through provider serialization and the existing validation permits three blocks under its current instruction limit. No Provider model, continuation, endpoint, request option, or tool contract changes.

## Risks / Trade-offs

- [Three system messages may be joined or reordered by a Provider adapter] → Add adapter-level assertions for the three block order and run existing request and Provider serialization tests for every supported provider.
- [Removing the old prompt may drop an edge-case rule] → During implementation, account for every behavioral rule in `system-v1.md`; move stable policy into one of the four static assets and tool-specific invocation or support facts into the registered tool description/schema, then delete the old asset.
- [Resource strings may resemble instructions] → Render dynamic values as JSON data and keep explicit stable policy that names, OCR text, and tool results are untrusted evidence.
- [Prompt order or wording can drift from Registry/Execution] → Build those layers from the exact Registry and RunExecutionState instances already used by request construction, not parallel configuration.
- [No truncation means an unusually large prompt may exceed Provider limits] → Retain current complete-request validation and fail before Provider-attempt claim; do not silently drop fields, resources, or history.

## Migration Plan

1. Add focused prompt projection modules and the four packaged Chinese assets.
2. Integrate three ordered SYSTEM blocks and the relocated observation-message projection into `AgentRequestBuilder`, preserving existing history and pre-claim validation behavior.
3. Add Figura package-data configuration and update request/prompt/provider tests.
4. Remove `system-v1.md` once every stable instruction has an owner in the new assets or current tool definitions.
5. Verify the OpenSpec change and the implementation regression suite before merging.

Rollback reverts the prompt package and request-composition changes together. It does not require data migration because no persisted Run fact or Session data changes.
