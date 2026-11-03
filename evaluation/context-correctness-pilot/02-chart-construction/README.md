# 02 图表构建

**状态：材料已准备；优先运行。**

## 评测目标

检查 Agent 能否把分轮给出的结构化数据和绘图要求保留到最终 ChartSpec 与渲染产物中。此任务从结构化数据开始，不需要从图像测量数据。

## Agent 输入

第 1 轮附加 `input/dataset.json`，之后不重复附加。文件 SHA-256：

`af5b21aa1e02c3de92a6e929d63caa02bec2ab60446c5b22b1b60abfb7a0b582`

数据由合成样例组成。标准图表合同与验收规则见本目录 `answer-key.md` 和 `scorecard.md`，不要提供给 Agent。

## 运行材料

- 固定三轮提示：`conversation.md`
- 输入数据：`input/dataset.json`
- 标准答案：`answer-key.md`
- 验收项：`scorecard.md`

压缩组与基线组必须使用相同的数据文件字节和提示词。
