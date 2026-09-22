## Context

当前 `projectDecisionTimeline` 同时承担事件关联、状态计算和前端展示数据组织，`RunTimeline` 又直接把返回的每个 unit 渲染为嵌套 `details` 卡片。上一项 change 已经补齐 process/turn/operation 关联，但这些关联是为了重放和诊断，不应成为用户看到的界面层级。普通运行和评测目前共享 `RunTimeline` 组件，因此需要在共享的时间线领域层增加一个更明确的用户展示投影。

## Goals / Non-Goals

**Goals:**

- 保留内部 decision/process projection 的关联、状态、去重和 lineage 能力。
- 输出一条按事件顺序排列、面向业务步骤的扁平用户时间线。
- 将工具调用、工具结果和视觉观察合并为一个可折叠步骤。
- 默认隐藏模型轮次开始/结束、operation 保存和运行启动等技术事件。
- 让隐藏技术事件中的失败信息仍能出现在可见的错误或终态步骤中。
- 让普通运行和评测通过同一个用户展示投影保持一致。

**Non-Goals:**

- 不删除或重写后端 execution event history。
- 不改变模型调用、工具调用、审核、恢复、重试或发布行为。
- 不重新设计 measurement、review、generation 的业务状态机。
- 不把原始 payload 从系统中删除；原始安全详情仍可按需读取。

## Decisions

### 1. 分离内部关联投影与用户展示投影

保留现有 decision/process 投影作为事实关联层，新增用户展示投影作为唯一的普通运行和评测渲染输入。用户展示投影只返回有限的可见项，例如 `tool`、`measurement`、`review`、`generation`、`publication`、`error` 和 `observation`，不返回 process/turn/operation 容器。

选择分离而不是直接修改 `DecisionUnitItem` 的原因是：内部 unit 需要继续承载状态和 lineage，而用户界面需要不同的层级和过滤规则。只改 CSS 或给 process 卡片换中文名称，无法消除嵌套语义。

### 2. 使用显式的技术事件过滤策略

默认不产生可见项的事件包括 `run_started`、`resume_started`、`model_started`、`model_completed`、`operation_completed` 和 `final_answer`。`final_answer` 已由对话结果区域承担；run 状态由运行摘要承担。`run_failed`、`run_interrupted`、`recovery_blocked`、`budget_exhausted` 以及业务审核/测量/生成事件仍然产生可见项。

过滤只影响默认展示，不影响内部状态计算。若隐藏的 `model_completed` 或其他技术事件包含结构化失败上下文，展示投影必须将其合并到同一 run 的错误终态或对应工具步骤，不能静默丢失。

### 3. 工具是用户时间线的基本动作单位

通过 `call_id` 将 `tool_call` 和 `tool_result` 合并为一个工具项；将带有相同 `call_id` 的 `visual_observation` 附着在该工具项下。工具项默认收起，只在展开时展示参数、结果、状态、图片和安全详情资源。没有 call id 的旧工具事件使用有限的 sequence fallback，但仍按工具事件展示，不创建“历史事件”外壳。

### 4. 业务步骤使用扁平列表，详情使用按需展开

`RunTimeline` 只渲染用户展示项的顺序列表。测量、审核、生成和发布可以作为紧凑业务卡片，但不得再被 process/turn/operation 卡片包裹。默认不展示 sequence、原始事件数组和内部 unit id；这些内容保留在“查看技术详情/原始安全记录”入口中。

这样既能让用户看到“做了什么、结果如何、下一步是什么”，又不会损失 test5 诊断所需的完整事实。

### 5. 评测复用同一展示输入

评测页面继续调用普通的 `RunTimeline`，只传入只读权限和 evaluation/case 上下文。评测层不得重新遍历事件或重建自己的过滤规则；评测报告和证据区独立于时间线，但工具、错误、审核和终态的顺序及显示方式完全一致。

### 6. 通过回放夹具验证“可见项”而不是仅验证 unit 数量

前端回归需要断言：

- model lifecycle 和 operation-save 不生成可见项；
- tool call/result/observation 合并为一个工具项；
- failure context 从隐藏事件进入可见错误项；
- 普通运行与评测使用同一投影；
- 重复 sequence/transition 不产生重复可见项；
- 旧事件仍可读，但不会制造大量兼容卡片。

## Risks / Trade-offs

- [Risk] 过滤技术事件时可能隐藏唯一的失败原因 → [Mitigation] 先抽取结构化 failure envelope，再过滤，并将失败提升到可见终态；没有结构化字段时保留通用错误摘要。
- [Risk] 扁平列表可能削弱复杂 review collection 的父子关系 → [Mitigation] 只隐藏 process/turn/operation 容器，保留 review collection、candidate attempt 和 review sub-check 的业务关系。
- [Risk] 旧事件无法建立精确关联 → [Mitigation] 继续使用内部 legacy bucket 和 sequence 去重，但默认只展示其中有业务意义的步骤。
- [Risk] 普通运行和评测出现展示漂移 → [Mitigation] 两者只调用同一个用户展示投影，并增加等价回放测试。

## Migration Plan

1. 在前端领域层增加用户展示项类型和投影，暂不修改后端事件。
2. 将普通运行和评测的 `RunTimeline` 切换到该投影，保留工具、审核和安全详情组件。
3. 删除默认渲染 process/turn/operation/legacy 容器的路径，保留内部投影供状态和诊断使用。
4. 更新样式和回放/smoke 测试；如发现历史兼容问题，可回退到旧渲染入口，事件数据无需迁移。

## Open Questions

无。技术生命周期是否显示已经确定为默认隐藏；后续若需要调试模式，可作为独立展示开关，不应重新改变普通用户时间线的默认语义。
