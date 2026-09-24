## Context

The Agent already has a post-generation hook and a `ChartReviewManager` that
can block a final answer while a candidate is pending. The tool description
contract and generated-chart review lifecycle are already implemented by
archived changes. The remaining work is limited to prompt organization,
review-gate context, lifecycle projection, and frontend presentation.

## Goals / Non-Goals

**Goals:**

- Make the default prompt a concise static behavior contract covering evidence,
  tool choice, generated-chart review, and final-answer claims.
- Represent a pending review as a candidate-specific obligation with bounded
  structured context.
- Reuse existing review state and tool metadata without creating a second state
  machine or rewriting completed tool contracts.
- Distinguish tool execution, review, and publication in events and UI.
- Preserve existing names, schemas, event kinds, artifact references, and
  review algorithms.

**Non-Goals:**

- Introducing explicit Agent phases or phase-specific tool allowlists.
- Rewriting tool descriptions, parameter schemas, or the tool presentation
  catalog.
- Replacing deterministic review checks or changing review policy thresholds.
- Changing chart rendering, Gateway publication rules, or machine identifiers.

## Decisions

### 1. Use review obligations instead of a phase machine

`ChartReviewManager` remains the source of truth. A pending candidate creates a
review obligation; the Agent checks whether that obligation is unresolved
before accepting a final answer. The Agent does not maintain another lifecycle
state machine. This supports retries and multiple candidates without adding
phase re-entry and tool-permission rules.

### 2. Keep the system prompt static and inject structured obligations

`runtime/prompts.py` will organize one stable prompt into role, evidence,
tool-use, generation, review, and answer-boundary sections. It will not contain
mutable candidate IDs. When a review is pending, the Agent will append bounded
structured gate context containing `required_action`, candidate and review IDs,
and the existing candidate, review, and publication states.

### 3. Make the existing review tool available through normal runtime setup

Runtime construction will expose `review_generated_chart` through the regular
tool surface using the existing manager. Its description, parameters, stable
name, and callable behavior remain unchanged. Other evidence, ChartSpec, and
regeneration tools remain available so a failed review can be repaired.

### 4. Separate lifecycle state dimensions at projection boundaries

Events and generated-chart projections will use `tool_status` for execution,
`candidate_status` for the candidate, `review_status` for review, and
`publication_status` for publication. Existing generic fields remain readable
for compatibility, but new chart lifecycle payloads do not overload one
generic `status` field.

`chart_review_started` means that a candidate-specific review obligation is
pending or has started. It does not mean review passed or publication
succeeded. Completion, publication, and rejection retain separate events.

### 5. Reuse existing presentation metadata

The existing bilingual tool catalog remains the source for tool labels. A
small lifecycle-event label mapping will complete Simplified Chinese labels;
unknown event kinds and tool names fall back to their stable English IDs.

## Risks / Trade-offs

- **[Risk]** The model ignores the obligation. **Mitigation:** the final-answer
  gate remains code-enforced and budget limits terminate without publication.
- **[Risk]** Older clients read only generic `status`. **Mitigation:** retain
  compatible fields and make new fields additive.
- **[Risk]** Stable review-tool registration changes tool counts in tests.
  **Mitigation:** update Agent contract tests while keeping the existing tool
  schema unchanged.
- **[Risk]** Structured gate context consumes tokens. **Mitigation:** include
  bounded metadata only, never image bytes or duplicate history.

## Migration Plan

1. Reorganize the static prompt and add structured review-gate context.
2. Register the existing review tool through normal runtime composition and
   preserve direct-Agent compatibility.
3. Project independent lifecycle fields and correct review-start semantics.
4. Connect existing tool labels, add lifecycle labels, and update generated
   chart presentation.
5. Run focused tests, the full Python suite, frontend checks, and strict
   OpenSpec validation.

No database migration is required. Existing events and artifacts remain
readable through compatibility fallbacks.

