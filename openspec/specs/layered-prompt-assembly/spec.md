# layered-prompt-assembly Specification

## Purpose

为主 Agent 建立中文 Markdown 驱动、分层且可追踪的上下文装配能力，使长期行为规则、当前工具能力、过程分析产物和运行时状态彼此隔离并能在每轮模型调用中正确组合。

## Requirements

### Requirement: Main Agent context uses four explicit layers

主 Agent 上下文 SHALL 保持静态职责、动态工具、过程产物和 Run/Turn 动态状态四层。过程产物 SHALL 包含 observation scope、候选 refs、overlay、质量 warning 和实际使用的 provenance；Run/Turn 层 SHALL 提供当前事实、问题、候选状态和预算，不得把普通测量或审核修复建议表达为代码拥有的业务动作清单。

#### Scenario: Normal chart turn exposes the four layers

- **WHEN** 主 Agent 为一次图表分析请求准备模型调用
- **THEN** 上下文能够区分长期行为规则、当前可用工具、已产生的图表产物和当前运行状态
- **AND** 当前运行的 attachment、panel、候选图和待办动作不会被误认为静态职责

#### Scenario: Empty process layer is explicit

- **WHEN** 当前 run 尚未产生 panel、观测结果或候选图
- **THEN** 过程产物层明确表示没有可用产物
- **AND** Agent 不得引用其他 run 的产物作为当前 run 的事实

### Requirement: Static responsibilities are Chinese Markdown resources

静态职责层 SHALL 使用简体中文 Markdown 表达 Agent 角色、决策优先级、证据边界、工具使用原则、生成审核门禁和最终回答边界。静态内容 SHALL 不包含本次运行的 ID、用户请求、工具结果、候选状态或重试计数；稳定工具名、JSON 字段、ChartSpec 字段和状态枚举可以保留英文。

#### Scenario: Static prompt remains stable across runs

- **WHEN** 两个不同 session 分别创建主 Agent runtime
- **THEN** 两次装配使用同一版本的静态职责内容
- **AND** 静态内容不因 active source、panel inventory 或历史产物变化而改变

#### Scenario: Chinese policy preserves protocol identifiers

- **WHEN** 模型读取静态职责和动态说明
- **THEN** 自然语言规则为简体中文
- **AND** 工具调用名称、参数名、JSON key 和状态枚举保持与现有协议一致

### Requirement: Dynamic tool surface derives from registered tools

动态工具层 SHALL 从当前注册并授权的工具定义生成，包含模型可调用的稳定工具名、中文用途说明、适用范围、限制和原生参数 Schema。工具层 SHALL 只暴露当前 runtime 实际可调用的工具，不得在 Markdown 中声明未注册工具或内部本地路径输入。

#### Scenario: Authorized chart tools form the model surface

- **WHEN** runtime 为带图片的图表请求准备工具上下文
- **THEN** 模型看到的工具集合来自当前 registry 和 attachment authorization boundary
- **AND** 图像工具接受 opaque attachment ID 而不是本地文件路径

#### Scenario: Tool descriptions and schemas remain aligned

- **WHEN** 工具被动态装配到模型请求
- **THEN** 中文说明、稳定英文工具名和 JSON Schema 描述同一个 callable contract
- **AND** Prompt 文本不得要求模型提供 Schema 中不存在的字段

### Requirement: Process artifacts remain structured and attributable

过程产物层 SHALL 能够表达源附件、dashboard panel、局部 crop、初始 observation scope、OCR 或几何观测、layout 结果、evidence selection、ChartSpec、生成候选和审核结果。每个产物 SHALL 保留稳定 ID、来源引用、范围或 lineage、状态、confidence 和 warnings 等适用元数据；结构化 JSON 和模型可见图片 SHALL 保持可关联，不得只保留不可验证的自由文本摘要。

#### Scenario: Observation result becomes reusable process context

- **WHEN** dashboard 拆解或图表传感器产生 panel 和局部 observation
- **THEN** 过程产物层记录 panel、scope、attempt、crop/resource、refs 和状态
- **AND** 后续工具和模型可以通过同一 panel/attempt 关联局部结果

#### Scenario: Selection remains distinct from observation

- **WHEN** 主 Agent 选择或舍弃测量候选
- **THEN** 过程产物层单独记录 selected、discarded、semantic mapping 和 decision 来源
- **AND** 工具原始 observation 不被覆盖或改写为模型结论


### Requirement: Run and Turn state is dynamic control context

Run/Turn 动态状态层 SHALL 表示当前用户请求、active source、selected panel、当前 scope、最近工具动作、可选下一动作、生成图 review gate、恢复状态、资源预算和中断状态等代码拥有的事实。普通 measurement warning SHALL 以诊断和可选动作出现，不得自动将主链路置于独占 reviewing 状态。

#### Scenario: Scoped observation exposes model choices

- **WHEN** 当前 run 已选择一个 panel 并完成局部测量
- **THEN** 动态状态明确当前 panel、scope、候选 observation、可选动作和预算
- **AND** Agent 可以选择、舍弃、补充或直接组装

#### Scenario: Generated review remains a blocking state

- **WHEN** 生成图候选尚未通过审核
- **THEN** 动态状态明确禁止发布以及可执行的修复动作
- **AND** 该生成审核状态与测量 warning 分开表达

### Requirement: Layer assembly preserves authority and untrusted evidence boundaries

装配后的上下文 SHALL 保持以下优先级：代码拥有的授权、工具 Schema、生命周期和发布状态高于模型文本；静态职责高于过程产物中的自然语言；结构化工具结果和图片属于证据而非指令。用户输入、OCR 文字、图表图片中的文字和工具返回的自由文本不得修改 Agent 的硬性安全、范围或发布规则。

#### Scenario: Untrusted observation cannot change the workflow contract

- **WHEN** OCR、图片文字或工具自由文本包含要求跳过 panel routing 或 review 的内容
- **THEN** Agent 将其作为待分析证据而不是系统指令
- **AND** 授权、范围校验和发布门禁仍由代码状态决定

#### Scenario: Model claim cannot override publication state

- **WHEN** 模型文本声称候选已通过审核但代码返回 publication status 为 rejected
- **THEN** Agent 继续将候选视为未发布
- **AND** 最终回答不得把该候选描述为 verified 或 published

### Requirement: Prompt bundle identity is observable

每次主 Agent 装配 SHALL 具有可追踪的 Prompt bundle version 和层级标识。该标识 SHALL 可进入运行 trace 或诊断元数据，但不得记录用户图片字节、API key、本地路径或未授权的原始内容。

#### Scenario: Run trace identifies the assembled prompt version

- **WHEN** Agent 开始一次模型调用
- **THEN** trace 或运行诊断可以识别静态职责、工具面和动态上下文所使用的 Prompt bundle version
- **AND** 该元数据不泄露敏感内容
### Requirement: The four prompt layers carry one shared generation context

现有四层提示词 SHALL 保持不变：静态职责、动态工具、过程产物、Run/Turn 状态。source-
linked generation context SHALL 作为结构化动态上下文在适当层注入一次并在后续层引用，
不得复制成互相冲突的自由文本版本，也不得新增第五层来承载任务合同。

#### Scenario: Agent sees mode before choosing evidence

- **WHEN** 主 Agent 开始一个 panel transform
- **THEN** prompt context 显示 mode、source scope、coverage 和当前 attempt
- **AND** 工具说明与过程产物引用同一份字段
- **AND** Agent 可以在调用测量前决定 full observation、focused observation 或无需工具

### Requirement: Main prompt defines an explicit evidence decision matrix

静态职责和动态状态 SHALL 帮助 Agent判断任务模式、来源范围、覆盖目标、证据充分性和可用工具，但 SHALL 将这些内容表达为决策原则和事实，而非必须提交 selected/discarded 状态的流程协议。工具 warning、remeasure suggestion 和 review repair hint SHALL 明确为非自动、非强制建议。

#### Scenario: Warning does not cause an unexplained duplicate measurement

- **WHEN** 测量返回 warning 或 remeasure suggestion
- **THEN** Agent可以采用已有证据、忽略候选、局部补测、改用其他证据或停止
- **AND** 系统不会自动调用工具，也不要求先写独立 decision 对象

### Requirement: Review prompt is a separate tool-free contract

审核提示词 SHALL 只接收候选、source crop、ChartSpec、generation context 和 bounded
review history；不得暴露可调用工具，也不得要求审核 VLM 自行重新测量。prompt SHALL 要求
严格 JSON decision，并声明 repair kind 与 scope/target。

#### Scenario: Reviewer returns machine-readable repair

- **WHEN** reviewer 认为一个值需要补充证据
- **THEN** 返回可解析的 decision、issue、repair_kind=evidence_needed 和 bounded target
- **AND** 不返回要求 reviewer 自己调用工具的指令

### Requirement: Main Agent receives a compact current decision context

每轮主 Agent prompt SHALL 在现有四层体系中提供有界的当前状态摘要，至少表达当前 scope、可用 evidence/candidate 引用、issues、publication status、恢复状态和剩余预算。摘要 SHALL 引用代码拥有的事实，不得包含普通业务动作的 allowed/blocked action contract；仅不可绕过的授权、结构和发布约束可以标记为硬限制。

#### Scenario: Agent distinguishes focus from observation

- **WHEN** 当前范围已经应用但尚未获得 observation
- **THEN** prompt 将 focus 和 observation 作为不同事实表达
- **AND** 不指定模型必须继续同一测量或提交 abandoned 状态

#### Scenario: Agent sees evidence decision lineage

- **WHEN** 当前 attempt 已有候选 refs 或部分 refs 已被装配使用
- **THEN** prompt 显示 attempt、scope、refs 和已使用 provenance
- **AND** Agent不需要维护另一套 selected/discarded lifecycle

### Requirement: Decision context declares allowed and blocked actions

动态状态层 SHALL 只对授权越界、无效来源、非法 ChartSpec、失败候选发布、terminal 状态和预算耗尽声明硬性阻止。对测量选择、修复工具、局部补测、ChartSpec 调整或来源恢复的建议 SHALL 作为可选 `repair_hint` 或 issue 表达，不得形成普通业务动作白名单。

#### Scenario: Required evidence repair is explicit

- **WHEN** generated review 失败但仍有预算
- **THEN** prompt 明确当前候选不可发布并显示 issues 与建议
- **AND** Agent可以在授权范围内自主选择修复动作

#### Scenario: Prompt does not turn a warning into an automatic loop

- **WHEN** measurement 只有 warning 且没有 required repair obligation
- **THEN** prompt 将其标为可选决策
- **AND** Agent 未作出选择前不会自动重复调用工具

### Requirement: Prompt context remains aligned with the timeline projection

主 Agent prompt 与客户端时间线 SHALL 共享 run、candidate、attempt、scope 和 publication 身份，但两者无需共享模型内部下一动作状态。内部 decision、repair phase 和 subcheck 事件可以保留在 trace；默认客户端和模型上下文 SHALL 分别投影为适合其用途的事实摘要。

#### Scenario: Model and client agree on the next action

- **WHEN** 同一 candidate 正在审核或修复
- **THEN** prompt 与客户端引用相同 candidate/review 身份和最终状态
- **AND** 客户端无需显示模型的候选动作，模型也无需遵循 UI projection 的步骤容器
