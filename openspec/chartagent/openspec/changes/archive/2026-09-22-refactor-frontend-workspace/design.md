## Context

当前前端以 `App.tsx` 为主要编排文件，文件内同时包含工作区布局、会话加载、附件上传、运行提交、SSE 订阅、历史补偿、重连、重试、继续执行、评测读取、图片预览和大量展示组件。`gatewayClient.ts` 同时承担请求传输、响应映射、运行订阅和评测 API；`protocol.ts` 混合多个领域的类型；`global.css` 混合所有工作区的样式。普通会话和评测页面已经共享部分运行事件语义，但状态读取和展示仍由同一个入口文件分别组织。

本 change 只调整前端内部所有权。`ChartAgentClient`、Gateway HTTP/SSE 字段、资源引用、运行状态语义、Mock/Gateway 两种模式和用户可见行为是稳定边界；不引入新的状态管理库或外部依赖。

## Goals / Non-Goals

**Goals:**

- 让顶层入口只负责工作区组合和跨工作区选择，不再拥有所有业务细节。
- 让运行时间线归一化、事件去重、重连/历史补偿和终态收敛各只有一份实现。
- 让普通会话与评测只读工作台复用运行时间线、工具结果、视觉观察和状态标签基础设施。
- 按业务边界拆分协议类型、Gateway adapter、mock fixture、React 组件和 CSS。
- 保留现有公共接口和兼容 façade，支持逐阶段迁移和回滚。
- 使构建、smoke 和事件回放检查不依赖某个大型文件必须包含全部实现字符串。

**Non-Goals:**

- 不改变 Gateway、SSE、评测资源或后端 API 契约。
- 不增加新的用户功能，不重新设计视觉风格，不改变中文文案的语义。
- 不引入 Redux、Zustand 或新的组件库。
- 不修改 Python、Agent、图表工具、数据库 schema、Tauri/Rust 或生产依赖。
- 不为了追求文件行数而拆分本身具有完整职责的小模块。

## Decisions

### 1. 使用按业务域组织的前端结构

采用“工作区编排 + 业务域组件 + 纯逻辑/API”的结构，而不是把所有内容按 `components/`、`hooks/`、`utils/` 平铺。目标边界如下：

```text
App / WorkspaceShell
├── SessionWorkspace
│   ├── SessionSidebar
│   ├── ConversationPanel
│   ├── RunTimeline
│   └── AttachmentPanel
├── EvaluationWorkspace
│   ├── EvaluationPanel
│   ├── EvaluationTimeline
│   └── EvaluationDetail
├── PreviewOverlay
└── Dialogs
```

组件只负责渲染和用户交互；事件归一化、标签、错误和资源映射放在纯逻辑模块；网络和 SSE 只通过 `ChartAgentClient` 及其 adapter 暴露。这样可以避免仅把大型文件机械切片、却继续共享隐式状态的问题。

### 2. 将运行生命周期集中为一个控制器

新增运行和页面恢复中的运行都经过同一套运行控制流程，统一处理：

1. 启动或恢复请求；
2. 从当前 sequence 订阅 SSE；
3. 事件合并和重复过滤；
4. 断线后的历史补偿；
5. 有界退避重连；
6. 中断、重试、继续执行和终态刷新。

时间线归一化保持纯函数，运行控制器只管理异步生命周期和状态更新。控制器继续使用现有 `runId`、`afterSequence`、幂等 key、history gap 和 recovery 字段，不在前端重新解释后端协议。

相比在 `App` 中继续保留两套订阅代码，这能消除闭包、游标和清理逻辑分叉；相比引入全局状态库，局部工作区 hook 更符合当前单窗口、单活动运行模型。

### 3. 保留稳定的 API façade，内部拆分 Gateway 实现

保留 `api/client.ts` 中的 `ChartAgentClient` 作为唯一组件依赖。Gateway 实现内部可拆为 transport、session、run stream、evaluation 和 payload mapper，但 `gatewayClient` 继续导出当前客户端对象和 URL/错误入口。Mock client 继续实现同一接口，fixtures 与行为代码分离。

这样可以限制网络细节向组件泄漏，也避免一次重构迫使所有调用者改变 import 路径。任何旧的公开导出只有在确认无外部/测试使用后才删除，否则保留轻量兼容导出。

### 4. 按领域拆分协议类型并保留 barrel export

将会话、运行与恢复、评测、预览、Provider/健康状态拆到独立类型模块；`types/protocol.ts` 保留为 re-export 入口。纯类型模块不依赖 React、API 或组件，避免循环依赖，并让评测与普通运行共享同一组 `AgentRunEvent`、`RunHistory` 和资源类型。

### 5. 共享运行时间线，使用只读能力参数区分场景

普通会话与评测不再各自维护工具调用/结果、视觉观察和事件标签的拼装逻辑。共享的时间线组件通过 props 或只读 view model 区分：

- 是否允许中断、重试或继续执行；
- 是否显示评测资源和详情资源入口；
- 是否显示会话级操作。

评测仍保持只读，不能因为复用组件而获得运行控制能力。

### 6. 样式采用导入聚合而非全局重写

将全局样式按 tokens/layout、conversation/run、evaluation、attachment/preview、dialog 等职责拆分，由一个稳定入口按固定顺序导入。首轮不改 class 语义和视觉参数，只移动规则并处理重复声明，避免结构重构混入 UI 重设计。

### 7. 将 smoke 从文件位置契约改为能力契约

现有 smoke 通过拼接少数源码文件并查找字符串来验证功能，模块移动后会产生误报。迁移后保留必要的静态契约检查，但按实际模块路径读取并验证公开 façade、关键事件名、运行状态和启动脚本；同时以 `npm run build` 作为 TypeScript/import 边界检查。不会为了测试方便把实现重新集中回 `App.tsx`。

## Risks / Trade-offs

- **[运行重连或恢复行为回归]** → 先抽取纯函数，再抽取控制器；保留现有事件样例和 `runId:sequence` 去重规则，逐阶段执行 build、smoke 和 Gateway 回归。
- **[组件拆分后出现循环依赖]** → 规定依赖方向：types → domain → api/components，domain 不依赖 React，components 不直接访问 Gateway transport。
- **[评测误获得普通会话操作能力]** → 评测组件显式使用只读 props，Gateway client 仍通过独立的读取方法提供评测数据。
- **[CSS 导入顺序导致视觉回归]** → 先保持现有 class 和选择器优先级，拆分后进行宽、中、窄窗口的 build/smoke 与人工检查。
- **[删除兼容代码造成隐藏调用失败]** → 先用 `rg`、TypeScript 构建和 smoke 确认引用，再删除；不确定的公开入口保留 façade。
- **[静态 smoke 过度依赖实现细节]** → 将检查目标改为稳定的入口、契约和能力标记，而不是要求具体逻辑仍位于某一个文件。
- **[重构范围膨胀为 UI 重写]** → 以行为和协议不变为验收基线，新增交互或视觉改版另开 change。

## Migration Plan

1. 记录当前 `npm run build`、`npm run smoke` 和关键前端能力基线，建立待删除符号和公共导出清单。
2. 先拆分协议类型、错误/格式化函数、时间线归一化和 Gateway payload mapper；此阶段不改变组件树。
3. 提取运行生命周期控制器，令新运行与恢复运行共用订阅、补偿、重连和终态逻辑。
4. 拆分 Session、Run、Evaluation、Attachment、Preview 组件，并让评测接入共享时间线。
5. 拆分 Gateway adapter、mock fixtures 和 CSS，更新 smoke 的能力检查。
6. 清理确认无引用的旧实现与空壳导出，运行完整前端验证和相关 Gateway/Python 回归。

每个阶段都应保持可构建；若需要回滚，优先恢复对应阶段的前端文件，保留后端协议和数据不变。由于不改持久化和外部 API，不需要数据迁移或运行记录迁移。
