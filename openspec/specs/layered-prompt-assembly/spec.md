# layered-prompt-assembly Specification

## Purpose

为主 Agent 建立中文 Markdown 驱动、分层且可追踪的上下文装配能力，使长期行为规则、当前工具能力、过程分析产物和运行时状态彼此隔离并能在每轮模型调用中正确组合。

## Requirements

### Requirement: Main Agent context uses four explicit layers

主 Agent 的模型上下文 SHALL 明确区分四类信息：静态职责、动态工具、过程产物和 Run/Turn 动态状态。过程产物层 SHALL 包含 observation scope、候选 refs、overlay、质量 warning 和 selected/discarded 决策；Run/Turn 层 SHALL 表示当前可执行动作，而不得把普通测量 warning 自动写成强制 repair 状态。

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

静态职责和动态状态 SHALL 要求 Agent 依次判断：任务模式、来源范围、需要代表的系列、
证据是否足够、是否需要同范围补测，以及是否可以 assemble/render。提示词 SHALL 明确
工具 warning/remeasure suggestion 不是自动动作；Agent 必须显式选择 selected、discarded
或 request evidence repair。

#### Scenario: Warning does not cause an unexplained duplicate measurement

- **WHEN** 一次测量返回 warning 或 remeasure suggestion
- **THEN** Agent 可以选择接受、舍弃、局部补测或向用户澄清
- **AND** 未产生显式决策前不会自动再调用测量工具

### Requirement: Review prompt is a separate tool-free contract

审核提示词 SHALL 只接收候选、source crop、ChartSpec、generation context 和 bounded
review history；不得暴露可调用工具，也不得要求审核 VLM 自行重新测量。prompt SHALL 要求
严格 JSON decision，并声明 repair kind 与 scope/target。

#### Scenario: Reviewer returns machine-readable repair

- **WHEN** reviewer 认为一个值需要补充证据
- **THEN** 返回可解析的 decision、issue、repair_kind=evidence_needed 和 bounded target
- **AND** 不返回要求 reviewer 自己调用工具的指令

### Requirement: Main Agent receives a compact current decision context

每轮主 Agent prompt SHALL 在现有四层体系中提供一个有界的当前 decision context，至少表达 current unit、phase、status、scope、当前 evidence/candidate 引用、required next action 和剩余预算。该 context SHALL 引用已有结构化事实，不得复制一份会漂移的自然语言任务合同。

#### Scenario: Agent distinguishes focus from observation

- **WHEN** 当前 unit 已应用 focused scope 但尚未获得 observation
- **THEN** prompt 明确显示 pending observation 和允许的同 scope action
- **AND** 不把 focus applied 描述为已经获得可组装证据

#### Scenario: Agent sees evidence decision lineage

- **WHEN** 当前 attempt 已经有 selected/discarded refs
- **THEN** prompt 显示 decision status、attempt 和允许的后续 assemble/remeasure action
- **AND** Agent 不需要从多条重复事件中猜测当前状态

### Requirement: Decision context declares allowed and blocked actions

动态状态层 SHALL 明确列出当前允许、需要显式确认和被阻塞的动作。普通 warning 可以作为可选行动建议；required repair、scope violation、review gate 和 publication status SHALL 作为代码拥有的约束呈现。

#### Scenario: Required evidence repair is explicit

- **WHEN** generated review 要求同一 panel 的 evidence repair
- **THEN** prompt 显示 same-scope measurement 为允许或必需动作，并阻止跨 panel、直接 assemble 或 publication
- **AND** Agent 可以显式选择完成、放弃或进入 terminal recovery

#### Scenario: Prompt does not turn a warning into an automatic loop

- **WHEN** measurement 只有 warning 且没有 required repair obligation
- **THEN** prompt 将其标为可选决策
- **AND** Agent 未作出选择前不会自动重复调用工具

### Requirement: Prompt context remains aligned with the timeline projection

主 Agent prompt 使用的 decision context 与客户端 timeline 使用相同的 unit、phase、attempt 和 status 标识。提示词 SHALL 不把 review snapshot 或原始工具结果快照当成新的决策转换。

#### Scenario: Model and client agree on the next action

- **WHEN** timeline 显示当前 unit 等待证据选择
- **THEN** prompt 显示相同的 pending unit 和 allowed decision actions
- **AND** 模型输出的后续工具调用可以通过同一 transition 关联回 timeline
