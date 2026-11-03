# 图表分析 400k 配对重跑评分

评判官：Codex（LLM-as-Judge）。逐项对照固定对话、`answer-key.md`、`scorecard.md`、最终回答与第三轮工具轨迹。关键项全部通过才判为任务通过。

## 结果

关键项全部通过，因此两组各自的图表分析任务均通过（各 1/1）。

| 评分项 | 100M 基线 | 400k 配置组 |
|---|---|---|
| 面板识别 | 通过：识别季度销售和月度订单两个独立面板。 | 通过：正确识别两个独立面板。 |
| 图表类型 | 通过：分组柱状图、单系列折线图。 | 通过：分组柱状图、单系列折线图。 |
| 类别与系列结构 | 通过：Q1–Q4；Jan–Jul；Target/Actual 与 Orders 归属正确。 | 通过：类别顺序和系列归属正确；排除了误检出的刻度文字和图例线假点。 |
| 全部数据值 | 通过：季度 40/36、55/51、48/45、62/59；月度 22、28、25、36、44、41、53；均明确标注估算。 | 通过：全部数据值与标注答案一致，均说明是按坐标轴估算。 |
| 轴标签与单位 | 通过：季度轴标签及 million USD 正确；Orders 轴正确。回答把 Number of Orders 释义为订单数，未与收入单位混淆；原图未单列单位。 | 通过：季度轴标为 Revenue (million USD)，订单轴标为 Number of Orders，并明确说明原图未注明订单单位。 |
| 季度差值 | 通过：4、4、3、3；Q1/Q2 最大并列，Q3/Q4 最小并列。 | 通过：按图面整数估读得到 4、4、3、3，并列判断正确。第三轮额外报告约 4.0/3.9 的亚单位读数，同时说明差异低于读图误差且按整数并列；符合估算容差。 |
| 月度变化 | 通过：净变化 +31；Jan=22 最低，Jul=53 最高。 | 通过：净变化 +31；Jan≈22 最低，Jul≈53 最高。 |
| 历史检索 | 通过：第三轮最终成功使用 `search_history` 和 `read_history`，定位并读取两个面板的记录。 | 通过：第三轮最终成功使用 `search_history` 和 `read_history`，检索引用与面板来源对应。 |
| 历史事实回答 | 通过：Q3 Target=48、Actual=45，May=44、Jul=53。 | 通过：Q3 Target≈48、Actual≈45，May≈44、Jul≈53，均标为估算。 |
| 结论边界 | 通过：仅描述数据与算术结果，没有无依据的因果解释。 | 通过：仅描述图表数据与变化，没有无依据的因果解释。 |

两组第三轮均曾遇到 `search_history` 返回 `invalid_result` 的工具响应，随后重试成功；`read_history` 调用成功，最终引用来源和数值核对正确。该过程记录为工具重试，不改变最终任务判分。

## Token 与压缩资格

- 400k 配置组完整三轮任务通过；100M 基线完整三轮任务通过。
- 400k 组实际总用量 **365,803 Tokens**；100M 基线 **325,672 Tokens**。按 `(基线 - 配置组) / 基线` 计算，原始 usage 差异为 **-12.32%**，即配置组多用了 40,131 Tokens。
- 400k 配置的触发阈值为约 **320,000 Tokens（80%）**，但本组没有成功压缩事件。因此这次数据**不能用于判断压缩后的正确性，也不能称作压缩节省率或压缩开销**。两组总用量差异是观察值，不能归因于压缩。
- 这里的 1/1 只描述这个固定图表分析样本在对应条件下的端到端回答是否通过，不是有统计代表性的总体成功率，也不并入 30 项 Agent 端到端评测。

## 可复核证据

- 400k 组回答：[第 1 轮](01-chart-analysis__compaction/turn-01/final-answer.txt) · [第 2 轮](01-chart-analysis__compaction/turn-02/final-answer.txt) · [第 3 轮](01-chart-analysis__compaction/turn-03/final-answer.txt)
- 400k 组第三轮工具轨迹：[工具调用记录](01-chart-analysis__compaction/turn-03/tool-overview.json)
- 100M 基线回答：[第 1 轮](01-chart-analysis__baseline/turn-01/final-answer.txt) · [第 2 轮](01-chart-analysis__baseline/turn-02/final-answer.txt) · [第 3 轮](01-chart-analysis__baseline/turn-03/final-answer.txt)
- 100M 基线第三轮工具轨迹：[工具调用记录](01-chart-analysis__baseline/turn-03/tool-overview.json)
- 执行与 usage 汇总：[400k 执行记录](01-chart-analysis__compaction/execution.json) · [基线执行记录](01-chart-analysis__baseline/execution.json) · [批次摘要](summary.json)
