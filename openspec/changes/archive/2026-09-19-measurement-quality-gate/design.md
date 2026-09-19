## Context

现有四类图表传感器已经返回 chart-specific geometry、`confidence`、`warnings` 和 source-sized overlay，Agent 也会把工具观察写入当前 run 的消息、artifact index 和 checkpoint。但这些字段目前没有统一的生命周期，也没有记录某次测量是否可以作为 ChartSpec 的确定性来源。

本 change 需要跨越传感器、Agent run 状态、`assemble_spec` 和 prompt/测试契约。它只建立测量证据的质量基础设施；具体的 TargetRegion 裁剪、策略化重测和 VLM measurement review 由后续 change 实现。

## Goals / Non-Goals

**Goals:**

- 为所有图表测量提供统一、有限且可序列化的质量 envelope。
- 让每次测量都能关联到精确的附件、面板、工具和 attempt lineage。
- 把现有几何、标定、覆盖、关联和 overlay 检查汇总成代码拥有的质量门禁。
- 让源图测量结果在进入 `assemble_spec` 前必须通过 accepted 状态检查。
- 保持不使用测量工具时的直接 ChartSpec 装配，以及现有 observation、checkpoint、恢复和单图兼容行为。

**Non-Goals:**

- 不在本 change 中实现任意局部 TargetRegion、context margin 或具体重测算法。
- 不在本 change 中引入 SAM、OCR 或新的图像处理依赖。
- 不把确定性 accepted 状态解释为源图事实已经经过 VLM 视觉复核。
- 不移除现有四个 chart sensor，也不新增一个必须由模型主动调用的独立 `validate_measurement` 工具。
- 不改变生成图的现有 deterministic audit 和生成后 VLM review gate。

## Decisions

### 1. 使用共享质量 envelope，而不是让每个传感器各自定义状态

在不改变 `bars`、`series`、`sectors`、`points` 等 chart-specific 字段的前提下，为测量结果增加统一的质量部分，概念上包含：

- `status`：`provisional`、`accepted`、`remeasure_required`、`partial`、`unsupported` 或 `failed`；
- `attempt`：稳定 attempt ID、父 attempt、工具名和策略摘要；
- `source`：attachment、panel 和局部/源坐标范围摘要；
- `quality`：有界 confidence、检查项、issues 和 warnings；
- `evidence`：overlay 或其他受控视觉证据引用。

图表传感器继续维护自己的数据结构，共享 envelope 只负责生命周期、归因和质量语义。这样可以避免四个工具的字段继续分叉，也不会把所有 chart-specific 数据压扁成通用格式。

### 2. 以 run-scoped MeasurementSession 为主，并纳入 checkpoint

每个当前 run 按 `attachment_id + panel_id` 建立一个有界的 MeasurementSession。session 保存当前有效 attempt、历史 attempt 摘要、冲突和未解决问题；每个 attempt 保存输入范围、tool、结果摘要和质量状态，不保存原始图像字节或 provider payload。

session 随 Agent checkpoint 一起序列化，并在恢复时校验 attachment、panel 和可选 source digest。恢复只允许重新使用同一来源键的 accepted attempt，过期、来源不匹配或状态不确定的 attempt 必须降级为 provisional/unknown，不得跨 panel 复用。

选择 run-scoped 而不是立即引入全局数据库，是因为测量证据当前服务于一次图表恢复 run；checkpoint 已经是现有恢复边界，可以减少迁移面和跨运行污染风险。后续若需要跨 run 复用，再单独设计持久化证据仓库。

### 3. accepted 只代表代码侧质量通过

质量审计由共享层执行，至少汇总范围有效性、几何支持、坐标/基准线标定、数据覆盖、系列/标签关联和 overlay 完整性。阻断问题统一进入结构化 issue，包含 code、location、severity 和 bounded message。

`accepted` 的含义是“满足当前确定性传感器的使用契约”，不是“VLM 已经确认所有源图语义”。因此 accepted 结果仍保留 warnings 和 confidence；后续 VLM measurement review 可以在不改变本 change 状态机的情况下增加更高一级的语义复核。

这种定义比直接把 confidence 当阈值更可靠：confidence 是传感器的估计，status 是代码根据多个检查得出的使用资格。

### 4. 将门禁放在 assemble_spec 边界，不增加独立模型工具

测量工具返回的 server-issued evidence/attempt reference 进入当前 Agent 的 observation 和 session。源图装配请求如果声明使用测量证据，`assemble_spec` 必须解析并校验该引用：来源键匹配、attempt 存在、状态为 accepted、没有未解决的 blocking issue。

门禁失败时返回结构化错误和 bounded recovery action，阻止返回可被误认为已确认的 ChartSpec。这样即使模型没有主动调用一个外置 validate 工具，也不能跳过检查。

没有使用任何测量工具的直接视觉组装不要求伪造 measurement reference，继续走现有单 ChartSpec 兼容路径；生成后的结构校验和图表审核仍然照常执行。

### 5. 保留 legacy result，但把它降级为 provisional

现有直接调用传感器的测试、内部调用或自定义工具可能只返回旧格式。共享归一化层在兼容读取时可以把缺少质量 envelope 的结果包装为 provisional/unknown，并保留原始 chart-specific 字段；它们不能凭借 legacy 形态直接通过 source-derived assembly gate。

这样可以分阶段迁移四个传感器，而不会破坏旧的 JSON observation 或让未知质量结果被误认为 accepted。

### 6. 未来的局部重测使用同一 session，不另起一套证据模型

本 change 只定义 session、attempt、status 和 issue 的稳定边界。后续 TargetRegion change 可以把 `target_region`、`context_margin` 和 `strategy` 放入新的 attempt，并通过父 attempt 与全局结果关联；局部结果只能更新明确目标或产生冲突，不能覆盖整个 session 的来源和质量历史。

## Risks / Trade-offs

- **[门禁增加一次结构化状态检查]** → 只在使用测量证据的 `assemble_spec` 路径执行；直接视觉组装保持兼容，并将 payload 控制在有界摘要内。
- **[accepted 仍可能存在语义误判]** → 明确 accepted 仅表示确定性质量通过；保留 warnings/overlay，并在后续 change 加入按 panel 聚合的 VLM measurement review。
- **[checkpoint 变大]** → 只保存 attempt 摘要、issues、source refs 和有限历史，不保存图片字节；历史记录按 session 和 attempt 数量封顶。
- **[旧工具结果缺少 envelope]** → 兼容层统一降级为 provisional/unknown，允许继续观察但阻止其直接作为确定性测量来源。
- **[来源引用过期或串 panel]** → 引用绑定 attachment、panel、run/session 和 attempt digest；恢复时执行来源匹配，失败则要求重新观察。
- **[不同图表的质量阈值不一致]** → 共享状态和 issue 契约保持一致，具体阈值由各传感器已有证据和 fixture 测试维护，不在本 change 强行统一数值阈值。

## Migration Plan

1. 增加共享 measurement envelope、session/attempt 数据模型和有界序列化能力，先覆盖 observation、artifact index 与 checkpoint。
2. 将四个传感器的现有 warnings、confidence、scope 和 overlay 适配到共享 envelope，并为缺失 envelope 的 legacy result 提供 provisional fallback。
3. 接入确定性质量审计，明确 accepted、partial、unsupported 和 blocking issue 的转换规则。
4. 扩展 `assemble_spec` 的源图测量引用和门禁错误；保留无测量引用的直接单图兼容路径。
5. 更新 workflow、动态 artifact prompt、恢复逻辑和回归测试，验证未接受测量不能进入确定性 ChartSpec。
6. 若需要回滚，关闭 source-derived measurement gate 的强制发布路径并继续读取旧 ChartSpec/observation；session 和 attempt 是附加元数据，不执行破坏性数据迁移。

## Open Questions

- 后续 VLM measurement review 是否对所有 accepted session 执行，还是只对存在 blocking/高风险 issue 的 session 执行，由 TargetRegion/retry change 决定。
