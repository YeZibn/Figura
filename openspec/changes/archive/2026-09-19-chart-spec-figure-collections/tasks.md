## 1. ChartSpec figure/collection 数据模型

- [x] 1.1 在 `src/chartagent/spec/` 增加来源键、布局、覆盖、figure 子项和 collection 的类型定义，保持 `ChartSpec` 作为独立子图语义。
- [x] 1.2 为 `ChartFigure` 和 `ChartSpecCollection` 实现有界的 `to_dict`/`from_dict`、稳定 ID 和结构化 `validate()`，覆盖来源一致性、子图数量、布局和覆盖状态。
- [x] 1.3 更新 spec 导出、digest/身份计算和类型测试，验证单 ChartSpec round-trip 不变，以及 figure/collection round-trip 保留顺序和子图语义。

## 2. assemble_spec 集合装配与工具协议

- [x] 2.1 扩展 `assemble_spec` 的参数 schema，使其兼容现有单图输入，并支持显式 figure/collection 输入及稳定的子图 ID。
- [x] 2.2 实现集合装配的原子校验：逐个复用 ChartSpec 生成校验，再校验精确来源键、系列覆盖、布局上限和结构化错误路径；任一阻断问题不得返回可生成的部分结果。
- [x] 2.3 为集合输出补齐 `kind`、figure/collection ID、source、layout、coverage 和子图摘要，确保返回结果可直接交给 `render_chart`。
- [x] 2.4 更新 `assemble_spec` 的中文工具描述、静态 workflow prompt 和动态结果提示，明确同源多子图必须一次装配、不可静默丢系列、不得手写内部 IR。
- [x] 2.5 增加 assemble_spec 的单图兼容、同源多子图、跨 panel 不合并、遗漏系列和非法子图原子失败测试。

## 3. composite figure 渲染与确定性审计

- [x] 3.1 在 `src/chartagent/tools/chart/rendering.py` 增加单 ChartSpec、ChartFigure 和 ChartSpecCollection 的兼容分派，并按受限 row-major grid 创建最终画布。
- [x] 3.2 复用现有 bar、line、pie、scatter 绘制函数，在每个子图 axes 上保留 `chart_id` 关联，同时执行子图级 artist/data 审计。
- [x] 3.3 增加 figure 级最终 draw、边界/裁剪、尺寸、媒体类型和编码完整性检查，确保审计对象是最终 composite 图片。
- [x] 3.4 生成 figure digest 和有界 artifact metadata，返回一张 composite 图片及其子图、来源、布局、覆盖摘要；保持旧单图 metadata 兼容。
- [x] 3.5 增加两饼图同图、混合图表类型、超限布局、覆盖不完整和单图回归的渲染测试。

## 4. 审核、重试与持久化链路

- [x] 4.1 扩展生成候选和 review context，使 source-linked figure 的一次 VLM 审核同时接收源图、composite、完整 figure 语义和 coverage，并保持无工具约束及明确 JSON 决策格式。
- [x] 4.2 将 figure 级 deterministic gate 接入现有发布状态机：子图、覆盖、布局或编码失败不得发布；VLM 失败时沿用有限修复/重试，并重新生成完整 figure。
- [x] 4.3 扩展 Agent loop、候选幂等键和审计事件，使同一 figure candidate 的重复事件不会产生重复 artifact 或串用其他子图的 review 结果。
- [x] 4.4 扩展 Gateway history/protocol 的可选 metadata，持久化 figure/collection、来源、子图 ID、布局、coverage 和 review 摘要，同时保持历史单图记录可读取。
- [x] 4.5 增加 figure 级审核通过、子图失败阻断、coverage 不完整阻断、review 重试幂等、超时/耗尽和旧单图候选回归测试。

## 5. 前端结果展示

- [x] 5.1 扩展前端生成图表协议类型和事件归并逻辑，使一个 composite figure 只对应一个最终展示 artifact，并保留 figure/子图元数据。
- [x] 5.2 在生成结果详情中展示来源、子图 ID、布局、coverage 和 review 状态；继续通过现有 preview route 展示一张 composite 图片，不引入子图编辑器。
- [x] 5.3 完成前端类型检查、生产构建和 smoke 测试，确认旧单图和新 composite 结果都能展示。

## 6. 端到端验证与交付

- [x] 6.1 增加或复用同一 panel 含 Q1/Q2 多系列的 dashboard fixture，验证一次主流程能够生成一个包含两个子图的 composite artifact。
- [x] 6.2 使用 test3 类真实运行验证：拆解后的同源 panel 被复用、各子图使用正确的小 panel 语义、最终输出覆盖全部系列且只触发一次 figure 级 VLM review。
- [x] 6.3 运行 `conda run -n agent python -m pytest -q`、前端 `npm run build` 和 `npm run smoke`，并执行 `git diff --check` 与严格 OpenSpec 校验。
- [x] 6.4 更新相关主规格或通过 sync 流程同步已实现的 figure/collection 和 composite generation 契约，记录兼容性与回滚说明。
