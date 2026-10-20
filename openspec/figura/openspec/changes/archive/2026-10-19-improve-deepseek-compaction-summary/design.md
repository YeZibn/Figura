## Context

See `proposal.md` for the motivation and `specs/session-context-compaction/spec.md` for the behavior contract. Summary requests are built separately from ordinary Agent requests, but currently specify only non-streaming mode, so Provider reasoning settings are inherited. The DeepSeek adapter already supports `thinking_mode` and `reasoning_effort="medium"`; the summary validator currently rejects every response continuation before reading `assistant_content`. Provider request descriptors are frozen for retry and recovery, so a reasoning override must be selected before the descriptor is bound.

## Goals / Non-Goals

**Goals:**

- Give only new DeepSeek compaction requests an explicit medium-thinking configuration.
- Accept DeepSeek's private continuation alongside a valid final summary without turning that continuation into summary data.
- Keep retries, recovery, and previous checkpoints deterministic and safe.

**Non-Goals:**

- Change ordinary Agent reasoning configuration, other Providers, compaction thresholds or budgets, summary schema, prompt target, or full-history fallback policy.
- Change database schema or migrate completed checkpoints.
- Change the Provider adapter's support for DeepSeek reasoning levels; `medium` is already supported.

## Decisions

### Set provider-specific options while building the summary request

The summary request builder will continue to set `stream=False`. When the selected Provider is DeepSeek, it will additionally set `thinking_mode=True` and `reasoning_effort="medium"`. For other Providers it will keep the existing option behavior. The resulting prepared options must be represented in the existing frozen Provider request descriptor; the Provider adapter remains responsible for translating them to the DeepSeek payload.

This keeps the policy at the summary-request boundary. Changing `.env` or the shared Provider profile would also affect ordinary Agent turns and would not express the intended scope. Relying on inherited defaults would preserve the failure observed in the experiment.

### Validate the final response separately from DeepSeek continuation

The summary validator will keep the existing checks for Provider/model identity, stopped finish reason, absence of tool calls, and valid assistant text. It will permit a continuation only when the response Provider is DeepSeek and the continuation belongs to that same Provider. JSON parsing, schema validation, and source-reference authorization will use `assistant_content` only. The normalized summary returned for checkpoint installation will contain no continuation field.

Other Providers retain the current no-continuation summary contract. Invalid or missing final content remains a rejected summary and follows the existing fallback path. This permits the provider response envelope without weakening the summary's actual data contract.

### Do not rewrite an already frozen operation

New operations bind the explicit medium options before dispatch. Recovery must continue to honor request identity: if an unfinished operation is already bound to different DeepSeek reasoning options, it will not be mutated or dispatched under a new fingerprint. Resolve it using the existing safe fallback path, preserve the prior valid checkpoint, and let a later newly created operation use the updated policy. Completed checkpoints require no migration.

### Verify locally before using the live experiment

Automated tests will stub Provider responses and verify request options, DeepSeek payload projection, continuation acceptance, summary-content validation, checkpoint exclusion, and unchanged ordinary/other-Provider settings. After those checks pass, run one real DeepSeek summary smoke test. Resume the paired context experiment only if that smoke test installs a valid checkpoint. The experiment must skip a summary request when its estimated input plus configured completion budget exceeds the selected context capacity. Compare Provider input tokens only for the same fact questions answered correctly by both arms, and count the shared summary-generation request once per repetition.

## Risks / Trade-offs

- **Medium thinking can increase summary latency or completion usage** → keep it scoped to the additional summary request and measure the real smoke call before rerunning the experiment.
- **Allowing a continuation could accidentally expose private reasoning** → accept it only in DeepSeek's response envelope, never parse it as summary content, and test that it is absent from the installed checkpoint and ordinary request projection.
- **An older frozen operation may not use the new options** → preserve the operation identity and safely fall back instead of silently rebinding it.
- **The live endpoint may behave differently from the adapter contract** → require the single real smoke test before interpreting A/B results.

## Migration Plan

No storage migration is required. New DeepSeek compaction operations use the explicit medium options. Completed checkpoints remain valid as-is. Any unfinished operation frozen under different reasoning options resolves through the existing fallback behavior; a subsequent operation can be created with the new policy. Rollback consists of reverting the summary-request override and DeepSeek-only continuation allowance, while leaving established checkpoints and canonical Run history intact.
