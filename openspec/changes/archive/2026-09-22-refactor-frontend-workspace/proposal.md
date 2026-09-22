## Why

前端已经承载会话、运行时间线、SSE 重连、恢复/重试、附件、评测、预览和错误映射等多类职责，但这些实现目前集中在少数大型文件中。`App.tsx`、全局样式、协议类型和 Gateway client 继续叠加功能会增加重复逻辑和回归风险，也让普通会话与评测展示难以共享基础设施。现在后端和运行协议已经稳定，适合进行一次保持行为不变的前端内部重构。

## What Changes

- 将前端按会话、运行、评测、附件、预览和通用展示职责拆分为清晰的模块与组件。
- 将运行时间线归一化、事件合并、状态标签、测量修复摘要和错误映射提取为可复用的纯逻辑。
- 统一新运行、历史恢复、SSE 补偿、重连、重试、继续执行和中断的前端控制流程，删除重复实现。
- 在保持 `ChartAgentClient` 外部接口兼容的前提下，拆分 Gateway transport、数据映射、运行订阅和评测 API 实现。
- 将协议类型、mock 数据、样式和前端 smoke 契约按职责整理，删除确认无引用的冗余实现与兼容空壳。
- 保持普通会话、评测只读工作台、工具结果、视觉观察、生成图预览、模型选择和运行状态的现有行为不变。
- 不引入新的状态管理库，不修改 Gateway/SSE 协议、后端 API、Tauri 行为或用户可见的产品能力。

## Capabilities

### New Capabilities

无。本 change 只重构前端内部实现，不引入新的运行时能力。

### Modified Capabilities

无。本 change 不改变任何现有 OpenSpec requirement，因此使用 `skip_specs: true`。

## Impact

- 主要影响 `frontend/src/App.tsx`、`frontend/src/api/`、`frontend/src/types/`、`frontend/src/styles/` 以及前端 mock 和 smoke 脚本。
- 保留 `ChartAgentClient`、Gateway 请求字段、SSE 事件字段、资源引用和既有导出作为稳定兼容边界。
- 需要补充或调整前端构建、smoke、事件回放、重连/恢复和评测只读展示验证。
- 不涉及 Python Gateway、Agent、图表工具、数据库 schema、Tauri/Rust 或新的外部依赖。
