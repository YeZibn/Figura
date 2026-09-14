## Why

Figura's top-level Python modules and `tools/` package currently mix orchestration, domain services, tool adapters, protocol exports, and chart algorithms. Broad names such as `runtime.py`, `review.py`, `data.py`, `geometry.py`, and `register.py` make ownership unclear and force unrelated changes through large modules. The package needs a clearer structure before more tool and review capabilities are added.

## What Changes

- Turn the top-level Agent, runtime, attachment, and review modules into packages with focused submodules while preserving their existing import surfaces through package exports.
- Organize tool infrastructure, tool adapters, built-in tools, chart tools, and external protocol integrations into explicit package boundaries.
- Rename broad implementation modules to capability-oriented names, such as `filesystem`, `json`, `bars`, `catalog`, and `rendering`.
- Separate domain services from Tool factories: attachment and generated-chart review services remain domain APIs, while model-facing Tool adapters live under the tool adapter layer.
- Move shared ChartSpec identity logic to a lower-level specification module so rendering and review do not depend on each other.
- Preserve stable function-calling names, parameter names, result protocols, lifecycle events, public imports, and callable behavior.
- Add structural import and compatibility checks so the reorganization does not introduce dependency cycles or break existing consumers.

## Capabilities

### New Capabilities

None. This is a source-organization refactor with no new user-facing behavior.

### Modified Capabilities

None. Existing behavior contracts remain unchanged; the change opts out of behavior-level spec deltas with `skip_specs: true`.

## Impact

- Affects the `src/chartagent/` package layout, imports, package exports, and test import paths.
- Touches Agent/runtime composition, attachment and review service boundaries, chart tool registration, and OpenAI/MCP integration modules.
- Requires compatibility re-exports during migration and targeted tests for imports, registry composition, dispatch, generated-chart review, and Gateway startup.
- Does not change persisted data formats, tool names, JSON result shapes, trace event names, or frontend contracts.
