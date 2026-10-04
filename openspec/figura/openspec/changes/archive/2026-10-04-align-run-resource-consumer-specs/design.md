## Context

See `proposal.md` for the reason for this alignment. The shared `run-execution-resources` spec and `src/figura/agent/execution_resources.py` define one typed resource catalog. The four consumer specs still describe separate legacy projections, and their Figure/render failure wording no longer matches the committed-resource behavior.

## Goals / Non-Goals

**Goals:** Make each consumer spec describe its current resource lookup and projection contract, preserving its domain-specific tool behavior.

**Non-Goals:** Change runtime code, tool schemas, persistence, resource ordering, or the shared resource model.

## Decisions

- Keep the four existing capability boundaries and modify only the requirements that refer to the obsolete fields.
- Use `run-execution-resources` as the source of truth for common typed-reference and resource-content rules. Consumer specs describe how measurement, OCR, Figure assembly, and rendering use that catalog.
- Distinguish committed failed resources from accepted successful Figures and renders. A failed result remains queryable by its typed resource reference; only a successful Figure that passes same-Session validation is accepted for rendering.
- Treat this as a specification-only reconciliation because the current `src/figura` implementation already follows the typed resource contract.

## Risks / Trade-offs

- **[A future resource-contract change may leave consumer specs stale again]** → Keep common reference and content rules in `run-execution-resources` and cross-check consumer deltas against that spec during validation.
- **[The delta may accidentally broaden runtime behavior]** → Preserve existing tool inputs and domain rules; change only the inaccurate resource access and projection descriptions.
