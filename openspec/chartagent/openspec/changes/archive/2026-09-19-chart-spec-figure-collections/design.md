## Context

当前系统已经把 `ChartSpec` 作为单图的语义 IR，并由 `assemble_spec` 统一完成生成前校验；`render_chart`、候选审核和 artifact 持久化也都以单个 ChartSpec 为中心。现有结果协议能够展示多张图片，但无法表达“多张子图属于同一个来源且应当合成为一张最终图”。本设计落实 proposal 和规格增量中的 figure/collection 语义，同时保留单图路径。

## Goals / Non-Goals

**Goals:**

- 建立 `ChartSpec`、`ChartFigure`、`ChartSpecCollection` 三层边界：单图语义、同源最终画布、一次运行的多来源批次。
- 让同一精确来源键 `attachment_id + panel_id` 下的多个子图只生成一个 composite artifact。
- 让来源系列覆盖、子图校验、布局校验和审核成为同一个可追溯的 figure 级生命周期。
- 保持现有单 ChartSpec 的输入、输出和前端 artifact 兼容。
- 复用现有单图渲染器和审核状态机，减少第二套生成路径。

**Non-Goals:**

- 不在本 change 中修复 `measure_bars` 的基准线、旋转或横向测量算法。
- 不把普通饼图扩展为“一个饼图同时表达多个系列”；多系列饼图通过多个独立子图表达。
- 不实现任意坐标、拖拽或自由排版的 dashboard 编辑器。
- 不改变 OCR、SAM 或 VLM 的数值提取职责，也不引入新的视觉模型依赖。

## Decisions

### 1. 采用三层语义模型

新增以下可序列化模型，字段命名与协议使用 snake_case，输出到前端时沿用现有 camelCase 映射：

- `ChartSpec`：现有单个图表语义，不增加“同图其他系列”的隐式字段。
- `ChartFigure`：`figure_id`、`source`、`layout`、`charts`、`coverage`。`source` 至少包含 `attachment_id` 和 `panel_id`；`charts` 中每项包含稳定的 `chart_id`、可选显示标题和一个完整 `ChartSpec`。
- `ChartSpecCollection`：`collection_id` 和有序 `figures`，用于一次运行中的多个来源面板。

figure 的最小 JSON 形状为：

```json
{
  "kind": "chart_figure",
  "figure_id": "figure_...",
  "source": {
    "attachment_id": "attachment_...",
    "panel_id": "panel_..."
  },
  "layout": {
    "type": "grid",
    "columns": 2
  },
  "charts": [
    {"chart_id": "q1-2024", "spec": {"metadata": {}, "dataset": []}},
    {"chart_id": "q2-2024", "spec": {"metadata": {}, "dataset": []}}
  ],
  "coverage": {
    "source_series": ["Q1 2024", "Q2 2024"],
    "represented_series": ["Q1 2024", "Q2 2024"],
    "omitted_series": [],
    "status": "complete"
  }
}
```

理由：把“数据是什么”和“最后怎么放在一张图上”分开，可以避免重复类别被塞进单个 pie 的结构错误，也让单子图重试不必改变 figure 的来源边界。figure 和 collection 的稳定 ID 用于审核、幂等和结果追踪，不使用本地路径或模型生成的长文本作为身份。

备选方案是继续返回多张独立图片，由前端自行拼接；该方案无法保证服务端审核的是最终画布，也无法可靠传递来源覆盖，因此不采用。另一备选是扩展 ChartSpec 直接携带多个 series panel；这会让单图 IR 同时承担布局和集合职责，且破坏 pie 的语义边界，也不采用。

### 2. 让 `assemble_spec` 成为唯一的集合装配与校验入口

保留现有单图参数作为兼容分支，并为工具增加显式的 figure/collection 输入分支。集合分支先逐项构建并执行现有 `ChartSpec` 生成校验，再执行来源、覆盖和布局校验；任何阻断性问题都以 `collection.figure[...].charts[...]` 形式返回并整体失败。

装配规则如下：

1. 一个 figure 的所有子图必须使用相同的 `attachment_id` 和 `panel_id`。
2. collection 可以包含多个 figure，但不同来源不得自动合并。
3. `source_series`、`represented_series` 和 `omitted_series` 由显式输入或已收集的来源证据形成；`omitted_series` 非空时不能标记为 `complete`。
4. figure 的布局只接受有限的 grid 类型，并限制子图数量、列数和最终尺寸。
5. 装配成功返回完整 figure/collection JSON；失败不返回可交给 `render_chart` 的部分 spec。

这样做保留了“模型先观察、再一次性组装、失败后修正再组装”的现有 prompt 约定；模型不需要手写内部 IR，也不能绕过统一校验直接调用渲染器。

### 3. 在渲染层复用单图绘制器，增加 figure 画布编排

`render_chart` 根据输入 kind 分派：单 ChartSpec 继续使用现有单图路径；ChartFigure 在一个 Matplotlib figure 中按确定性的 row-major grid 创建多个 axes，然后对每个子图调用已有 bar、line、pie、scatter 绘制函数和单图审计逻辑。

figure 级处理包括：

- 根据 `columns` 和子图数量计算行数，统一应用最大列数、子图数、画布宽高和字节限制。
- 给每个 axes 保存 `chart_id`，审计时按子图定位 artist 数量、数据值、标题、轴标签和裁剪问题。
- figure 级 `tight_layout`/边界检查完成后再编码图片，确保检查的是最终 composite，而不是未合成的子图。
- 只返回一张图片和一份 figure artifact metadata；子图的 digest、类型、标题和点数放入有界 metadata，避免把子图渲染为多个最终 artifact。
- figure digest 由规范化后的 figure JSON 计算，单 ChartSpec digest 继续按原规则计算。

不把子图先编码成 PNG 再二次拼接，因为那会丢失统一字体、边界审计和最终画布的语义定位；直接共享最终 Matplotlib figure 才能在同一层完成质量检查。

### 4. 将审核提升为 figure 级，但保持一次 VLM 调用

source-linked composite 只触发一次无工具 VLM 审核。审核输入包含源图、最终 composite、完整 figure JSON、每个子图 ChartSpec 和 coverage；审核输出仍使用现有结构化的 decision、confidence、checks、issues 和 publicationStatus。VLM 不调用 OCR、CV、测量、布局或 review 工具。

审核前由代码完成所有确定性检查：子图 ChartSpec、覆盖状态、子图绘制审计、最终画布裁剪、编码完整性和尺寸限制。VLM 负责源图与最终组合结果的语义对照，重点检查子图是否齐全、系列是否归属正确、类别和值是否被误放，以及最终布局是否导致关键内容不可读。

若任一子图或 coverage 失败，直接进入可修复的非发布状态；若 VLM 失败，则沿用现有有限修复/重试状态，但修复输入必须重新生成整个 figure candidate，不能只发布其中一个“看起来正常”的子图。

### 5. 通过现有 artifact 生命周期承载集合元数据

candidate、review 和 published artifact 继续使用现有 opaque reference、状态和幂等键。新增的 figure/collection 信息放入受限的结构化 metadata：`figureId`、`collectionId`、`source`、`childChartIds`、`layout`、`coverage` 和子图摘要。持久化优先复用现有 JSON/事件字段，不把本地路径、图片字节或 provider 原始 payload 写入协议。

前端仍按一个 generated chart artifact 展示一张 composite 预览；详情面板可以显示子图 ID、来源、覆盖和审核状态，但本 change 不要求前端提供子图编辑器。已有没有 figure 元数据的单图记录按旧字段读取。

### 6. 以兼容分派控制迁移风险

输入没有 `kind`/figure/collection 字段时保持现有单图行为；显式 figure 或 collection 输入才进入新路径。新路径初期不改动单图渲染函数的语义和现有数据库列，先通过统一序列化、artifact metadata 和回归测试验证；如果复合渲染存在问题，可暂时关闭集合分支而不影响既有单图生成和历史 artifact 读取。

## Risks / Trade-offs

- [Risk] 同源子图数量增加后，单张 composite 可能变得拥挤或超过尺寸上限 → [Mitigation] 限制子图数、列数和画布尺寸，执行最终画布边界审计，并返回明确的布局失败。
- [Risk] 来源系列名称在理解阶段不稳定，coverage 可能因为命名差异误判 → [Mitigation] 使用规范化后的系列键参与覆盖计算，同时保留原始显示名称；无法确定时标记为不完整，不静默通过。
- [Risk] figure 级一次 VLM 审核的上下文更大，可能增加输入成本或超出模型上下文 → [Mitigation] 传递有界的子图摘要和完整但受限的 ChartSpec，限制 figure 子图数，并在超限时返回可修复错误。
- [Risk] 旧客户端只认识单图 artifact 字段 → [Mitigation] 保持 `artifactKind`、preview route、媒体类型和单图字段不变，新增字段均为可选，旧客户端仍可展示一张 composite 图片。
- [Risk] 子图独立审计通过但最终合成后发生标题或标签裁剪 → [Mitigation] figure 级重新 draw 后执行最终边界检查，最终检查失败时禁止发布。

## Migration Plan

1. 先落地模型、序列化、集合装配和单元测试，确认旧 ChartSpec round-trip 与单图工具契约不变。
2. 再接入 composite renderer、figure digest、artifact metadata 和 figure 级 deterministic audit。
3. 最后接入 source-linked VLM review、Gateway 持久化和前端展示，并用同一面板的 Q1/Q2 多子图 fixture 做端到端验证。
4. 回滚时停止生成新的 figure/collection 请求，保留单图分支和已有 artifact 读取；已经落盘的复合 artifact 仍按其 opaque reference 和图片媒体类型读取，不执行破坏性迁移。
