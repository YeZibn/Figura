## Context

当前项目已经有 `ChartSpec`、`assemble_spec`、`validate_spec` 和统一的工具结果/视觉观察边界，但没有 `ChartSpec` 到图像 artifact 的实现。Gateway 已经能够管理运行事件和生成视觉资源，React 前端也能展示运行历史与受授权的图片资源。这个 change 延续现有边界，不引入 Tauri 工作流。

## Goals / Non-Goals

**Goals:**

- 在 Python Agent 侧提供四种基础图表的确定性渲染。
- 复用现有 `ChartSpec`，不让模型直接拼接像素或不受约束的图像数据。
- 让生成图表同时能够作为模型视觉证据和用户可下载的持久化 artifact。
- 让 Gateway、运行历史和 React 前端区分生成图表与临时观察图像。
- 对输入、输出尺寸、字节数和元数据进行统一限制。

**Non-Goals:**

- 不实现自由主题编辑、拖拽编辑或在线图表编辑器。
- 不在本阶段扩展 `ChartSpec` 的样式 schema。
- 不实现堆叠柱状图、气泡图、热力图或动画图表的生成布局。
- 不把前端图表库作为第二套权威渲染器。

## Decisions

### D1: Python 侧使用唯一的确定性渲染器

采用 Python 的 headless Matplotlib 渲染 `ChartSpec`，输出 PNG，并将其封装成现有 `GeneratedImage`/`ToolResult`。Matplotlib 已经是项目开发依赖，能够覆盖坐标轴、图例、饼图标签、散点系列和无窗口运行。

前端 ECharts 或浏览器 SVG 没有被选为权威渲染源：它们适合交互展示，但会使 Agent 自验证、CLI 输出和 Gateway 输出拥有不同的绘图实现；手写 SVG 则会重复实现刻度、布局和文字测量。未来可以在不改变 `ChartSpec` 和 artifact 契约的情况下增加交互预览，但不作为本阶段的生成结果。

### D2: 渲染工具复用 ChartSpec 和现有工具结果边界

新增 `render_chart` 工具接收 ChartSpec 字典，先执行 `ChartSpec.from_dict`、结构校验和生成侧约束校验，再创建图像。成功时返回结构化生成元数据和 `GeneratedImage`；失败时返回结构化错误，不让 Matplotlib 异常穿透 Agent 循环。

默认布局按图表类型选择：bar 使用单系列或按 `series` 分组的 grouped bar，line 按 `series` 分组绘制折线，pie 要求非负且总和大于零的 category/value 数据，scatter 按 `series` 分组绘制 x/y 点。没有在 `ChartSpec` 中表达的堆叠方式、颜色、点大小和主题不在 MVP 中猜测。

### D3: 生成图表使用独立的 artifact kind

生成图表在 Gateway 侧使用 `generated_chart` artifact kind，并通过独立的 opaque artifact ID 关联 session、run 和事件。模型观察资源仍保留原有 observation 语义；当 Agent 需要自验证时可以消费同一生成结果的受控视觉副本，但前端将其标记为用户生成物。

渲染器只负责产生有界的内存图像。Gateway 的运行级 artifact sink 负责分配 opaque ID、写入受控存储、记录媒体类型/字节数/尺寸/图表类型，并把 artifact 元数据写入运行事件。事件 JSON 只传元数据和引用，不传图片 bytes 或本地路径。

### D4: 复用现有授权和生命周期模型

生成 artifact 的读取沿用 session/run 所有权校验、配置的保留期限和会话删除级联。前端只通过 Gateway 的受授权资源读取预览和下载；它不接触 Python 文件路径，也不把 artifact bytes 写入会话 transcript。

artifact 过期、删除或授权失败时，Gateway 返回结构化 bounded error，前端保留标题和失败状态。旧版本客户端忽略未知生成事件时，已有运行历史和普通视觉观察仍保持可读。

### D5: 默认边界和输出限制

默认输出尺寸为 1200x800，最大尺寸为 2400x1600，单个输出沿用 10 MiB 图像上限；具体限制集中在渲染配置中并可由测试覆盖。字体、布局和颜色使用稳定默认主题，测试验证数据点数量、系列标识、标签和输出尺寸，而不依赖每个像素的脆弱快照。

## Risks / Trade-offs

- [Matplotlib 增加运行时依赖和启动成本] → 将依赖放入 `agent` 环境的正式运行依赖，使用 Agg 后端并在 Gateway 健康检查/测试中暴露初始化失败；不影响没有调用生成工具的普通文本运行。
- [不同机器的字体导致视觉像素差异] → 使用无窗口后端、稳定默认字体和语义级测试，不将完整 PNG 字节作为唯一断言。
- [ChartSpec 当前不能表达所有布局意图] → MVP 只生成明确支持的 grouped/single 语义；对堆叠、负饼图、空数据等情况返回结构化错误，不静默猜测。
- [生成 artifact 与模型观察可能重复存储] → 在 artifact sink 中使用同一受控 bytes 和关联 ID，事件只保存引用；清理统一由 artifact retention 和 session cascade 完成。
- [模型生成了格式正确但语义不合理的 ChartSpec] → 渲染前执行结构与图表类型约束，渲染后允许 Agent 读取视觉结果，但不把自验证设为隐藏的强制循环。

## Migration Plan

1. 将 Matplotlib 从开发依赖提升为 `agent` 环境的运行依赖，并增加 headless 初始化检查。
2. 以兼容方式增加 generated-chart artifact 元数据、运行事件和受授权读取能力；已有 observation artifact 不迁移、不改变语义。
3. 注册 `render_chart`，默认只在 ChartSpec 校验成功后生成；若渲染依赖不可用，返回 bounded `generation_unavailable` 错误。
4. 增加 React 协议类型、运行时间线卡片、预览和下载行为；旧的 mock 模式提供确定性生成示例或明确 unavailable 状态。
5. 若需要回滚，停止注册生成工具并保留已有 artifact 清理逻辑；历史 session、理解工具和普通运行事件无需回滚迁移。
