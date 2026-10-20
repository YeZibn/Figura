## 1. DeepSeek Summary Request Options

- [x] 1.1 Set `thinking_mode=true` and `reasoning_effort="medium"` only for newly built DeepSeek compaction requests, and verify the options are frozen into the request descriptor.
- [x] 1.2 Ensure unfinished operations bound to different DeepSeek reasoning options safely fall back without mutating or dispatching the frozen request.
- [x] 1.3 Add tests for the DeepSeek payload, frozen retry options, unchanged ordinary DeepSeek requests, and unchanged non-DeepSeek summary settings.

## 2. Summary Response Contract

- [x] 2.1 Allow a DeepSeek continuation only when Provider identity matches, while continuing to validate JSON and source references from final assistant content alone.
- [x] 2.2 Ensure continuation content is excluded from the installed summary checkpoint and ordinary Agent history; preserve rejection and fallback for invalid final content.
- [x] 2.3 Add tests for valid DeepSeek content with continuation, invalid/missing final content, provider mismatch, checkpoint privacy, and unchanged non-DeepSeek validation.

## 3. Verification and Experiment

- [x] 3.1 Run focused Provider and context-compaction tests, then the relevant broader Figura test suite.
- [x] 3.2 Run one real DeepSeek compaction smoke test and confirm a source-valid checkpoint installs without exposing continuation content.
- [x] 3.3 Guard the paired experiment against over-capacity summary dispatch; rerun it and compare Provider input-token totals only for identical fact questions answered correctly by both arms, counting summary generation once.
