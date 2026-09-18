## Why

当前 Dashboard 拆解以 OCR 和确定性亮度/空白线索发现候选 panel，再让 SAM 在候选框内细化。对于多图表图片，这种候选拓扑可能在进入 SAM 之前就已经错误，例如把一个完整图表卡片拆成多个区域；而 OCR 文字归属也不能代表图表区域本身。应该让多模态模型先根据视觉语义提出完整分区，再让 SAM 负责边界细化。

## What Changes

- **BREAKING** 调整 `decompose_chart_image` 的分区输入契约：复杂图片由 VLM 提供有名称的语义区域预测，包括角色、可选图表类型和归一化 bbox。
- 移除 OCR 作为 panel 发现、panel 关联和分割校验的前置依赖；本 change 不在拆分阶段执行全图 OCR 或局部 OCR。
- 通过 VLM 提出的 box/point 调用 SAM，对每个语义区域生成 mask、polygon、边界和置信度。
- 对 VLM 预测和 SAM 结果执行边界、尺寸、重叠、碎片化和一致性校验；SAM 失败时保留 VLM bbox 作为 partial 结果。
- 按稳定区域 ID 和安全 slug 生成命名 crop，并通过受管控的视觉资源引用保存，供后续局部图表分析使用。
- 让后续柱状图、折线图、饼图和散点图传感器能够消费 panel 的 crop 引用和源图坐标，而不是重新扫描整张图片。
- 保留独立的 `extract_text` 能力，后续仅在数值或小尺寸文字确实需要时按需使用；它不再是 Dashboard 分割的组成步骤。
- 保留部分结果、降级状态、警告和源图坐标映射，不因单个区域的 SAM 失败而丢弃其他区域。

## Capabilities

### New Capabilities

- `dashboard-decomposition`: 接收 VLM 提出的语义分区，使用 SAM 细化区域，生成带稳定名称和可复用 crop 引用的局部图表区域。

### Modified Capabilities

<!-- Existing single-chart observation requirements remain unchanged; panel crop
     handoff is specified as part of the new dashboard-decomposition contract. -->

## Impact

- 重写 Dashboard 拆解工具的输入、输出和模型提示词契约，但保留 `decompose_chart_image` 的稳定工具名。
- 调整 `dashboard` observation、SAM segmentation backend、视觉观察资源持久化和 panel-to-sensor handoff。
- 移除当前拆解实现中的 OCR-first candidate discovery、OCR association 和 local OCR retry 路径。
- 增加 VLM 区域提案校验、命名 crop 生成、资源生命周期和大小限制。
- 现有 `extract_text`、`inspect_chart_layout`、柱状图、折线图、饼图和散点图工具保持独立，可继续按需调用。
- 增加覆盖语义分区、SAM 细化、crop 资源引用、降级行为和后续传感器消费链路的测试。
