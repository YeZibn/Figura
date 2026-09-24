## 1. Shared attachment turn construction

- [x] 1.1 Add a helper in `src/chartagent/multimodal.py` that appends a clearly labeled, numbered local-path block to the user text and delegates image encoding to the existing `build_user_content`, using one ordered path sequence for both.
- [x] 1.2 Export the new helper from `chartagent` without changing the signature or output contract of `build_user_content`.
- [x] 1.3 Add multimodal tests for one and multiple paths, asserting model-visible path/image order and confirming the raw builder remains unchanged.

## 2. Attachment syntax and REPL wiring

- [x] 2.1 Extend `extract_image_refs` to recognize both unquoted `@path` and double-quoted `@"path with spaces"` references in encounter order, while leaving unterminated quoted input as text.
- [x] 2.2 Update `run_agent_repl` to use the shared attachment turn builder when paths are present and preserve the original plain string when none are present.
- [x] 2.3 Add CLI tests for quoted paths, mixed quoted/unquoted attachments, normalized remaining text, path metadata forwarding, missing files, and unchanged plain input.

## 3. Free chart-aware agent guidance

- [x] 3.1 Define an advisory default system prompt for the agent REPL that describes visual inspection and the four chart tools, tells the model to choose tools only when useful, and does not prescribe a sequence or require ChartSpec output.
- [x] 3.2 Add tests that the agent REPL uses the advisory default, still accepts an explicit system override, and does not alter the default `Conversation` REPL.

## 4. End-to-end acceptance

- [x] 4.1 Refactor `scripts/smoke_chart_understanding.py` to use the shared attachment turn builder and the agent REPL default prompt, with a user request that neither repeats the local path nor names a tool sequence.
- [x] 4.2 Change live-smoke acceptance to validate the returned ChartSpec and ground-truth dataset while reporting the observed tool trace diagnostically without asserting a fixed call order.
- [x] 4.3 Run the live endpoint smoke on both synthetic U0 charts and record whether free planning restores both datasets successfully.

## 5. Verification

- [x] 5.1 Run the complete test suite in the conda `agent` environment and confirm all existing Agent, CLI, multimodal, tool, and chart-understanding behavior remains green.
- [x] 5.2 Run strict OpenSpec validation and `git diff --check` for the completed change.
