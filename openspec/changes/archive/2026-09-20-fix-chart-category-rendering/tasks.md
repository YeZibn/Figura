## 1. ChartSpec 类别轴契约

- [x] 1.1 在 `ChartSpec.validate()` 中补充 `axes.x.categories` 与 cartesian 数据点 x 位置的一致性校验，覆盖空标签、重复标签、位置数量不匹配和无法映射等结构化错误。
- [x] 1.2 补充 `tests/test_chartspec.py`，验证带类别的 line ChartSpec 序列化/反序列化后保持顺序，非法类别映射被拒绝，未声明类别的数值 line/scatter 仍保持兼容。
- [x] 1.3 扩展 `assemble_spec` 的单图和 figure child 输入，保留可选的有序 `x_categories` 到 `axes.x.categories`，并更新工具 schema/描述以让主流程可发现该字段。

## 2. 折线图类别渲染与审计

- [x] 2.1 在 `src/chartagent/tools/chart/rendering.py` 中建立有界的类别位置准备逻辑，区分内部 x 坐标、类别文本和轴标题，并让带类别的 line 使用显式 tick 位置/文本。
- [x] 2.2 保持多系列折线共享类别位置，保留原始 y 值、系列身份和点顺序；没有类别域时继续使用数值横轴，避免影响现有 bar/scatter 路径。
- [x] 2.3 扩展折线确定性 artist fidelity 审计，验证类别刻度数量、文本、顺序以及各系列 x 位置映射；发现缺失或错位时返回可定位失败并阻止发布。

## 3. 离线生成回归

- [x] 3.1 在 `tests/test_chart_generation.py` 中增加带 `Jan`–`Jul` 类别的单系列和多系列 line 渲染测试，直接检查最终轴刻度文本和位置，而不是只检查 PNG 能否编码。
- [x] 3.2 增加数值型 line、已有 grouped bar、密集/旋转类别标签和非法类别映射回归，确认兼容性、布局边界和错误门禁不回归。
- [x] 3.3 增加 `assemble_spec` 的 line/scatter 类别传递、figure child 隔离和缺失字段兼容测试。
- [x] 3.4 重新运行相关 pytest、完整 pytest、`openspec validate --strict` 和 `git diff --check`，修复由本 change 引起的失败。

## 4. 真实评测复验

- [x] 4.1 使用现有 `bar_line_dashboard` 评测入口重新运行一次真实 bar+line 链路，不改变 provider、样本或评测规格。
- [x] 4.2 检查评测 bundle 中 Monthly Orders 的图片、ChartSpec、确定性审计和 VLM 结果，确认类别轴显示 `Jan`–`Jul`，并记录仍存在的非本 change 问题。
