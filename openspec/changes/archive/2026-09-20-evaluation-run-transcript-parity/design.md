## Context

当前普通会话通过 Gateway 的 `RunHistory` 和前端 `RunTimeline` 展示运行过程；评测工作台却通过 `EvaluationReader` 生成轻量事件摘要，再将 `records` 与 `gateway_run_events` 合并成另一种详情 DTO。两条链路的数据源、排序、工具调用关联和安全投影规则不同，导致评测中的工具结果比普通会话更不完整。

本设计需要兼容已经存在的评测 bundle。当前 bundle 的 `gateway_run_events` 仍可能保存完整的安全事件，但 `records` 或读取投影可能已经截断；历史数据不能被补造。普通 Gateway 事件本身仍受 `MAX_EVENT_PAYLOAD` 约束，因此未来的大型安全结果需要独立的详情承载方式。

## Goals / Non-Goals

**Goals:**

- 让评测 case 的运行记录使用与普通会话一致的事件语义和工具调用/结果分组方式。
- 保留完整的安全结构化结果，尤其是 `bbox`、多边形、坐标轴、柱体、系列和点坐标等图表数据。
- 让当前已保存的 bundle 尽可能直接恢复；无法恢复的历史截断必须明确说明来源和原因。
- 对大结果提供评测范围内、按需读取、可校验归属的安全详情资源。
- 保持评测只读、普通会话行为不变，并继续禁止凭据、私有推理、本地绝对路径和图片二进制进入前端。

**Non-Goals:**

- 不开放原始 SQLite、原始 provider response 或隐藏 reasoning。
- 不把评测变成可重跑、可修复或可修改的操作面板。
- 不重新设计普通会话的事件持久化协议；只抽取共享的序列化和展示语义。
- 不为历史上已经丢失的 payload 推断数值或生成伪造结果。

## Decisions

### 1. 以 Gateway 事件作为运行过程的权威来源

评测执行过程以 `gateway_run_events` 作为工具调用、工具结果、视觉观察、修复、审核、失败和恢复事件的权威来源；`records` 只补充用户/模型可见对话或事件中不存在的上下文。相同 `call_id` 的记录不再作为第二份工具结果并列展示，避免完整事件和被截断模型工具消息互相干扰。

评测 history 返回与普通会话 `RunHistory` 兼容的事件 DTO。评测资源引用只在 Gateway 到前端的映射层补充 evaluation/case 作用域，不改变普通事件字段的含义。

### 2. 复用运行时间线，而不是维护第二套工具详情组件

将普通会话使用的工具步骤归并逻辑、事件标签、工具调用/结果展开、视觉观察挂载和生命周期事件展示抽取为可复用的只读运行时间线组件。普通会话继续保留中断、重试、继续执行等动作；评测传入只读模式，不显示会修改状态的动作。

评测页面仍保留批次、case、阶段诊断、报告和证据画廊，但选中 case 后的运行过程按普通会话方式直接展示。按需加载只用于避免评测列表和 case 概览被大型详情撑大，不再让用户先看到一个永远不含工具结果的摘要时间线。

### 3. 采用语义化安全投影

安全投影保留以下边界：敏感键删除、`data:`/图片字节隐藏、文本与集合大小上限、单条结果和总响应上限。投影不再使用单一全局递归深度作为截断依据：

- 标量数值、布尔值和坐标数组按原子值保留；
- `bbox`、`polygon`、`points`、`bars`、`series`、`axes`、`baseline`、`plot_area`、`plot_frame`、`evidence` 等已知图表结构按字段保留；
- 超过集合或字节上限时，在具体字段上返回结构化截断信息，包括来源、原因、保留数量和可否继续读取；
- 普通未知对象仍经过通用投影，不能因为字段名称未知而绕过敏感数据检查。

这样可以同时满足“完整安全展示”和“不能把任意 provider payload 无界暴露给前端”。

### 4. 大结果使用评测范围内的详情资源

当经过安全处理的工具结果无法放入普通事件 envelope 时，事件保留 `tool_name`、`call_id`、状态、序号、摘要和一个不透明的 detail reference；完整安全结果写入当前 evaluation bundle 的 allowlist 目录，并登记 evaluation、case、run、媒体类型、字节数和摘要指纹。

详情读取必须校验 evaluation/case/run 归属、资源 ID、媒体类型和大小上限。前端只按需请求该结构化 JSON，不直接拼接本地路径或打开 SQLite。对于旧 bundle 没有 detail reference 的情况，读取器继续展示事件中已有结果并标记“持久化阶段不可恢复”。

### 5. 明确三类完整性状态

DTO 将区分：

- `persisted_truncated`：事件或 records 写入时已经丢失内容；
- `projection_truncated`：读取安全投影因响应/集合上限隐藏内容；
- `detail_unavailable`：存在详情引用但当前资源不可读或未授权。

前端在工具结果附近显示具体状态，而不是将所有情况合并为“结果不完整”。前端容器允许滚动查看完整返回内容，并提供展开/复制结构化 JSON 的入口；视觉上的折叠不改变数据是否已经返回。

### 6. 兼容当前 bundle 和普通会话

当前 `bar_line_dashboard` bundle 的读取优先走已有 `gateway_run_events`，因此 `decompose_chart_image`、`measure_bars` 和 `extract_line_series` 的深层几何字段可以在不重跑评测的情况下恢复。缺失 records 时保留事件时间线；缺失 detail resource 时不伪造内容。

普通会话继续使用原有 Gateway history 和持久化路径。共享的是事件 DTO、归并逻辑和安全规则，不改变普通会话的存储位置、运行控制或恢复协议。

## Risks / Trade-offs

- **[完整事件让单次响应变大]** → 选中 case 后按需读取，保留事件分页/序号游标，大结果使用独立 detail resource，不把它们放入评测列表。
- **[安全投影规则过宽导致敏感字段泄露]** → 先执行敏感键和二进制检查，再执行语义字段保留；所有资源通过 evaluation/case/run 归属校验。
- **[旧 bundle 已经永久截断]** → 保留已有 preview，明确标记 `persisted_truncated`，不尝试从模型或图片反推缺失 JSON。
- **[records 与 events 的时间/序号空间不同]** → 主运行顺序使用 event sequence；records 作为带 source 标记的补充消息，并通过 call_id、时间戳和可用 turn 关联。
- **[共享前端组件影响普通会话]** → 先建立普通会话现有行为快照，再以只读参数接入评测，增加普通会话回归测试。

## Migration Plan

1. 先抽取共享的安全事件序列化、工具步骤归并和只读运行时间线 DTO，保留旧评测接口作为兼容回退。
2. 改造评测 history/detail 读取，使当前 bundle 优先返回完整的 persisted Gateway event payload，并在深层图表结构上验证数值不丢失。
3. 接入评测专用大结果 detail resource；新运行写入引用，旧 bundle 不需要迁移即可使用已有事件结果。
4. 将评测前端切换到共享运行时间线，补充截断来源、资源不可用、历史缺口和只读状态展示。
5. 通过后端单测、当前 `bar_line_dashboard` 回归、前端 build/smoke 和普通会话回归后，再移除评测主链路中的旧摘要详情依赖。回滚时保留旧只读接口和已生成 bundle，不删除评测数据。
