# Figura 系统总览

> 更新日期：2026-10-19。范围：新 Figura 的当前工作树 `src/figura/`。代码、主规格、归档记录、活动 change、目标设计和旧 `chartagent` 分别标记。本文是入口；组件内部流程与完整字段见按领域划分的专题文档。

## 1. 一眼看懂 Figura

Figura 接收用户文本和图像，创建可恢复的 Run，让 Agent 调用模型与工具。一个 Session 中后续 Run 从持久事实重建规范历史；每次普通请求都另行携带此前所有 Run 的完整用户输入、附件 ID 和来源引用，压缩游标不会删减这一部分，当前 Run 输入仍作为原生用户消息发送。选定 Provider 容量有效且本地估算达到阈值时，模型请求可使用带来源引用的历史摘要和近期原始过程尾部；可压缩范围包括符合连续条件的先前已完成 Run，以及当前 Run 已提交的完整交互。当前用户输入始终保留为原生消息，原始过程段前会标记其对应 Run 与输入引用。近期原始过程与滚动摘要目标分别约为容量的 10%，历史用户输入、指令、工具及当前 Run 内容都另计入完整请求估算。摘要不会替代或删除原事实。模型也可通过历史工具按引用搜索、读取旧消息、工具结果、资源元数据，或显式加载历史图像。

**当前工作树已实现**内部 ReAct、跨 Run 对话投影、上下文压缩与历史检索、图像加载与 Panel 分割、独立 OCR、十类图表的统一测量工具、ChartSpec/ChartFigure v2、Figure 组装与 PNG 渲染，以及统一 Provider 流式请求。模型文本可按 attempt 临时回传到网页；只有完整终止流经校验后，响应、continuation、工具调用批次和 checkpoint 才提交。测量结果采用 schema v3，保持为有来源依据的候选观察。网页已支持协作停止、工具时间线、整会话删除、临时回答文本、成功生成图的大图查看和 PNG 下载。测量回归脚本可在离线条件下通过真实 RapidOCR 和生产授权测量路径评估固定样例；它不调用 Provider，也不代表端到端 Agent 成功率或开放域准确率。

普通模型请求由 Agent 组装稳定规则、当前工具目录、可选历史摘要、资源/异常状态索引，以及本轮实际需要的历史与图像消息。四份基础规则之后加入 `image_feedback.md`：原图、OCR/测量标注图和生成图各自带有与资源引用相邻的简短观察提醒，历史图像显式重载时按资源类型复用同一规则。这些提醒进入下一次普通推理，主 Agent 自主决定后续动作；不会额外发起模型请求，也不创建审核状态或门控。对应 change [add-figura-image-feedback-guidance](../openspec/figura/openspec/changes/archive/2026-10-08-add-figura-image-feedback-guidance/proposal.md) 已归档，主规格已同步；本地验证确认观察提示与图像引用一同进入请求，但真实 Provider 行为尚无有效探测结论。摘要请求独立读取 `compaction.md`。

Agent 将目标 Run 已提交前缀、较早终态 Run 事实和 Sources 元数据重建为调用期 `RunExecutionState` 完整资源目录；提示只投影近期历史、摘要来源或当前动作相关的定位信息，其他内容可通过历史工具读取。目录不持久化，完整工具输入/结果仍来自 Runtime 通用工具事实，图像文件由 Sources 管理。Token 估算仅提供占比并触发可选压缩，不是请求准入或 Run 输出预算。通用证据生命周期、正式生成图验证、发布与端到端 Agent 评测仍未实现。仓库中的 `src/chartagent/` 是旧系统，不作为新 Figura 实现依据。详细职责见 [Agent 专题](figura/agent.md#提示分层与代码职责)。

当前新生成的历史摘要采用字段化分层合同，将目标、约束、决定、事实、进度状态、问题、资源和未接受提议分别保存；每项保留授权来源引用。压缩只跨越完整交互边界，覆盖可落在最近已完成 Run 的中间，也可进入目标活动 Run 的冻结已提交前缀。活动 Run 只有在下一动作是模型请求或 Provider 重试、且没有已启动的 Provider attempt 时才参与；未提交记录、未完成工具批次和未解决动作留在原文。Runtime operation 冻结目标 Run 的记录/工具前缀、容量、预算与覆盖游标，以供恢复时精确重建。每次摘要请求的 Markdown 指令会写入当次容量和约 `floor(C/10)` 的摘要长度参考目标；它是软目标，不限制输出或要求填满。每个所选 Run 的原始输入另与新覆盖过程分开提供；普通请求的完整历史输入区从权威 Run 事实重建，不增加数据库字段。

```mermaid
flowchart LR
    UI[Web: React 界面] -->|FiguraClient / Workspace API| Gateway[Web: 本地 Gateway]
    Gateway -->|Session、Run 查询、创建、停止请求与整会话删除| Runtime[Runtime]
    Gateway -->|附件/Panel 操作与 ChartFigure PNG 内容读取| Sources
    Sources -->|附件与 Panel 元数据| DB[(Figura SQLite / storage)]
    Sources -->|私有附件、独立 Panel 与 ChartFigure PNG| Files[(私有图片文件)]
    Gateway --> Delete[Web: Session 删除协调]
    Delete -->|同一事务删除 Session 聚合| Runtime
    Delete -->|暂存 / 回滚恢复 / 提交清理| Sources
    Gateway -->|异步提交、启动恢复与周期补偿| Dispatcher[Run Dispatcher]
    Dispatcher -->|扫描持久 running Run| Runtime
    Dispatcher -->|execute(session_id, run_id)| Agent[Agent]
    Gateway -->|本地配置可用性| Provider[Provider Boundary]
    Runtime -->|RunState、请求绑定、重试到期时间、停止请求与私有续接| Agent
    Agent -->|读取较早的终态 RunState| Runtime
    Agent -->|当前 Run 与较早 Run 的事实| Memory[Memory]
    Runtime -->|Session 摘要检查点与压缩操作| Agent
    Memory -->|规范历史与异常终态投影| Agent
    Agent -->|模型选定的历史读取工具调用| Tools[Tools]
    Tools -->|search_history / read_history| Memory
    Tools -->|read_resource_image| Reader[RunExecutionImageReader]
    Runtime -->|Run 输入与已提交工具事实| Catalog[Agent RunExecutionStateService]
    Sources -->|附件元数据与 Panel 记录| Catalog
    Catalog -->|完整 resources: Attachment / Panel / OCR / Measurement / ChartFigure / ChartRender| Agent
    Agent -->|最新工具批次中需回看的类型化图像引用| Reader
    Gateway -->|授权读取成功 OCR / 测量观察图| Reader
    Reader -->|授权读取 Attachment / Panel / ChartRender| Sources
    Reader -->|原图、观察标注图或 ChartRender PNG| Agent
    Reader -->|按需返回观察图 PNG| Gateway
    Agent -->|稳定规则、工具目录、可选摘要与资源索引 + 当前历史/所需图像及其观察提示| Provider[Provider]
    Provider -->|规范流事件；终止后给出完整 ProviderResponse| Agent
    Agent -->|普通请求 text_delta：临时 assistant_delta| Gateway
    Agent -->|图像 / OCR / 测量 / assemble / render 工具调用| Tools
    Tools -->|ChartSpec / ChartFigure 校验与绘图| Chart[Charts]
    Chart -->|校验结果与 PNG 字节| Tools
    Tools -->|读取来源或保存渲染 PNG| Sources
    Tools -->|ToolExecutionResult| Agent
    Agent -->|执行事实、Attempt、终态| Runtime
    Runtime -->|Session、Run 事实与事件| DB
    Runtime -->|安全 Session / Run / Event 投影| Gateway
    Catalog -->|仅构造安全渲染摘要| Gateway
    Gateway -->|受授权渲染内容读取| Sources
    Gateway -->|JSON / SSE / 授权 PNG 预览与下载| UI
```

图中的完整资源目录是 Agent 从已提交事实重建的调用期投影，不是 Runtime 的持久字段或额外结果存储。模型请求可只投影近期与摘要来源相关的资源定位信息；服务端仍保留授权前缀内的完整目录，Agent 可通过历史工具继续查找。OCR/测量/组装/渲染完整结果仍由通用 ToolResultFact 保留，ChartFigure 完整值从其成功调用事实恢复，渲染 PNG 保存在 Sources。来源引用定位规范事实，不复制事实权威。Web 的工具时间线也只从已提交工具事实生成摘要与详情；`run_progress` 事件用于提示前端重新读取，不承载工具结果。各 change 的当前状态见[第 5 节](#5-阅读与状态规则)；领域合同见 Agent、Runtime、Memory、Tools、Sources 与 Web 专题。

## 2. 大组件与下钻入口

| 组件 | 职责与跨组件交付 | 当前状态 | 内部文档 |
|---|---|---|---|
| Runtime | Session、Run、执行事实、Provider 请求与 attempt、Checkpoint、上下文摘要检查点与压缩操作、生命周期与进度事件；交付可恢复 `RunState` 和同 Session 较早 Run 的一致快照；每 Session 至多有一个 running Run | 当前工作树已实现；schema v13；按逻辑请求持久化四阶段尝试、退避与恢复；压缩操作引用共享 Provider request/attempt 合同；另有单动作执行所有权、停止请求、受控 Session 删除与安全终态说明 | [Runtime](figura/runtime.md) |
| Sources | 管理 Session 附件与 Panel 元数据、私有附件/Panel 图像和 ChartFigure PNG 文件、图像验证/处理和授权读取；与 Runtime 共用一份 SQLite | 已实现；渲染 PNG 只存私有文件，无独立元数据表；整会话删除含文件暂存、恢复与启动对账 | [Sources](figura/sources.md) |
| Agent | 按 checkpoint 组装请求、协调模型与工具；从 Run 事实和 Sources 元数据重建类型化资源目录 | 当前工作树已实现 ReAct、完整交互压缩、历史检索、图像类型观察提示和流式 Provider 调用；DeepSeek 摘要单独使用 medium thinking；完整响应才进入 Runtime 提交，压缩走共享 Provider request/attempt 重试合同 | [Agent 编排与资源目录](figura/agent.md) |
| Memory | 从同 Session 的 Run 事实构建规范历史、异常终态与来源引用；提供只读搜索、完整内容读取和资源元数据定位 | 当前工作树实现来源可寻址历史检索；摘要检查点由 Runtime 持久化，Memory 不另存历史副本 | [Memory](figura/memory.md) |
| Provider | 选择固定 provider/model，声明流式能力，归一化流事件、完整响应和安全失败；估算实际输入、上下文容量和网络故障分类 | 已实现 Qwen、DeepSeek、MiMo 的流式请求；连接与发送阶段有界，响应阶段不设总生成超时；重试由共享 Agent/Runtime coordinator 按冻结请求合同执行 | [Provider](figura/provider.md) |
| Tools | 版本化定义、参数/结果校验及 handler；执行事实归 Runtime | 当前工作树 `figura-web-v10` 注册 9 个工具；统一 `measure_chart` 返回十类 schema v3 候选观察；仍绑定 v9 的活动 Run 会阻止 v10 启动 | [Tools](figura/tools.md) |
| Shared / Validation | 被多个能力复用的 JSON Schema 校验与图像大小限制 | 当前已实现；不拥有测量回归或评测结果 | [Validation](figura/validation.md) |
| Evaluation | 使用固定图片与可见目标，对生产授权测量路径做离线回归；另以固定合成历史检查压缩投影和来源取回；报告不进入在线 Run 或 Web API | 当前工作树已有测量回归与上下文对照脚本；结果分别限定于固定图表样例和小样本合成会话，不覆盖端到端 Agent 或开放域基准 | [Evaluation](figura/evaluation.md) |
| Storage | 一份 SQLite 的连接、事务和 schema 初始化；由 Runtime 与 Sources 共用 | 当前已实现 | [Runtime](figura/runtime.md)、[Sources](figura/sources.md) |
| Web | 本地 Gateway、Session/Run/Panel/ChartFigure 渲染内容与工具时间线只读 HTTP API、安全历史投影和 SSE；前端经 Figura client 复用工作区 UI | 当前工作树已实现协作停止、周期恢复调度、活动状态补读、会话删除与图片/工具时间线；另外以无 durable ID 的 SSE `assistant_delta` 展示当前 attempt 临时文本，重试/缺口时清空并以持久 Run 状态收敛 | [Web](figura/web.md) |
| Charts | `ChartSpecData` 单图值与 `ChartFigure` 多图画布值，严格解析、规范序列化、纯校验和 PNG 绘制 | 当前工作树已实现 v2 与十类图表；对应 change 已归档、10 份 delta 已同步主规格；代码仍处于未提交工作树 | [Charts](figura/charts.md) |

## 3. 跨组件内容流

1. **网页输入与身份**：React Figura UI 通过 `FiguraClient` 调用 loopback Gateway。Gateway 创建/列出 Session，并提供确认后的整会话删除；删除须无 running Run，在同一 SQLite 事务与 Sources 文件暂存流程中清除该 Session 内容。Gateway 委托 Sources 上传、读取和删除附件，或读取 Panel；Run 创建只提交文本、有序附件 ID、provider ID 与幂等键。Runtime 先处理幂等重放，再拒绝同 Session 的第二个 running Run；成功时校验附件归属并保存输入、初始 checkpoint、Run 和创建事件。图片字节留在私有文件中。见[网页边界](figura/web.md)、[运行时](figura/runtime.md#2-内部流转)和[Sources](figura/sources.md#2-内部流转与不变量)。
2. **重建 Session 对话**：每次模型动作前，Agent 向 Runtime 读取目标 Run 之前的终态 RunState。Memory 从 Run 事实重建规范闭合历史与异常 outcome；若有有效摘要检查点，普通请求会以摘要替代精确覆盖游标之前的交互，并保留游标之后的原始交互，包括覆盖 Run 内较新的交互。规范历史及原事实始终可按来源引用读取。见[Session Memory](figura/memory.md#3-内部流转与失败边界)。
3. **估算、压缩与组装请求**：Provider 对完整准备请求作本地估算；容量有效且估算达到约 80% 时，Agent 按 `floor(C/10)` 分别设定 raw-history 预算与摘要软目标。选择器把符合连续条件的先前已完成 Run 过程和当前 Run 已提交的完整交互组成一条时间序列，按交互边界保留近期原文并摘要更早前缀。活动 Run 仅在下一动作属于 `MODEL` 或 `PROVIDER_RETRY` 且没有已启动的 Provider attempt 时纳入；其覆盖止于 Runtime 冻结的记录与工具序号，后续请求继续使用该检查点。当前输入保持原生用户消息，先前 Run 的输入、附件 ID 和来源引用完整单独投影；原文过程带输入定位引用。未提交记录、未完成工具批次、未解决动作以及无法安全跨越的异常历史留在原始上下文。摘要只接受带授权来源引用的字段化结果；dispatch 前按冻结容量预检，安装后重建并重新估算普通请求。两个 10% 数值只描述历史选择和摘要长度参考，不构成完整请求占用目标。细节见[Agent](figura/agent.md)、[Provider](figura/provider.md)、[Memory](figura/memory.md)和[Runtime](figura/runtime.md)。
4. **工具、渲染与恢复**：Tool Runtime 校验图像/Panel、OCR、统一十类测量、`assemble_chart_figure` 和 `render_chart_figure`。测量结果使用 schema v3；组装工具委托 Charts 严格解析 v2 内容与语义，并检查同 Session 目录中已提交成功的测量引用。渲染工具只接受已提交 Figure；Charts 的十类 renderer 生成 PNG，Sources 按 `(run_id, call_id)` 私下保存，Runtime 仍沿用通用工具事实持久化调用和结果。Agent 从成功配对事实重建 Figure 与渲染资源；同批次成功 PNG 随后加入下一次 Provider 请求，并带有渲染类型 Cue。OCR、测量标注和显式重载图片也按解析出的资源类型附带观察 Cue，身份引用与图像相邻；这些提示不表示正式审核。网页内容路由核对 Session、成功事实、摘要和文件。没有独立 Figure/渲染表。Panel 与渲染文件为幂等本地写，观察和 Figure 组装为 `replay_safe`。分别见[Tool 调用](figura/tools.md#2-内部流转)、[画布组装](figura/tools.md#7-图表画布组装工具)、[图表渲染](figura/tools.md#8-图表渲染工具)、[Charts](figura/charts.md)、[Sources](figura/sources.md)和[Agent 资源目录](figura/agent.md#4-runexecutionstate-资源合同与完整字段)。
5. **返回网页**：Gateway 从 Runtime 读取 Session snapshot、Run history 和安全事件，再投影 JSON/SSE。Run 工具时间线从当前 Run 的 ToolCall、Attempt 和 Result 事实生成；列表先返回有界摘要，详情与 OCR/测量观察图按需读取。持久 `run_progress` SSE 事件只通知前端刷新时间线，不携带工具 payload。Session-scoped Panel 与 ChartFigure 渲染路由只提供成功工具结果对应的 PNG；Run DTO 附加渲染摘要，React Gallery 按渲染所在 Run 懒加载所有成功预览，每张均可打开交互大图并通过同一授权内容路由下载 PNG。Conversation 不把 Agent 的完整 Session Memory、工具消息或 Provider continuation 暴露为普通对话。详见[网页端边界](figura/web.md)。
6. **图表链**：当前有 `ChartSpecData`、`ChartFigure`、纯 PNG renderer、Sources 私有 PNG 文件保存和网页预览；Figure 全文/摘要及渲染调用/结果分别借用 Run 工具调用/结果事实保留，Agent 可跨 Run 从统一资源目录索引成功画布与渲染内容。仍没有单独图表对象表、来源证据模型、生成图验证、发布或端到端 Agent Evaluation；已有的离线测量回归见 [Evaluation](figura/evaluation.md)。[规划能力](#4-规划能力与边界)标出这些未实现部分。

7. **停止、恢复与后续对话**：停止请求经 Gateway 写入 Runtime 独立控制事务；Agent 在执行 owner 保护下允许已开始动作提交真实结果，随后在边界 interrupted。Dispatcher 启动与周期扫描都从持久 checkpoint 推进。普通请求与摘要请求共享不可变逻辑请求记录、attempt ledger 和每请求最多四次发送；连接与发送阶段超时有界，Provider 流保持存活时不因总耗时单独取消。结果未知的请求不会重发同一 attempt；满足条件的纯生成请求仅在旧 owner 已退出、旧 attempt 已关闭时可按原 binding 创建替代 attempt。部分文本不会形成持久回答或工具事实。安全工具沿原调用身份有限恢复。后续 Run 保留闭合交互，将合法未完成末尾批次整体转换为异常上下文；成功资源仍可授权引用，未知调用不会被补造成结果。完整流程见 [Runtime](figura/runtime.md#停止所有权与恢复事务)、[Agent](figura/agent.md#异常-run-推进与后续请求)、[Memory](figura/memory.md#合法异常尾部投影) 和 [Web](figura/web.md#协作停止与客户端生命周期)。

执行策略在当前工作树中已统一：Run 没有累计模型轮次、工具次数、时间或 token 配额；每个逻辑 Provider 请求最多四个物理 attempt（首次加最多三次），只对已分类的临时失败自动重试，工具失败仍由模型决定后续动作。共享执行 JSON 单元默认 32 MiB，图片、事件、隐私、并发和领域保护各自保留。Token 估算不限制请求；只有容量已配置且估算达到约 80% 时才触发可选摘要。上下文估算、压缩和按需检索现已落入当前工作树，并有已归档 change 和同步主规格；无容量/估算失败时不自动压缩，摘要失败则保留完整历史请求路径。Provider 请求采用流式传输，但完整请求绑定仍校验 wire fingerprint；只要传输未明确失败，就不会因生成时间超过某个总时限而关闭。字段与边界见 [Provider](figura/provider.md)、[Runtime](figura/runtime.md#providerrequestrecord) 和 [Validation](figura/validation.md)。

## 4. 规划能力与边界

下表和虚线图中的虚线只说明[架构设计草案](figura-architecture-design.md)里尚未实现的目标。当前工作树有统一 `measure_chart` 与十类封闭 schema v3 观察、独立 OCR 文字观察、可选多边形范围与有条件的数值/几何结果；这些仍是工具候选观察，不等于通用证据域或完整图表事实。独立合同落地时，应先判断领域 owner，再在现有领域文档扩展或新增简短领域名的子文档。

| 目标能力 | 新 Figura 当前状态 | 需要明确的合同 |
|---|---|---|
| 图像文字与图表测量 | 当前工作树 Registry v10 注册 `extract_text` 和 `measure_chart`；统一入口接收十类 `chart_type`，结果使用封闭的 schema v3 family observations，并保存在通用 Run 工具事实中，由 Agent 索引为 `ocr`、`measurement`。历史 schema v2 测量事实保留原样，不转换为当前类型资源；相关主规格已同步 | 尚无通用 `EvidenceRef`、Agent 显式选证与证据生命周期；候选观察不会自动成为图表事实 |
| 离线测量回归 | 当前有固定合成样例、生成来源与可见目标、误差分类及真实 RapidOCR 回归；13 张图片、20 个图表实例、188 个目标本次全部通过，命令和指标范围见 [Evaluation](figura/evaluation.md) | 不代表端到端 Agent 完成率、任意真实图表准确率或外部基准成绩 |
| 独立图表对象与来源 | 当前 `ChartFigure` 完整 JSON 可随成功 assembly 工具事实跨 Run 保留；尚无独立 ChartFigure 表、修改版本或证据对象 | 是否增加可编辑图表实体、来源绑定和通用证据生命周期 |
| 生成图、验证与发布 | 当前工作树已有 ChartFigure→PNG 绘制、Sources 私有文件保存、Agent 图像回传观察提示及 Web 预览；提示引导模型自主回看，不产生审核结论。Chart rendering 与图像反馈主规格已同步、对应 change 已归档；尚无正式图表验证或发布服务 | 验证结果、ChartSpec/来源绑定、幂等发布身份 |
| 端到端与开放域 Evaluation | 尚无基于真实 Agent Run 的完成率评估或外部图表基准适配 | 需定义 Run 样本、人工标注、任务级指标和可复现的模型/Provider 条件 |

```mermaid
flowchart LR
    Image[Attachment / Panel] -->|当前：measure_chart schema v3 + OCR| Measure[十类 ChartSpec v2 family 的候选观察]
    Measure -->|当前：模型可选传入引用| Figure[ChartFigure 组装工具]
    Figure -->|调用参数与结果存于通用 Run 工具事实| Runtime[Runtime]
    Runtime -->|工具事实 + Sources 附件/Panel 元数据| State[Agent RunExecutionState.resources]
    State -->|六类类型化资源；提示使用精简索引| Agent[Agent]
    Figure -.->|未来：显式来源验证| Choice[EvidenceRef]
    Choice -.-> Spec[持久 ChartSpec + provenance]
    Figure -->|当前：render_chart_figure 生成 PNG| Render[当前工作树：ChartFigure → PNG 暂存与预览]
    Render -.->|未来：生成图验证| Verify[VerificationResult]
    Verify -.-> Publish[PublishedArtifact]
    Runtime[真实 Agent Run 事实] -.->|未来：端到端评估| Eval[Evaluation 诊断]
```

附件与 Panel 目前属于同一个 Sources 能力；渲染 PNG 是按 Run/调用身份保存的私有文件，不新增 Source metadata 模型。模型字段见[Sources](figura/sources.md)，完整资源目录合同见[Agent](figura/agent.md#4-runexecutionstate-资源合同与完整字段)，工具输入输出见[Tools](figura/tools.md#6-图像与测量工具合同)。`improve-figura-chart-measurement-reliability` 已归档，测量回归、十类结果合同和对应主规格已同步。测量引用标识成功工具调用，不证明 ChartSpec 数据值正确；旧 `src/chartagent/` 的身份、字段和存储不能直接视作新 Figura 合同。

## 5. 阅读与状态规则

查**完整字段**时，从组件表进入该合同的 owner 专题；跨领域使用者只链接并解释消费方式。专题边界由模型的语义、权威 owner、生命周期和不变量决定，后续出现独立领域时增建子文档，不能按调用链强行合并。嵌套值、联合 payload、枚举和字段来源在所属专题展开。查长期完整产品构想时，参阅[Figura 架构设计草案](figura-architecture-design.md)，其中未实现部分不自动成为当前合同。

当前主规格位于 `openspec/figura/openspec/specs/`。截至 2026-10-19，图表测量、图像反馈、上下文压缩与检索等历史 change 已同步并归档；[DeepSeek 摘要优化](../openspec/figura/openspec/changes/archive/2026-10-19-improve-deepseek-compaction-summary/tasks.md) 与 [Provider 流式改造](../openspec/figura/openspec/changes/archive/2026-10-19-unify-figura-request-streaming/tasks.md) 的 delta 也已同步并归档。后一 change 的 5.3、5.4 仍未勾选：全量 Python 测试报告有 35 项因缺少旧图表 fixture 失败，在线 Provider 长请求与传输故障验证未执行。当前 `figura` store 没有活动 change；代码、主规格与归档记录均尚未提交。旧系统代码与规格分别位于 `src/chartagent/` 和 `openspec/chartagent/`，只在迁移或兼容性分析中对照。

当前实现已接通协作停止、异常历史续用、上下文压缩和渐进式历史读取：Web 保存停止请求，Agent 在 Run owner 保护下完成当前动作并在边界收尾；Gateway 周期扫描补偿无人执行的 running Run。Memory 将合法异常尾部转为来源可寻址的 outcome。摘要覆盖的旧消息仍保留规范事实，可由历史工具搜索并精确读取；历史图像需显式请求，不能仅凭目录自动加载。新增字段和读取合同见 [Runtime](figura/runtime.md)、[Memory](figura/memory.md)、[Agent](figura/agent.md)与[Tools](figura/tools.md)。

上下文能力的当前实现依据见[预算与恢复归档设计](../openspec/figura/openspec/changes/archive/2026-10-09-refine-figura-context-compaction-budgets/design.md)、[历史输入保留与摘要目标设计](../openspec/figura/openspec/changes/archive/2026-10-10-preserve-user-inputs-in-context-compaction/design.md)、[活动 Run 历史压缩设计](../openspec/figura/openspec/changes/archive/2026-10-10-compact-active-run-history/design.md)和[早期压缩设计](../openspec/figura/openspec/changes/archive/2026-10-05-session-context-compaction/design.md)；相关 delta 均已同步到主规格。容量对照的实验方法和适用范围见 [Evaluation 专题](figura/evaluation.md)。图像观察引导的设计依据见[归档提案](../openspec/figura/openspec/changes/archive/2026-10-08-add-figura-image-feedback-guidance/proposal.md)。

### 规格与实现的已知差异

截至 2026-10-19，两个 Provider change 的主规格已同步，`figura` 全部 28 份主规格通过严格校验。Provider 流式功能的代码与规格已在当前工作树中，但在线 Provider 验证尚未执行；因此长时间保持连接、实际 Provider 事件形状与网络故障分类的端到端行为仍未得到在线证据。全量 Python 测试有 35 项因缺少 `tests/fixtures/legacy_charts/` 图片或 manifest 失败；已完成的 focused 测试、前端 build/smoke、change 严格校验和 `git diff --check` 记录见归档任务。实现与规格状态不等同于已完成在线验收。

Agent 执行、Provider 流式、请求重试、历史检索、上下文压缩、工具运行时与图像观察相关主规格见 [Agent ReAct](../openspec/figura/openspec/specs/agent-react-execution/spec.md)、[Provider](../openspec/figura/openspec/specs/model-provider/spec.md)、[Provider retry](../openspec/figura/openspec/specs/provider-request-retries/spec.md)、[Run 执行核心](../openspec/figura/openspec/specs/run-execution-core/spec.md)、[历史检索](../openspec/figura/openspec/specs/session-context-retrieval/spec.md)、[上下文压缩](../openspec/figura/openspec/specs/session-context-compaction/spec.md)、[工具运行时](../openspec/figura/openspec/specs/tool-runtime/spec.md)和[图像观察解码](../openspec/figura/openspec/specs/image-observation-decoding/spec.md)。结构与回归测试不证明真实模型遵循效果。当前 `openspec list --store figura` 无活动 change；归档 change 不代表其未完成的在线验收已完成。
