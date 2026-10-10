## 1. Historical input projection

- [x] 1.1 Build a chronological historical-input payload from every validated prior Run input, preserving exact text, ordered attachment IDs, and the input message source reference; exclude the active Run input.
- [x] 1.2 Add a tagged user-role context message for the historical-input payload and static guidance that treats it as historical data while preserving current-request precedence.
- [x] 1.3 Project one compact source locator before each retained raw Run process segment; omit the duplicated historical user body while keeping the original Assistant/tool message order and call/result pairing.

## 2. Compaction source and budget flow

- [x] 2.1 Update summary request construction to pass each selected Run's original input separately from only its newly covered process messages, and authorize the input source reference for summary validation.
- [x] 2.2 Update raw interaction token estimation to count process messages and source locators without charging the historical input body twice; ensure ordinary-request preparation estimates the complete historical-input section.
- [x] 2.3 Render the frozen context capacity and approximate `floor(C / 10)` summary target into the compaction Markdown instruction using explicit placeholder replacement; include the rendered prompt in the existing request digest and recovery identity.
- [x] 2.4 Preserve the existing complete interaction cutoff, abnormal-history behavior, valid-summary handling, and request fallback when the complete inputs exceed usable Provider capacity.

## 3. Prompt and implementation documentation

- [x] 3.1 Update `compaction.md` with the dynamic soft target, the distinction between complete user inputs and process summaries, and instructions not to repeat full inputs in the generated summary.
- [x] 3.2 Update ordinary Agent prompt guidance and the relevant Memory/Agent/context-compaction documentation to describe the historical-input section, Run locators, source references, and input-driven request growth.

## 4. Regression coverage and validation

- [x] 4.1 Cover chronological exact input preservation, duplicate/empty inputs, attachment IDs, source references, active-input non-duplication, and exclusion of historical input bodies from raw process messages.
- [x] 4.2 Cover Run locators at whole-Run and partial-Run raw suffixes, unchanged tool batches/results and Provider continuations, and summary requests carrying the original input with only newly covered process messages.
- [x] 4.3 Cover dynamic capacity/summary-target rendering, prompt digest changes, frozen retry/recovery identity, actual request estimates including all historical inputs, and no silent truncation on capacity overflow.
- [x] 4.4 Run focused request, prompting, compaction, Provider-history, and recovery tests, then validate the OpenSpec change.
