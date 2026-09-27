# Figura 系统总览

> 更新日期：2026-09-27。范围：新 Figura 的当前工作树 `src/figura/`。代码、主规格、归档记录、目标设计和旧 `chartagent` 分别标记。本文是入口；组件内部流程与完整字段见按领域划分的专题文档。

## 1. 一眼看懂 Figura

Figura 接收用户文本和图像，创建可恢复的 Run，让 Agent 调用模型与工具。一个 Session 中后续 Run 会从较早终态 Run 的持久事实重建完整对话。**当前新 Figura 已有内部文本/图像 ReAct、跨 Run 对话投影、耐久执行基础，以及本地 HTTP/SSE Gateway 和 React 网页入口**。来源观察、证据选择、生产图表工具、渲染、验证、发布与评测链尚未实现；仓库中的 `src/chartagent/` 是旧系统，不能把其能力画作新 Figura 的已运行组件。

```mermaid
flowchart LR
    UI[React Figura 网页] -->|FiguraClient / Workspace API| Gateway[本地 Figura Gateway]
    Gateway -->|Session、Run 查询与创建| Runtime[Run Runtime]
    Gateway -->|图片上传、列表、内容读取| Attach[Attachment Service]
    Attach -->|Session 附件元数据| Runtime
    Attach -->|私有图片文件| Files[(私有文件)]
    Gateway -->|异步提交已持久化 Run| Dispatcher[Run Dispatcher]
    Dispatcher -->|execute(session_id, run_id)| Agent[Agent]
    Gateway -->|本地配置可用性| Provider[Provider Boundary]
    Runtime -->|RunState、Checkpoint| Agent[Agent]
    Agent -->|读取较早的终态 RunState| Runtime
    Agent -->|当前 Run 与较早 Run 的事实| Memory[Session Memory Projection]
    Memory -->|完整有序角色消息| Agent
    Agent -->|按 Session 解析当前和历史图片| Attach
    Agent -->|ProviderRequest| Provider[Provider Boundary]
    Provider -->|ProviderResponse| Agent
    Agent -->|ToolInvocation| Tools[Tool Runtime]
    Tools -->|ToolExecutionResult| Agent
    Agent -->|执行事实、Attempt、终态| Runtime
    Runtime -->|SQLite 事实与事件| DB[(Figura SQLite)]
    Runtime -->|安全 Session / Run / Event 投影| Gateway
    Gateway -->|JSON / SSE| UI
    Chart[ChartSpecData Core] -.->|尚未接入组装工具与 Run| Agent
    Future[来源/证据、图表产物、渲染、验证、发布、评测] -.->|后续 change| Runtime
```

实线是当前新 Figura 的工作树路径；虚线表示尚未接入的 ChartSpecData 能力或目标设计。Web Gateway 只公开安全投影，并通过有界异步 Dispatcher 进入 Agent；当前 Gateway 组合使用空 ToolRegistry，因此这条网页入口还没有生产图表工具。Run Runtime 的执行事实是恢复依据；Agent 的 Session Memory 是从这些事实重建的只读调用期投影，没有独立消息表。Gateway 的会话消息投影则只展示持久用户输入与已接受最终答案，两者用途不同。事件只是安全投影。模型请求中的 `ImageBlock` 是调用期内容，Run 输入只保存附件 ID。

## 2. 大组件与下钻入口

| 组件 | 职责与跨组件交付 | 当前状态 | 内部文档 |
|---|---|---|---|
| Run Runtime | Session、Run、执行事实、Attempt、Checkpoint、生命周期事件；交付可恢复 `RunState` 和同 Session 较早 Run 的一致快照；每 Session 至多一个 running Run | 当前工作树已实现 | [运行时与恢复](figura/runtime.md) |
| Attachment Service | 验证并私有保存 Session 图片；交付经 Session 校验的 `ImageBlock`；Gateway 提供本地网页上传与读取 | 当前工作树已实现 | [附件与来源边界](figura/attachments.md) |
| Agent | 按 checkpoint 组装请求、协调模型和工具、提交结果与终态；由 Gateway Dispatcher 异步调用 | 当前工作树已实现内部同步 ReAct 与 Gateway 调度入口 | [Agent 编排](figura/agent.md) |
| Session Memory Projection | 从同 Session 的 Run 事实构建完整角色消息；无独立持久化、裁剪或摘要 | 当前工作树已实现，按请求重建 | [Session Memory](figura/session-memory.md) |
| Provider Boundary | 选择固定 provider/model，归一化请求、响应和安全失败 | 已实现 Qwen、DeepSeek、MiMo | [Provider 集成](figura/provider.md) |
| Tool Runtime | 版本化定义、参数/结果校验及 handler；执行事实归 Runtime | 基础设施已实现，无生产图表工具 | [Tool 能力与调用](figura/tools.md) |
| 共享 JSON Schema 合同 | 有界 JSON 与受支持 Schema 子集的校验，供多个领域消费 | 已实现基础校验 | [共享验证合同](figura/shared-validation.md) |
| Local Gateway 与 React Figura 网页 | Session、附件、Run HTTP API、安全历史投影与 SSE；前端经 Figura client 复用工作区 UI | 当前工作树已实现；网页入口尚无生产图表工具 | [网页端边界](figura/web-boundary.md) |
| ChartSpecData Core | 单图内容值、解析、校验和规范序列化 | 当前工作树有未提交代码；change 已移入未提交归档目录，主规格已出现 | [图表内容模型](figura/chartspec.md) |
| 来源、证据、产物与发布 | 观察、选证、渲染、验证、发布 | 新 Figura 尚未实现 | [后续能力边界](figura/future-boundaries.md) |
| Evaluation | 从权威 Run 事实读取诊断结果 | 新 Figura 尚未实现 | [后续能力边界](figura/future-boundaries.md) |

## 3. 跨组件内容流

1. **网页输入与身份**：React Figura UI 通过 `FiguraClient` 调用 loopback Gateway。Gateway 创建/列出 Session，并委托 Attachment Service 上传、读取和删除图片；Run 创建只提交文本、有序附件 ID、provider ID 与幂等键。Runtime 先处理幂等重放，再拒绝同 Session 的第二个 running Run；成功时校验附件归属并保存输入、初始 checkpoint、Run 和创建事件。图片字节留在私有文件中。见[网页边界](figura/web-boundary.md)、[运行时](figura/runtime.md#2-内部流转)和[附件](figura/attachments.md#2-内部流转)。
2. **重建 Session 对话**：每次模型动作前，Agent 向 Runtime 读取目标 Run 之前的终态 RunState；Runtime 在一个 SQLite 读快照中按 ordinal 排序并检查范围与完整性。Session Memory 将历史 Run 以及当前 Run 的已提交前缀投影为完整 user/assistant/tool 消息。见[Session Memory](figura/session-memory.md#3-内部流转与失败边界)。
3. **组装模型请求**：Attachment Service 按同一 Session 解析当前和历史输入中的附件，工具 Registry 投影为模型可见定义。Agent 校验完整 ProviderRequest；不裁剪历史，任何附件或 Provider 硬限制不满足都会在 attempt claim 前失败。Provider 返回规范化 `ProviderResponse` 后，Runtime 提交响应、continuation、工具调用意图、Attempt 结论与下一 checkpoint。见[Agent 编排](figura/agent.md#2-内部流转)和[Provider 合同](figura/provider.md#2-内部流转)。
4. **工具与恢复**：Tool Runtime 校验并执行 handler；Runtime 单独记录调用、启动和结果。已启动但结果不明的工具效果不会由 Agent 自动重放；已启动但未提交响应的 Provider attempt 也不会自动重发。Gateway 启动时按稳定顺序发现 running Runs，并交给同一 Dispatcher/Agent 恢复路径。分别见[Tool 调用](figura/tools.md#2-内部流转)和[运行时恢复](figura/runtime.md#2-内部流转)。
5. **返回网页**：Gateway 从 Runtime 读取 Session snapshot、Run history 和安全事件，再投影 JSON/SSE；Conversation 只显示持久用户输入与已接受最终答案，不把 Agent 的完整 Session Memory、工具消息或 Provider continuation 暴露为普通对话。详见[网页端边界](figura/web-boundary.md)。
6. **图表链**：当前 `ChartSpecData` 能表达并验证单图内容，但尚不保存为 Run 图表对象，也没有来源证据、渲染、验证或发布连接。目标链见[后续能力边界](figura/future-boundaries.md)，不属于上述实线路径。

## 4. 阅读与状态规则

查**完整字段**时，从组件表进入该合同的 owner 专题；跨领域使用者只链接并解释消费方式。专题边界由模型的语义、权威 owner、生命周期和不变量决定，后续出现独立领域时增建子文档，不能按调用链强行合并。嵌套值、联合 payload、枚举和字段来源在所属专题展开。查长期完整产品构想时，参阅[Figura 架构设计草案](figura-architecture-design.md)，其中未实现部分不自动成为当前合同。

当前主规格位于 `openspec/figura/openspec/specs/`。网页边界已有 `figura-web-gateway` 与 `figura-web-client` 主规格；`connect-figura-web-frontend` 的规划 change 仍在活动目录，尚未归档。`add-figura-chartspec-core` 已从活动列表消失，归档目录和主规格均在当前未提交工作树中；这不代表后续持久 ChartSpec 或渲染链已实现。旧系统代码与规格分别位于 `src/chartagent/` 和 `openspec/chartagent/`，只在迁移或兼容性分析中对照。
