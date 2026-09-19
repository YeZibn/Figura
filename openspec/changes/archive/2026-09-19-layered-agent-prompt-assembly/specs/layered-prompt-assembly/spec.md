## Purpose

为主 Agent 建立中文 Markdown 驱动、分层且可追踪的上下文装配能力，使长期行为规则、当前工具能力、过程分析产物和运行时状态彼此隔离并能在每轮模型调用中正确组合。

## ADDED Requirements

### Requirement: Main Agent context uses four explicit layers

主 Agent 的模型上下文 SHALL 明确区分四类信息：静态职责、动态工具、过程产物和 Run/Turn 动态状态。每一类 SHALL 有稳定的来源标记和边界；缺失的动态层 SHALL 显式表示为空，不得用历史文本或模型推断伪造当前状态。

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

过程产物层 SHALL 能够表达源附件、dashboard panel、局部 crop、OCR 或几何观测、layout 结果、ChartSpec、生成候选和审核结果。每个产物 SHALL 保留稳定 ID、来源引用、范围或 lineage、状态、confidence 和 warnings 等适用元数据；结构化 JSON 和模型可见图片 SHALL 保持可关联，不得只保留不可验证的自由文本摘要。

#### Scenario: Decomposition result becomes reusable process context

- **WHEN** dashboard 拆解产生 accepted panel 和局部预览
- **THEN** 过程产物层记录 panel ID、源 attachment、scope、crop/resource 引用和状态
- **AND** 后续工具和模型可以通过同一 panel ID 关联局部结果

#### Scenario: Generated candidate remains distinct from source evidence

- **WHEN** render_chart 产生候选图并进入自动审核
- **THEN** 候选图、ChartSpec、review 结果和 publication status 保持独立且可关联
- **AND** 候选 preview 不会被过程产物摘要描述为已发布 artifact

### Requirement: Run and Turn state is dynamic control context

Run/Turn 动态状态层 SHALL 表示当前用户请求、active source、selected panel、执行阶段、最近工具动作、待办动作、review gate、恢复状态、重试预算和中断状态等代码拥有的事实。状态变化后，下一次模型调用 SHALL 获得更新后的状态；模型自由文本不得覆盖这些状态。

#### Scenario: Scoped observation exposes the next action

- **WHEN** 当前 run 已选择一个 panel 并完成局部测量
- **THEN** 动态状态明确当前阶段、selected panel 和下一步可执行动作
- **AND** Agent 不会因为缺少旧对话文本而回到完整 dashboard 拆解

#### Scenario: Review recovery exposes bounded action

- **WHEN** 候选审核失败且仍有修复预算
- **THEN** 动态状态包含候选引用、审核分类、有限诊断和下一步修复动作
- **AND** 状态明确禁止发布失败候选

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
