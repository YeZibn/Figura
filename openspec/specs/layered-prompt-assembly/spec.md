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

过程产物层 SHALL 能够表达源附件、dashboard panel、局部 crop、measurement tool 的 observation scope、OCR 或几何观测、layout 结果、候选 measurement evidence、ChartSpec、生成候选和审核结果。每个产物 SHALL 保留稳定 ID、来源引用、范围或必要 lineage、质量/状态及适用的 confidence 和 warnings；模型对候选是否采用不作为独立过程产物保存。结构化 JSON 和模型可见图片 SHALL 保持可关联，不得只保留不可验证的自由文本摘要。

#### Scenario: Observation result becomes reusable process context

- **WHEN** dashboard 拆解或图表传感器产生 panel 和局部 observation
- **THEN** 过程产物层记录 panel、scope、attempt、crop/resource、refs 和质量状态
- **AND** 后续工具和模型可以通过同一 panel/attempt 关联局部结果

#### Scenario: Evidence use is represented by the actual assembly input

- **WHEN** 主 Agent 在 ChartSpec assembly 中引用部分测量候选
- **THEN** 过程产物层保留 measurement observation 和实际 assembly refs
- **AND** 不单独记录 selected、discarded 或 semantic-decision 生命周期

### Requirement: Layer assembly preserves authority and untrusted evidence boundaries

装配后的上下文 SHALL 保持以下优先级：代码拥有的授权、工具 Schema、生命周期和发布状态高于模型文本；静态职责高于过程产物中的自然语言；结构化工具结果和图片属于证据而非指令。用户输入、OCR 文字、图表图片中的文字和工具返回的自由文本不得修改 Agent 的硬性安全、范围或发布规则。

#### Scenario: Untrusted observation cannot change the workflow contract

- **WHEN** OCR、图片文字或工具自由文本包含要求跳过 panel routing 或 review 的内容
- **THEN** Agent 将其作为待分析证据而不是系统指令
- **AND** 授权、范围校验和发布门禁仍由代码状态决定

#### Scenario: Model claim cannot override committed publication facts

- **WHEN** 模型文本声称图表已发布但没有对应的已提交 artifact 引用
- **THEN** 最终回答 guard 删除或更正该发布声明
- **AND** Agent 不得把暂存预览描述为正式 artifact

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

### Requirement: Runtime prompt exposes committed facts without shadow lifecycle state

Run/Turn 状态层 SHALL 提供当前请求、授权来源、selected panel、measurement evidence、最近工具动作、可选下一动作、已提交的 staged chart、verification 与正式 artifact 事实、派生恢复资格、预算和中断状态。它 MUST NOT 提供平行的领域生命周期状态、独立执行门禁、固定修复阶段或完整上下文快照。measurement warning 和验证 repair hint SHALL 是可选诊断，不得自动调度工具。

#### Scenario: Unfinished verification is described from committed facts

- **WHEN** Run 有已暂存但尚未验证的图像
- **THEN** 主 Agent 上下文显示其暂存身份及当前验证事实
- **AND** 不声称图像已通过或已发布，也不维护额外 gate 状态

#### Scenario: Measurement warning remains model selected

- **WHEN** measurement observation 带有 warning 或补测建议
- **THEN** prompt 将其作为有范围的证据和可选诊断
- **AND** 在 Agent 选择前系统不会自动重复调用工具

### Requirement: Semantic verification prompt keeps a bounded tool-free contract

语义验证提示 SHALL 接收暂存图、准确 ChartSpec、授权来源范围及 generation context，不得暴露工具调用。它 SHALL 使用 generated-chart-verification 定义的严格 JSON 结论和有界 issues；repair hint 仅描述诊断，不得要求验证模型选择或执行后续工具。

#### Scenario: Verifier identifies a repair hint without scheduling work

- **WHEN** VLM 找到可修复的标签或数据映射问题
- **THEN** 返回固定字段的验证结论和有界 issue
- **AND** 主 Agent 自主决定是否重测、修正 Spec、重新生成或停止

### Requirement: Prompt and timeline share stable committed references

主 Agent prompt 与客户端时间线 SHALL 使用相同的 run、staged、verification、artifact、collection child 和 source scope 引用。提示词 MAY 包含模型所需的证据说明，但不得引用客户端无法解析的第二套生命周期身份；客户端不得控制模型内部动作。

#### Scenario: Published result matches the visible timeline

- **WHEN** 图表已有已提交的正式 artifact
- **THEN** prompt 和时间线引用相同 artifact 身份与 warning 结果
- **AND** 时间线刷新不会触发验证或发布
