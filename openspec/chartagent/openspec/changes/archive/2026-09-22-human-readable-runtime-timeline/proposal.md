## Why

当前时间线把内部的 `process`、模型轮次、`operation` 和兼容事件直接渲染成嵌套卡片，导致普通运行和评测页面像调试器一样层层包裹，用户难以连续理解“加载、拆解、测量、组装、审核、生成、失败”的真实过程。需要将内部关联投影与用户展示投影分开，让界面只呈现有业务意义的步骤。

## What Changes

- 新增面向用户的扁平时间线投影；内部 `process`、`turn`、`operation` 和 `legacy` 关联仅用于重放、去重、状态和诊断，不再直接生成顶层展示卡片。
- 将 `tool_call`、`tool_result` 和关联的 `visual_observation` 合并为一个可折叠工具步骤。
- 默认隐藏 `model_started`、`model_completed`、`operation_completed`、`run_started`、`resume_started` 等技术生命周期事件；模型调用失败仍通过可读的错误终态展示。
- 保留测量、审核、生成、发布、恢复阻塞和终态错误等用户可理解的业务步骤，移除默认展示的 sequence、原始事件套娃和无意义的兼容卡片。
- 普通运行和评测工作台共用同一套用户时间线投影；评测只增加 case/report 上下文，不重新解释 execution history。
- 保留按需展开的安全详情入口，但不改变后端事件事实来源、重连、幂等、恢复和 lineage 语义。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `desktop-client`: 普通运行使用扁平、中文、面向业务步骤的执行时间线，隐藏模型和 operation 技术生命周期事件。
- `evaluation-workbench`: 评测只读时间线复用普通运行的用户展示投影，并保持工具、错误和审核详情一致。
- `unified-decision-review-timeline`: 明确内部 decision/process projection 与用户展示 projection 分离，兼容事件不再默认成为视觉容器。

## Impact

- 主要影响 `frontend/src/components/run.tsx`、`frontend/src/domain/run/timeline.ts`、前端运行样式和相关 smoke/回放测试。
- 不新增后端接口、模型调用或持久化存储；现有 execution event history 继续作为唯一事实来源。
- 需要验证普通运行、历史刷新、SSE 重连、显式 retry、评测只读回放以及旧事件兼容场景的可读性和一致性。
