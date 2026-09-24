## 1. 用户时间线投影

- [x] 1.1 定义面向展示的 timeline item 类型和可见事件分类，明确技术生命周期事件只保留在内部 projection。
- [x] 1.2 实现从 canonical events 和现有 decision/process projection 生成扁平用户时间线的逻辑，保留业务步骤的 sequence 顺序和状态。
- [x] 1.3 将 `tool_call`、`tool_result`、`visual_observation` 按 call id 合并，并处理旧事件、缺失 call id、重复 sequence 和重复 transition。
- [x] 1.4 将隐藏技术事件中的结构化 failure context 提升到可见错误或终态步骤，确保过滤不会丢失失败原因。

## 2. 普通运行展示

- [x] 2.1 重构运行时间线组件，使其渲染扁平用户时间线，不再把 process、turn、operation 或 legacy unit 作为顶层嵌套卡片。
- [x] 2.2 隐藏模型轮次开始/结束、operation 保存、run 启动和 final answer 重复记录；保留运行摘要、业务步骤、审核状态和终态错误。
- [x] 2.3 将工具步骤、测量、审核、生成、发布和恢复阻塞整理为稳定的中文展示，默认不显示 sequence、内部 unit id 和原始事件数组。
- [x] 2.4 保留工具参数、结果、观察图片、详情资源和原始安全记录的按需展开能力，确保截断/不可用状态仍可解释。
- [x] 2.5 调整运行时间线样式，移除套娃容器的视觉层级，统一扁平步骤、状态标记、错误提示和窄窗口布局。

## 3. 评测工作台复用

- [x] 3.1 让评测只读视图复用普通运行的用户时间线 projection、工具合并、错误摘要和详情展开逻辑。
- [x] 3.2 保留 evaluation/case/report/evidence 上下文以及只读约束，不重复显示生成图或重新解释 execution history。
- [x] 3.3 验证普通运行和评测对于同一 event history 的可见步骤、顺序、状态和错误内容一致。

## 4. 回归验证

- [x] 4.1 增加 test5 风格回放夹具和期望可见步骤，覆盖模型 lifecycle、operation 保存、工具调用、审核、失败和终态。
- [x] 4.2 增加前端 timeline 行为 smoke/regression，验证技术事件隐藏、工具合并、观察附着、错误提升、旧事件兼容和重复事件去重。
- [x] 4.3 更新前端 UI contract smoke 与类型/构建检查，覆盖普通运行和评测共用同一 projection 的入口。
- [x] 4.4 运行 `git diff --check`、`conda run -n agent python -m pytest -q`、`frontend` 下的 `npm run build` 与 `npm run smoke`，确认不改变后端运行语义。
