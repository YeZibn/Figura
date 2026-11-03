# 03 图表修改

**状态：材料已准备；优先运行。**

## 评测目标

检查 Agent 能否在多轮修改中保留原图数据，正确合并最终要求，并丢弃后来明确撤销的临时方案。

## Agent 输入

只附加 `input/quarterly-regional-sales.png`。该文件复制自 `tests/fixtures/figura_measurement/images/single/bar.png`。

SHA-256：

`79f04312fcd4430f41f4c53b9d808d2c7e3b094c630d8b0745389ea32eca9e36`

标准数据来源为 `tests/fixtures/figura_measurement/cases/bar.json`，不得附加给 Agent。

## 运行材料

- 固定三轮提示：`conversation.md`
- 标准答案：`answer-key.md`
- 验收项：`scorecard.md`

压缩组和基线组使用同一张输入图及相同三轮提示。
