## Why

在真实的 `test2` 链路中，第一次运行得到的 dashboard 分区只存在于当前 Agent 运行的内存中，后续运行无法复用，于是重复拆解；OCR 和几何测量也没有统一消费局部面板，仍可能读取整张 dashboard。与此同时，源附件绑定和审核失败恢复没有形成闭环，审核失败会直接终止运行，而不是让主 Agent 修正 ChartSpec 后重新生成。

现在需要把“分区结果可复用、分析范围可追溯、审核失败可恢复”统一为跨运行的基础设施，确保复杂图片的后续请求真正围绕已识别的 panel 工作。

## What Changes

- 增加持久化的 PanelHandoff 注册表，按 session、attachment 内容哈希和面板语义保存稳定的 `panel_id`、源图区域、局部范围、坐标变换、版本和置信度。
- 为后续运行建立 source context 恢复和 panel reuse-first 策略；有效面板优先复用，只有源图变化、面板失效或用户明确要求时才重新拆解。
- 增加统一的 PanelScopeResolver，让 OCR、柱状图、折线图、饼图和散点图测量都通过同一面板引用进行物理裁剪，并同时保留局部坐标与源图坐标。
- 扩展 OCR 和图表传感器的输入契约，使它们不会在已有面板任务中默认扫描整张 dashboard。
- 将源附件绑定从当前 run 的临时参数提升为 session 级可验证上下文；校验 attachment 所属 session、内容哈希和可访问性。
- 将审核失败分为源绑定、审核运行时、语义图表、渲染安全和重试耗尽等类型，并让可恢复失败回到主 Agent 修正 ChartSpec、重新 assemble/render/review。
- 为候选图建立有限重试和 lineage，旧候选保持未发布状态，新候选只有通过审核后才能发布。
- 让 checkpoint、Gateway 和前端保留活动源图、面板引用、审核恢复状态和候选关联，支持断点继续与页面重连。
- 更新运行时 Prompt，明确“先复用面板、局部分析、审核失败必须修复”的行为；关键约束由 runtime 和工具层强制执行，不依赖 Prompt 记忆。

## Capabilities

### New Capabilities

- `panel-handoff-registry`: 提供跨运行、可校验、带版本的面板注册与复用能力。

### Modified Capabilities

- `dashboard-decomposition`: 拆解结果需要产生稳定 PanelHandoff，并支持幂等复用和失效处理。
- `chart-layout-context`: 布局上下文需要解析为统一的 PanelScope，并提供局部图与源图坐标变换。
- `chart-understanding`: OCR 和四类图表传感器需要消费 panel scope，而不是隐式扫描整图。
- `attachment-access`: 附件需要支持 session 级 source context 恢复、哈希校验和安全绑定。
- `agent-session-memory`: 会话需要持久化活动源图和面板注册关系，而不仅是文本历史。
- `run-checkpoint-recovery`: checkpoint 需要保存可恢复的 source/panel 引用和审核修复状态。
- `agent-loop`: 主 Agent 需要消费审核诊断并生成修正候选，不能在可恢复审核失败时直接结束。
- `chart-generation`: 候选图需要携带 source/panel 归因和候选 lineage，审核失败时允许有限修正但禁止绕过发布门禁。
- `vlm-chart-review`: 审核需要提供结构化失败诊断、源绑定预检和有限重试语义。
- `attachment-workspace`: 前端需要保留活动源图，区分本次新选择和会话当前附件。
- `desktop-client`: 前端需要展示 panel 复用、局部分析、审核修复和最终失败状态。

## Impact

- 影响 `src/chartagent/agent`、`src/chartagent/gateway`、`src/chartagent/memory`、`src/chartagent/review` 和 `src/chartagent/tools/chart` 的运行时、持久化及工具输入契约。
- 影响 Gateway 的 session/run/checkpoint 数据结构，以及前端运行请求、附件状态和执行轨迹展示。
- 需要新增持久化面板数据和局部 crop/观察资源的生命周期管理，但不把本地路径或原始图像字节暴露给模型或日志。
- 需要使用 `conda run -n agent` 执行 Python 测试，并保留 RapidOCR 在 `agent` 环境中的现有运行约定。
- 默认链路不重新引入 SAM；SAM 继续作为可选的边界细化能力。
