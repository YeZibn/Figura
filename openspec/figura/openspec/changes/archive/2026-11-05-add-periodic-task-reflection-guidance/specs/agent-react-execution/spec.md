## ADDED Requirements

### Requirement: Agent periodically rechecks task direction
For an ordinary model request, Figura SHALL count committed ordinary model responses in the authorized current Run. When that count is a positive multiple of 20 and another ordinary model request is prepared, the dynamic running-state SYSTEM instruction SHALL include one `task_reflection` entry with `completed_rounds` set to the committed response count and `interval_rounds` set to 20. The entry SHALL appear in the next ordinary request after the preceding tool batch is resolved. A single model response SHALL count once regardless of the number of calls in its batch.

Tool executions and results, Provider attempts and transport retries, context-compaction requests, and model responses from earlier Runs SHALL NOT increase the current Run's count. The count SHALL be derived from committed Run facts without a new cumulative quota, persistent counter, database field, or public API field.

#### Scenario: Include a reminder after twenty committed responses
- **WHEN** the authorized current Run contains twenty committed ordinary model responses and execution prepares the next ordinary model request
- **THEN** its dynamic running-state SYSTEM instruction contains `task_reflection` with `completed_rounds: 20` and `interval_rounds: 20`

#### Scenario: Count a multi-call response once
- **WHEN** the twentieth committed model response contains multiple tool calls
- **THEN** Figura resolves the complete ordered tool batch and includes one task-reflection entry in the next ordinary model request

#### Scenario: Repeat at each twentieth response only
- **WHEN** execution prepares ordinary model requests after 19, 20, 21, and 40 committed responses in the current Run
- **THEN** the reflection entry is absent after 19 and 21 responses and present after 20 and 40 responses with the matching count

#### Scenario: Exclude attempts, tools, summaries, and earlier Runs
- **WHEN** the current Run has Provider retries, tool executions, or context-compaction requests, or an earlier Run has committed model responses
- **THEN** none of those events or responses increase the current Run's ordinary response count

### Requirement: Task reflection preserves Agent autonomy and evidence boundaries
When `task_reflection` is present, the Agent instructions SHALL direct the model to compare the original user request with completed work and its available evidence, identify unmet requirements or unsupported results, consider whether recent actions reduced those gaps, and choose a useful next action. The model SHALL remain free to continue, correct its approach, or deliver supported results with limitations. The entry SHALL NOT assert that the task is wrong or complete, force termination, restrict valid tool calls, require a separate reflection report, create another model request, or represent the round count as a hard Run limit. Source values and retrieved content SHALL remain untrusted data.

#### Scenario: Continue when an effective path remains
- **WHEN** the reflection entry is present and the model identifies a task-relevant action that can resolve an unmet requirement
- **THEN** the model may select that action through the existing ReAct decision path

#### Scenario: Correct unsupported or misdirected work
- **WHEN** the reflection entry is present and the model identifies an unsupported result or work that does not address the original request
- **THEN** the model may correct the approach or result using available evidence without treating prior execution as proof of correctness

#### Scenario: Deliver when further actions cannot address the gap
- **WHEN** the reflection entry is present and no available action can materially resolve the remaining gap
- **THEN** the model may deliver the supported result and explain its limitations without being required to fabricate completion

### Requirement: Task reflection is reproducible across execution recovery
Figura SHALL derive `task_reflection` from the same authorized committed current Run prefix used to prepare the ordinary model request. Restarting execution or compacting covered history SHALL NOT reset or alter the count for an unchanged committed prefix. Context-compaction requests SHALL NOT receive `task_reflection`. A Provider retry SHALL preserve its existing frozen request binding and SHALL NOT add a second count or recompute different reflection metadata from a later Run prefix.

#### Scenario: Rebuild the same reminder after restart or compaction
- **WHEN** execution restarts or history is compacted while the authorized committed current Run prefix remains unchanged
- **THEN** the next newly prepared ordinary request derives the same reflection count and entry

#### Scenario: Preserve the bound entry on Provider retry
- **WHEN** an ordinary Provider request containing `task_reflection` is retried after a transport failure
- **THEN** Figura reproduces the bound request and its reflection entry subject to existing request identity checks

#### Scenario: Keep the summary request dedicated
- **WHEN** Figura prepares a context-compaction request while the current Run has reached a reflection interval
- **THEN** the summary request follows its existing contract without a `task_reflection` entry
