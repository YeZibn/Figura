# 01 图表分析

**状态：材料已准备；按当前计划暂缓运行。**

## 评测目标

检查 Agent 能否从一张复合图表中识别面板、坐标轴、系列与数据，并在后续轮次准确找回早先提取的值。此项只评估读图和分析，不要求重绘，避免与图表构建混为一项。

## Agent 输入

只附加 `input/bar_line_dashboard.png`。图像 SHA-256：

`b6b6105d739d1a0399295fd75286f27ac8965644423a0533de814f8aaecb9e00`

仓库源文件为 `tests/fixtures/bar_line_evaluation/bar_line_dashboard.png`。标准答案来自 `tests/fixtures/bar_line_evaluation/ground_truth.json`，不要附加标准答案文件。

## 运行材料

- 固定三轮提示：`conversation.md`
- 标准答案：`answer-key.md`
- 验收项：`scorecard.md`

每轮都必须在同一个实验会话中完成。不要把标准答案或评分表粘贴给 Agent。
