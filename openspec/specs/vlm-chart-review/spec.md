# vlm-chart-review Specification

## Purpose

为生成图表提供一次自动、统一且可追踪的多模态语义审核，使 VLM 能够直接结合原图、ChartSpec 和候选图判断旋转、横向布局、标签关联、数值映射与可读性，而不依赖审核阶段的 OCR、CV 或测量工具。

## Requirements

### Requirement: Semantic chart review is performed by an internal tool-free VLM

For every generated chart candidate whose review policy requires semantic
review, the system SHALL automatically perform one additional multimodal VLM
review call after rendering. The review call SHALL not expose or invoke OCR,
CV, geometry, layout, chart-measurement, or generated-chart review tools, and
the main Agent SHALL not be responsible for deciding whether to invoke it.

#### Scenario: Source-linked candidate is reviewed automatically

- **WHEN** a ChartSpec derived from an authorized source attachment is rendered
  into a candidate image
- **THEN** the system automatically invokes one VLM review call before
  publication
- **AND** the review call has no tools available
- **AND** the candidate remains unpublished until the review result is applied

#### Scenario: Review receives the required visual and structured context

- **WHEN** the internal VLM review call is prepared for a source-linked
  candidate
- **THEN** it receives the authorized source image, the generated candidate
  image, and the immutable ChartSpec represented by the candidate
- **AND** it can distinguish source-versus-candidate comparison from
  candidate-versus-spec comparison
- **AND** local paths, credentials, raw provider payloads, and unrelated
  attachments are not included

#### Scenario: Direct-data candidate has no source-fidelity claim

- **WHEN** a candidate is generated only from user-supplied structured data and
  its policy does not require semantic review
- **THEN** the system does not claim that a source comparison was performed
- **AND** the candidate still passes the applicable structural and encoded
  artifact safety checks before publication

### Requirement: VLM review returns a bounded structured decision

The internal reviewer SHALL return exactly one JSON object with exactly four
top-level fields: `decision`, `confidence`, `checks`, and `issues`. `decision`
SHALL be `pass`, `pass_with_warning`, or `fail`. `confidence` SHALL be a
number in the range 0..1. `checks` SHALL contain exactly
`chart_type`, `orientation`, `layout`, `data_mapping`, `labels`, and
`readability`, with each value equal to `pass`, `warning`, or `fail`.

`issues` SHALL be an array of at most 32 objects. Each issue SHALL contain
non-empty bounded `code`, `location`, and `message` strings and a `severity`
of `warning` or `error`. The review SHALL cover chart type, whole-canvas
rotation, horizontal-versus-vertical orientation, axis direction, category
order, series identity, values or relative geometry, zero-baseline or other
geometric relationships, labels, and readability. Bar, line, pie, and scatter
charts SHALL receive the corresponding chart-specific visual checks.

The decision SHALL be internally consistent: `pass` requires all checks to be
`pass` and no issues; `pass_with_warning` permits no failed check or error and
requires a warning detail; `fail` requires a failed check or error issue. A
critical relationship that cannot be verified SHALL NOT be treated as a pass.
A missing, malformed, ambiguous, extra-field, or out-of-contract response
SHALL NOT be treated as a pass.

#### Scenario: VLM identifies a clean match

- **WHEN** the candidate matches the ChartSpec and, when applicable, the
  source image across the required visual checks
- **THEN** the reviewer returns the exact four-field JSON contract with
  `decision: pass`
- **AND** all six check values are `pass`
- **AND** `issues` is an empty array

#### Scenario: VLM identifies a blocking visual mismatch

- **WHEN** the candidate has a wrong orientation, category order, series
  association, value mapping, label association, baseline relationship, or
  another critical visual mismatch
- **THEN** the reviewer returns `decision: fail`
- **AND** at least one check is `fail` or one issue has `severity: error`
- **AND** the issue identifies the affected ChartSpec field or visual region
  with a bounded explanation
- **AND** the candidate cannot be published

#### Scenario: VLM identifies a non-blocking concern

- **WHEN** the data mapping is credible but the candidate has a bounded
  readability, density, or non-critical visual concern allowed by policy
- **THEN** the reviewer returns `decision: pass_with_warning`
- **AND** no check is `fail` and no issue has `severity: error`
- **AND** at least one check or issue records a warning
- **AND** the warning is retained in the candidate's bounded review metadata
- **AND** publication, if allowed, remains explicitly qualified

#### Scenario: VLM reports an incorrect bar baseline

- **WHEN** a vertical bar chart's bar bottoms do not align with the coordinate
  system's zero baseline, or a horizontal bar chart's bar starts do not align
  with the zero baseline
- **THEN** the reviewer records a layout or data-mapping failure with a
  location such as `candidate.plot_area.zero_baseline`
- **AND** the result has `decision: fail` and an error issue
- **AND** the image bottom or plot-frame edge is not accepted as the baseline
  merely because it is visually closest

#### Scenario: Invalid reviewer output is rejected

- **WHEN** the VLM response is not valid JSON, contains extra top-level fields,
  omits a required field, uses an unknown enum, has an out-of-range confidence,
  violates the decision consistency rules, or contains unbounded issue data
- **THEN** the system records a bounded review failure
- **AND** it does not publish the candidate or infer a pass from free-form text

### Requirement: Review decisions are code-enforced publication transitions

The system SHALL apply the validated VLM decision atomically to the
candidate's review and publication state. Only `pass` MAY transition a
candidate to `published`, and only an allowed `pass_with_warning` MAY
transition it to `published_with_warning`; `fail`, invalid output, timeout,
or unavailable source evidence SHALL transition it to a non-published state.
The main Agent SHALL not be able to override the transition with a final answer
or a model-generated review claim.

#### Scenario: Passing review promotes the candidate

- **WHEN** a candidate's required safety checks pass and its VLM decision is
  `pass`
- **THEN** the candidate becomes verified and published with bounded review
  metadata
- **AND** the Gateway may expose the corresponding final artifact

#### Scenario: Failed review rejects the candidate

- **WHEN** the VLM decision is `fail` or the review cannot be completed
- **THEN** the candidate becomes review-failed, timed-out, or retry-exhausted
  according to the failure cause
- **AND** no final artifact reference is issued
- **AND** a final Agent response cannot describe the candidate as verified or
  published

#### Scenario: Review result cannot be applied to another candidate

- **WHEN** a review result carries a missing, stale, or mismatched candidate
  reference, review reference, or ChartSpec digest
- **THEN** the system rejects the result with a bounded error
- **AND** no other candidate's publication state changes

### Requirement: VLM review failures support bounded correction and retry

When a VLM review fails for a correctable visual or semantic issue, the system
SHALL provide the bounded review diagnostics to the main Agent so it can revise
the ChartSpec and request a new candidate. Review calls and candidate retries
SHALL obey the configured attempt, timeout, and size limits, and an exhausted
limit SHALL produce a terminal non-published state.

#### Scenario: Blocking issue is repaired with a new candidate

- **WHEN** a VLM review rejects a candidate with a correctable issue and retry
  budget remains
- **THEN** the main Agent receives the issue location and bounded explanation
- **AND** it can assemble a corrected ChartSpec and render a new candidate
- **AND** the rejected candidate remains attributable and unpublished

#### Scenario: Review timeout is bounded

- **WHEN** the internal VLM review call exceeds its deadline or fails repeatedly
- **THEN** the system records a bounded timeout or retry-exhausted state
- **AND** it does not leave the candidate indefinitely pending
- **AND** it does not publish the candidate

### Requirement: Review performs source binding preflight

对 source-linked 候选执行 VLM 审核前，系统 SHALL 先确认源附件仍属于当前 session、可访问且内容哈希匹配。源附件缺失时 SHALL 返回 source binding failure，而不得把它伪装成图表语义审核失败。

#### Scenario: Active source is recovered before review

- **WHEN** 当前 run 没有新附件但 session 有有效 active source
- **THEN** 审核使用恢复后的源附件执行
- **AND** 不返回 source_evidence_unavailable

### Requirement: Review failures provide structured recovery diagnostics

VLM 审核拒绝候选时 SHALL 返回状态、问题代码、问题说明、严重级别、受影响的 ChartSpec 路径和建议动作。系统 SHALL 区分可修复语义问题、源绑定问题、运行时重试问题和不可恢复的 retry exhausted。

#### Scenario: Review reports a semantic mismatch

- **WHEN** 候选图与源图在数据、方向、标签或布局上不一致
- **THEN** 审核结果包含可供主 Agent 修正的结构化 diagnostics
- **AND** 审核阶段不调用 OCR、CV 或图表测量工具

### Requirement: Review retries are bounded and candidate-aware

系统 SHALL 对审核调用和候选修复设置有限次数。语义失败需要新候选才能重审；相同候选不得无限重复审核，且审核通过前不得发布。

#### Scenario: Review recovery reaches its limit

- **WHEN** 候选修复或审核重试达到上限
- **THEN** 系统保留候选和诊断并返回非发布的 retry_exhausted 状态

### Requirement: Generated chart review is a hard gate for publication and completion

生成图候选的结构检查和适用的 VLM 审核 SHALL 共同构成发布前的主链路门禁。候选处于审核中、需要修复或审核失败时，不得发布、不得作为成功生成结果返回，也不得由主 Agent 最终文本覆盖。

#### Scenario: Candidate remains blocked while review is pending
- **WHEN** 候选图已经渲染但审核结果尚未应用
- **THEN** 候选保持不可发布状态
- **AND** 主链路不得进入发布或成功终结阶段

#### Scenario: Failed candidate enters a controlled repair loop
- **WHEN** 审核返回可修复的语义、布局或映射问题
- **THEN** 系统只向主 Agent 提供有界诊断和修正 ChartSpec 的动作
- **AND** 修正后必须生成新的 candidate 并重新审核，旧 candidate 保持不可发布

#### Scenario: Passed candidate releases publication
- **WHEN** 候选通过全部必需审核，或策略允许带 warning 的决定
- **THEN** 系统原子地释放发布门禁
- **AND** 生成结果携带准确的审核和 warning 状态

#### Scenario: Review failure never becomes a successful run
- **WHEN** VLM 输出非法、审核超时、源证据不可用或修复次数耗尽
- **THEN** 候选进入非发布终态并保留失败诊断
- **AND** run 不能以已发布或审核通过的成功结论结束
