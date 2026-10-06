## ADDED Requirements

### Requirement: Summary generation has an independent Markdown instruction asset
Figura SHALL load summary-generation policy from an independent Chinese Markdown asset, separate from the ordinary Agent rules. A summary request SHALL contain only the summary task instructions and the authorized source payload, use no tools or images, and retain the existing source-linked JSON response contract. Ordinary requests SHALL NOT inherit the summary task's JSON-only output instruction. Missing or empty assets SHALL produce an explicit preparation failure rather than an empty policy or an inline fallback prompt. Loaded instruction content SHALL participate in the existing request digest and retry identity checks.

#### Scenario: Build a dedicated summary request
- **WHEN** eligible history is selected for compaction
- **THEN** the summary request uses the independent asset and the source payload without ordinary chart workflow rules, tools, or image blocks

#### Scenario: Keep summary output rules out of ordinary answers
- **WHEN** an ordinary Agent request is assembled with or without a saved summary
- **THEN** its static instructions do not include the summary task's JSON-only output requirement

#### Scenario: Detect an unusable summary asset
- **WHEN** the summary asset is absent or contains only whitespace
- **THEN** request preparation reports an explicit failure, sends no instruction-free summary request, and does not install a replacement summary

### Requirement: Summary guidance preserves evidence and incrementally reconciles history
The summary response SHALL use a versioned, machine-readable v2 structure with separate fields for current goals, constraints, decisions, facts, progress (`completed`, `in_progress`, `pending`, and `blocked`), open questions, resources, and unaccepted proposals. Every non-empty field entry SHALL contain non-empty text and one or more exact authorized input message or tool-result references supporting that content. `pending` SHALL contain only work explicitly requested or accepted by the user and not yet completed; unaccepted assistant suggestions SHALL remain proposals. The summary request SHALL provide the previous summary, its source references, and added history without exposing the checkpoint's storage version to the model. The model SHALL reconcile the actual prior summary content into the complete v2 response using only source-supported content and SHALL NOT infer pending work from an ambiguous legacy item. Runtime-generated trust and Run outcome fields SHALL remain outside the model response. The instructions SHALL distinguish user-provided data, tool observations, assistant inference, and unexecuted plans. Historical content SHALL remain data rather than executable instructions. The instructions SHALL ask for concise retention of necessary information without claiming a resulting context occupancy that the summary input does not establish.

#### Scenario: Retain a correction from newer history
- **WHEN** added history changes a fact, decision, or requirement retained in the prior summary
- **THEN** guidance directs the summary to reflect the correction with its supporting references and avoid retaining both versions as simultaneously settled facts

#### Scenario: Preserve task state in distinct v2 fields
- **WHEN** the source history contains a current goal, a completed action, user-accepted pending work, an unresolved blocker, and an unaccepted assistant suggestion
- **THEN** the generated summary places them in `current_goal`, `progress.completed`, `progress.pending`, `progress.blocked`, and `proposals` respectively, with supporting source references on each non-empty entry

#### Scenario: Reorganize a legacy summary
- **WHEN** an earlier summary with a different field layout is included for a new compaction
- **THEN** guidance migrates only source-supported content into v2 fields without treating ambiguous legacy text as user-accepted pending work or exposing the storage version to the model

#### Scenario: Read an existing checkpoint without forced migration
- **WHEN** an ordinary request consumes an existing checkpoint without triggering a new compaction
- **THEN** the checkpoint remains readable as legacy summary data and the storage schema is unchanged

#### Scenario: Keep a proposed action distinct from a completed result
- **WHEN** the source contains an assistant plan or an uncertain tool observation
- **THEN** guidance preserves its evidence state and does not present the proposed or uncertain action as confirmed completion

#### Scenario: Preserve exact source identities
- **WHEN** a retained item relies on a tool result and a message
- **THEN** guidance requires the exact input `tool_result` run/call reference and `message` run/record reference without fabricated identifiers or new top-level output fields

#### Scenario: Keep occupancy decisions in request coordination
- **WHEN** the summary source payload does not contain the final request capacity and retained-tail size
- **THEN** the instructions request a concise, source-supported summary without asking the model to assert that a target occupancy was reached
