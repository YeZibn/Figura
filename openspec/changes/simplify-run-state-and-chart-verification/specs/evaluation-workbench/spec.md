## REMOVED Requirements

### Requirement: Evaluation uses the runtime compatibility projection

**Reason**: 评测仅读取当前支持的已提交执行事实，不保留旧 lifecycle 格式的解释或迁移。
**Migration**: 使用当前执行事件投影；不支持的协议明确返回不可用状态。

### Requirement: Evaluation cases use the shared decision timeline projector

**Reason**: 统一投影直接呈现工具、验证和 artifact 的已提交事实，不维护独立的审核或发布决策周期。
**Migration**: 使用共享的 committed-fact timeline projector。

## ADDED Requirements

### Requirement: Evaluation uses the supported execution projection

评测工作台 SHALL 对当前支持的执行事件使用与普通运行相同的分组、错误字段和去重规则。评测报告可以增加 case 上下文，但不得把同一事件重新解释成另一套顶层时间线；不支持的协议或字段形状 SHALL 显示明确不可用状态，不读取旧 lifecycle 格式或合成缺失事实。

#### Scenario: Unsupported history is explicit

- **WHEN** case history 使用当前投影不支持的事件协议或字段形状
- **THEN** 工作台保留 case 与运行摘要并标注时间线不可用/不支持
- **AND** 不从旧 lifecycle 字段或评测阶段推断状态

### Requirement: Evaluation cases use the shared committed-fact timeline projector

评测工作台 SHALL 使用与普通运行相同的 canonical 用户时间线投影、unit、phase、transition 去重、工具 call/result 关联及已提交验证和 artifact 事实。评测批次可以增加 case、expected result、报告上下文及只读阶段诊断，但 SHALL NOT 再解释或修正测量、验证或发布状态。时间线 SHALL 按事件类型读取其唯一规定的状态字段。

#### Scenario: Evaluation transcript matches an ordinary run

- **WHEN** 普通运行和评测 case 指向同一份受支持的 execution history
- **THEN** 两者显示相同的测量、工具、assembly、verification 和 artifact publication 时间线步骤
- **AND** 评测专有的阶段诊断不会新增、删除或改写时间线业务状态

#### Scenario: Evaluation remains read-only

- **WHEN** 用户展开或刷新 case timeline
- **THEN** 客户端只读取已保存的 timeline inputs 和安全资源
- **AND** 不重新执行测量、装配、VLM verification 或发布

## MODIFIED Requirements

### Requirement: User can inspect an evaluation and its cases

The Gateway SHALL expose read-only detail resources for a selected evaluation and case. Case history SHALL return the same safe current run-event envelope as an ordinary session run, including lifecycle events, tool calls, tool results, visual observations, verification and artifact facts, failures, and recovery events. Events SHALL preserve sequence, timestamp, status, and `call_id` when available, with evaluation-scoped resource references and no database or local paths.

#### Scenario: Case history uses the shared event contract

- **WHEN** the client requests ordered history for a case with a persisted run
- **THEN** it receives the same supported event semantics as ordinary run history
- **AND** the response contains no database or local filesystem path

### Requirement: User can expand bounded read-only run details

The evaluation workspace SHALL display sanitized conversation messages, tool calls and results, measurement evidence details, committed verification results and issues, published artifact references, lifecycle events, errors, recovery state, and evaluation-scoped visual evidence. It SHALL preserve full persisted safe values within configured transport limits and clearly identify truncation or unavailable detail.

#### Scenario: User expands a verification result

- **WHEN** an evaluation case contains a committed chart verification event
- **THEN** the client displays its bounded checks, issues, and associated staged reference
- **AND** it does not rerun verification

### Requirement: Evaluation run transcript matches ordinary session trace

The evaluation workspace SHALL use the ordinary session timeline's call/result correlation, visual-observation behavior, domain labels, terminal/error presentation, and technical-event filtering. Model-start, model-completion, and internal commit-confirmation events SHALL remain available in history but SHALL NOT become separate visible rows.

#### Scenario: User inspects a selected case

- **WHEN** the user opens a case with a persisted run
- **THEN** tool calls, tool results, observations, verification results, artifact publications, and terminal events appear in their meaningful order

### Requirement: Evaluation tool steps use the shared default-collapsed presentation

The evaluation workbench SHALL use the ordinary timeline's canonical tool names, localized status semantics, and collapsed details. It MUST NOT infer tool completion, verification pass, or chart publication from an unknown tool result status.

#### Scenario: Evaluation tool details are opt-in

- **WHEN** a persisted evaluation run contains a tool call and result
- **THEN** the timeline initially shows one collapsed tool step
- **AND** expanding it reveals available bounded arguments, result, and visual evidence without rerunning the tool

### Requirement: Evaluation timeline preserves unresolved and blocked decisions

评测 case SHALL 保留真实的 pending、failed、blocked、partial 和 not_reached 运行、verification 及 artifact 状态，并显示当前运行单元的原因和必要的后续信息。measurement scope 与 observation 属于同一次工具调用；不得把它们之间不存在的间隔显示为 pending/abandoned measurement decision。未发布的暂存图不得标记为完整成功。

#### Scenario: Scoped measurement result is atomic

- **WHEN** case 在局部测量 tool call 执行期间中断，或工具返回失败/不充分结果
- **THEN** 评测时间线显示真实的工具执行状态及 interruption/结果原因
- **AND** 不构造等待 follow-up observation 的 measurement unit

#### Scenario: Failed verification remains inspectable

- **WHEN** 一张暂存图验证失败
- **THEN** case 显示失败验证、来源范围、issues 和预览可用状态
- **AND** 不显示正式 artifact 或推断修复预算终态
- **AND** 报告保留已经产生的证据和失败诊断

### Requirement: Evaluation expands the same safe evidence details

评测工作台 SHALL 使用与普通运行相同的工具 call/result、实际 assembly 输入、verification check 和 visual resource 关联规则。展开详情时 SHALL 保留 bounded structured values、sequence 和安全资源引用，不得通过本地路径或原始数据库补全内容；measurement evidence 使用情况不得表现为单独的 decision record。

#### Scenario: User inspects measurement and verification evidence

- **WHEN** 用户展开一个评测 case 的测量、assembly 或 verification 工具步骤
- **THEN** UI 显示工具输出、实际使用 refs、质量信息或验证 checks
- **AND** 不显示额外 evidence-decision 步骤
