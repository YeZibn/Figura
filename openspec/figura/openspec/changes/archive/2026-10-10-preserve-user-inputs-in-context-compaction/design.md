## Context

See [proposal.md](proposal.md) for motivation and [the delta spec](specs/session-context-compaction/spec.md) for required behavior. `RunInput` already persists each Run's text, ordered attachment IDs, and input-record ID. `project_run_messages` reconstructs one `UserMessage` plus the Run's committed Assistant/tool messages. Context compaction groups these messages into complete Assistant/tool interactions, selects a raw suffix, and stores a source-linked summary checkpoint. The current Provider request projection filters covered messages by the checkpoint cursor, which also removes a covered Run's original user input from later ordinary requests.

The change affects request assembly, raw-history estimation, the summary request payload, and prompt instructions. Canonical Run storage and the summary output v2 fields do not need a database migration.

## Goals / Non-Goals

**Goals:**

- Put every prior Run's complete user input into one ordered, clearly labeled Provider message, independent of summary coverage.
- Preserve current input as the current native user message and avoid sending prior input text twice.
- Keep source and Run association visible when retained Assistant/tool process messages refer to historical inputs.
- Give each source Run's original input to the summary model separately from the incremental process slice.
- Keep historical-input token cost visible to request estimation while retaining independent approximate 10% process and summary budgets.
- Render the selected capacity and approximate summary target into each new summary instruction and freeze that rendered request for retry/recovery.

**Non-Goals:**

- Extracting inputs into a second requirements ledger, rewriting user text, deduplicating repeated inputs, or deciding that an input is obsolete.
- Adding a new persistent input table or changing the durable `RunInput` contract.
- Truncating or pruning historical user inputs when the request approaches Provider capacity.
- Changing the v2 summary JSON shape, small interaction boundary, tool-result handling, or abnormal-Run recovery policy.
- Guaranteeing that the Provider accepts an indefinitely growing full-input section or follows every historical request correctly.

## Decisions

### 1. Build the historical-input section from canonical Run inputs

For each prior Run in the same Session, read its validated `RunInput` and input `ExecutionRecord`. Build one ordered entry containing `run_ordinal`, `text`, ordered `attachment_ids`, and a `MessageSourceRef` made from the Run ID and input record ID. Preserve repeated or empty text as distinct entries. Do not persist a duplicate index: rebuild the section from the Run snapshot on each request. Exclude the active Run because its input already appears as the final native user message.

The section is a generated `ProviderMessage` with role `user` and a JSON object tagged `figura_context_type: historical_user_inputs`. Static Agent instructions explain that this tagged message is historical context data, not a new task; the message body itself remains data rather than system instruction text. If there are no prior Runs, omit the section.

### 2. Keep raw process messages native and add Run input locators

Compaction selection continues to form logical interaction units from the validated `UserMessage`, Assistant response, and its complete tool batch/results. For raw Provider projection, remove the old user message body because the dedicated input section already contains it. At the start of each contiguous raw Run segment, insert one compact generated user context message tagged `figura_context_type: historical_run_context` with the Run ID, ordinal, and exact input `MessageSourceRef`. Then append the original Assistant and tool messages unchanged. This gives the model a nearby link from retained work to its full input while keeping tool-call IDs, results, continuation association, order, and within-batch boundaries intact. A raw suffix beginning midway through a Run still receives the Run locator before its first retained process message.

The generated locator is request metadata, not a canonical user message and not a new ExecutionRecord. It contains no copied user text.

### 3. Keep historical input outside the two 10% budgets, but include it in actual estimates

The raw-history selector still uses complete logical interaction boundaries, but its unit estimate replaces the full `UserMessage` body with the compact locator estimate. This makes the raw budget describe retained process messages plus locators instead of charging the user text twice. The complete historical-input message is included in the actual prepared ordinary request and therefore in the selected Provider's local context estimate used by the 80% trigger and post-compaction check.

Historical inputs are never removed to satisfy either 10% budget. If their combined size plus instructions, process context, resources, active input, and completion allowance exceeds the selected Provider's usable context, compaction cannot make those preserved inputs fit. Request preparation follows the existing capacity/error path and reports no successful Provider attempt. The implementation SHALL NOT silently drop or truncate any input.

### 4. Pass source Run input separately into summary generation

In the summary request's `source_runs`, put each selected Run's complete original input in an `input` object containing `text`, `attachment_ids`, and the exact input `reference`. Keep `messages` limited to the newly covered Assistant/tool process slice and exclude the `UserMessage` body. The same Run input may be supplied again when a later operation summarizes a newly covered slice from that Run; it gives the model stable task context without reclassifying earlier process messages as newly covered.

Include each supplied input reference in the request's authorized reference set. It can support summary items that preserve user intent. The summary remains the derived compact projection; the ordinary request's full-input section is authoritative for exact user wording. Attachments are passed as IDs only; summary generation does not load image bytes.

### 5. Render the soft summary target into the operation's prompt

When constructing a new summary request, pass the operation's frozen `context_capacity_tokens` and `summary_budget_tokens` to the compaction instruction builder. The Markdown asset contains explicit placeholders for capacity and the approximate target; replace only those named placeholders so JSON examples in the Markdown remain untouched. For capacity `C`, the rendered target is `floor(C / 10)`. State that the target concerns the complete generated summary JSON, is approximate, and must not cause padding, omission of key evidence, JSON truncation, or a second rewrite solely for length.

Use the rendered instruction in the existing prompt digest and prepared request descriptor. A retry or restart of a bound operation reconstructs the same source payload and instruction and verifies the existing request identity. New operations use the capacity loaded for the currently selected Provider; changing `.env` still takes effect through the existing Gateway restart/configuration lifecycle.

### 6. Preserve the small interaction unit and coverage cursor

The cutoff remains a process-message cursor. Its final Assistant record and tool sequence still must land after a whole committed interaction. Historical user input has its own stable input-record reference and is always projected separately, so moving the process cutoff does not hide or duplicate it. Existing checkpoint coverage continues to control which process messages enter the summary and which remain raw.

## Risks / Trade-offs

- [Risk] The ordered input section grows with every prior user message and can itself exceed Provider capacity. → Count it in every prepared-request estimate, preserve it without silent clipping, and use the existing request-preparation failure behavior when no valid request fits.
- [Risk] Historical inputs may contain quoted examples, copied instructions, or prompt-injection text. → Send the generated section as a user-role data message with a fixed `figura_context_type`, and explicitly instruct the Agent that it is historical context; current system rules and the active user request retain precedence.
- [Risk] Run locators add small repeated token overhead and may alter exact provider history wire shape. → Emit one locator per contiguous raw Run segment, preserve native Assistant/tool messages unchanged, and validate provider-specific continuation and tool-pair contracts.
- [Risk] Summary instructions gain dynamic text and existing in-progress operations may have a request descriptor produced by an earlier prompt asset. → Bind the rendered prompt to new operation descriptors, preserve retry identity checks, and keep the previous valid checkpoint if an old operation cannot be reconstructed exactly.
- [Risk] A soft 10% instruction cannot guarantee the model's actual completion length. → Keep it as guidance only; preserve structurally valid source-linked output and estimate the rebuilt ordinary request locally.

## Migration Plan

No SQLite schema migration is needed. Deploy the request-projection and prompt changes together. Existing Run inputs and summary checkpoints remain readable; the next ordinary request reconstructs the historical-input section from canonical Run facts. A newly created compaction operation binds the rendered target and source slice. If a pending operation cannot reproduce its bound request after an asset change, keep the existing checkpoint and follow the current safe fallback path rather than replacing it with a different summary.

## Open Questions

None. The selected behavior, input-section role, history ordering, budget treatment, and overflow behavior are defined above.
