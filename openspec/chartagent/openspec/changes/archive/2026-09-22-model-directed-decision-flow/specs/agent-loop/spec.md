## MODIFIED Requirements

### Requirement: Recoverable review failures return to the main Agent

当生成候选的审核失败且仍有重试预算时，Agent loop SHALL 将结构化审核诊断、候选身份、来源范围和剩余预算返回主 Agent。主 Agent SHALL 能够根据问题自主选择修正 ChartSpec、补充观察、局部测量、恢复来源绑定或停止；系统 SHALL NOT 仅因 `repair_kind` 将后续工具调用限定为一条固定阶段链。任何修复产生的新候选仍 SHALL 重新审核。

#### Scenario: Semantic failure triggers a model-selected correction

- **WHEN** VLM review 拒绝候选并返回具体语义问题
- **THEN** 主 Agent 收到问题、候选身份、来源范围和剩余预算
- **AND** 主 Agent 可以选择适用的授权工具或直接修正 ChartSpec
- **AND** 新候选重新进入生成审核

#### Scenario: Repair hint does not become a tool whitelist

- **WHEN** 审核将问题分类为 `spec_only`、`evidence_needed` 或 `source_rebind`
- **THEN** 该分类作为诊断和修复建议返回
- **AND** 系统不因该分类拒绝同一任务范围内其他合法工具调用

### Requirement: Agent keeps measurement evidence decisions bounded

Agent loop SHALL 将 measurement observation 的 scope、evidence refs、issues、overlay、attempt lineage 和实际被下游引用的 refs 作为有界上下文保存。多个 measurement session SHALL 保持来源、面板和 attempt 边界；系统 SHALL NOT 要求主 Agent先创建独立 selected/discarded/abandoned decision unit 才能调用 `assemble_spec`。

#### Scenario: Observation returns evidence facts to the model

- **WHEN** 测量工具返回候选、warning 或局部结果
- **THEN** Agent 将结构化问题、refs、overlay、scope 和非强制建议交给模型
- **AND** 上下文不包含替模型规定普通业务动作的 allowed/blocked action contract

#### Scenario: Multiple measurements retain independent evidence contexts

- **WHEN** 同一个 assistant 工具批次中的多个测量结果分别绑定不同 panel 或 session
- **THEN** Agent 保留每个 session 的 attachment、panel、attempt、父 attempt 和证据引用
- **AND** 任一 session 都不会因另一个结果后到达而被覆盖

#### Scenario: Used evidence is derived from the assembly request

- **WHEN** 主 Agent 在 `assemble_spec` 中引用当前 attempt 的部分 refs
- **THEN** 系统将这些 refs 记录为本次装配实际使用的 provenance
- **AND** 未引用候选无需逐项生成 discarded decision

### Requirement: Main-chain measurement decisions are model-led

主 Agent SHALL 在同一主链路中消费测量工具结果并自主决定使用哪些候选、忽略哪些误检、映射语义、请求局部补充或改用直接视觉理解。系统 SHALL 通过工具输入和实际 evidence refs 记录可追踪事实，不得要求模型维护额外的 measurement decision 状态机，也不得通过独立测量审核器替模型作出语义选择。

#### Scenario: Main Agent uses a candidate subset

- **WHEN** 测量工具返回的部分候选足以支持目标图表
- **THEN** 主 Agent可以只把实际使用的 refs 传给 `assemble_spec`
- **AND** 系统验证这些 refs 后继续，不要求提交 discarded refs

#### Scenario: Main Agent requests an initial scoped observation

- **WHEN** 主 Agent 能够判断 plot 或 legend 的大致范围
- **THEN** 主 Agent 可以提交 `observation_scope`
- **AND** 该调用不要求父 attempt 或预先登记的 decision

#### Scenario: Main Agent requests focused evidence

- **WHEN** 主 Agent判断某个候选、系列、基准线或区域仍不确定
- **THEN** 主 Agent可以调用对应测量工具并提供 `measurement_target`
- **AND** 该调用创建有父级关系的新 attempt，但不锁定后续修复工具顺序

#### Scenario: Main Agent ignores a false candidate

- **WHEN** 主 Agent判断某个候选是图例、文字或其他误检
- **THEN** 主 Agent可以不在装配输入中引用该候选
- **AND** 系统不要求单独提交舍弃状态，也不自动重测整个 panel

## ADDED Requirements

### Requirement: Assembly validates actual evidence use without a separate decision envelope

主循环 SHALL 允许 `assemble_spec` 通过 `measurement_ref + evidence_refs` 直接接收模型实际采用的 measurement refs，或接收不带 measurement provenance 的合法视觉输入。系统 SHALL 对被引用证据执行 session、attachment、panel、attempt、范围、引用和必要结构校验；只有非法引用或无效 ChartSpec 可以阻止当前组装，缺少独立 `measurement_decision` 不得成为阻断原因。

#### Scenario: Referenced evidence is valid

- **WHEN** 主 Agent提交属于当前来源和 attempt 的合法 evidence refs
- **THEN** 组装继续并保存实际使用的 provenance
- **AND** 同一 observation 中未引用的候选不会阻塞组装

#### Scenario: Referenced evidence is invalid

- **WHEN** 主 Agent提交不存在、越界、跨来源或结构不完整的 ref
- **THEN** 系统返回定位到该 ref 的结构化错误
- **AND** 不自动重测、不渲染、不发布依赖该引用的结果

#### Scenario: Direct visual assembly remains available

- **WHEN** 主 Agent不引用测量结果而提交合法 ChartSpec
- **THEN** 系统执行通常的结构校验和生成审核
- **AND** 当前 run 中未使用的 measurement observation 不会强制要求 abandoned decision

## REMOVED Requirements

### Requirement: Assembly is blocked until the main-chain evidence decision is explicit

**Reason**: 独立 selected/discarded/abandoned decision envelope 把证据选择变成了组装前状态机，重复表达模型在装配输入中已经作出的选择，并造成无意义阻塞。

**Migration**: 新请求直接携带实际使用的 evidence refs；旧 decision 字段和历史事件继续兼容读取，但不再是组装前置条件。
