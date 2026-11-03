# 25k 续测评分结果

评判官：Codex（LLM-as-Judge）。逐项对照固定对话、answer-key、scorecard、工具轨迹、ChartSpec 和实际 PNG；本轮是 rubric 复核，不是独立盲评实验。

## 任务结果

| 任务 | 条件 | 结果 | 依据 |
|---|---|---|---|
| 图表分析 | 100M 基线 | 未通过 | 读图估值、系列归属和历史检索符合要求；但第三轮差值表与其展示值算术不一致，例如 `62.0 - 58.9` 写成 `3.03`，并据此将最大/最小季度说成单一季度，未满足差值与极值关键项。 |
| 图表构建 | 100M 基线 | 未通过 | 两面板、类型、顺序、15 个数据值、历史核对和 PNG 均正确；渲染轴范围/刻度不符合 0–70、0–60、步长 10 的关键要求。 |
| 图表构建 | 25k 压缩 | 未通过 | ChartSpec、数据和历史核对正确，且出现 1 次成功压缩；PNG 仍使用自动刻度，未满足轴范围/步长关键项。 |
| 图表修改 | 100M 基线 | 未通过 | 原始值、方向、季度顺序、标题和来源保留；PNG 没有柱上数值标签，配色为默认蓝/橙/红，未满足两项关键要求。 |
| 图表修改 | 25k 压缩 | 未通过 | 3 轮完成并成功压缩 3 次；数据与撤销要求正确，但 PNG 仍没有柱上数值标签，且未使用指定颜色。 |
| 图表分析 | 25k 压缩 | 未完成，按端到端任务记失败 | 首轮达到 30 分钟上限后被中断；无最终回答，且最后一个 Provider attempt 的 usage 缺失。该运行不进入 Token 节省率配对。 |

## Token 用量

| 配对任务 | 100M 基线 | 25k 压缩组（含压缩请求） | 变化 |
|---|---:|---:|---:|
| 图表构建 | 123,236 | 133,444 | **增加 8.28%** |
| 图表修改 | 352,364 | 248,523 | **减少 29.47%** |

两项 usage 完整且均触发成功压缩。按任务等权计算，这两个可用配对样本的平均 Token 降幅为 **10.60%（2 项）**。图表分析压缩组因超时、usage 不完整且没有完成三轮，排除在该平均值之外。

## 成功率口径

- 100M 基线：**0/3** 任务通过全部关键项。
- 25k 压缩条件：按计划的三类任务计，**0/3** 端到端任务成功；图表分析超时，另两类未通过关键图表要求。
- 仅看完成且 usage 完整的 25k 压缩配对项：**0/2** 任务通过全部关键项。
- 图表分析 25k 压缩首轮记录到 2,098,542 Provider Tokens，另有 1 个 attempt usage 缺失；37 次压缩操作完成，另有 1 次操作停在 preparing。此 Token 数是已记录值，不是完整总量。

评分只代表这组固定样例。轴范围/刻度、自定义颜色和柱上标签的失败也反映当前 ChartSpec/渲染能力边界，不能单独归因为上下文压缩。

## 可复核证据

| 任务/条件 | 最终回答 | ChartSpec / PNG |
|---|---|---|
| 图表分析基线 | [第三轮回答](01-chart-analysis__baseline/turn-03/final-answer.txt)；[历史工具轨迹](01-chart-analysis__baseline/turn-03/tool-overview.json) | — |
| 图表构建基线 | [第三轮回答](02-chart-construction__baseline/turn-03/final-answer.txt) | [ChartSpec](02-chart-construction__baseline/turn-03/figure-01.json) · [PNG](02-chart-construction__baseline/turn-03/render-01.png) |
| 图表构建 25k | [第三轮回答](02-chart-construction__compaction/turn-03/final-answer.txt) | [ChartSpec](02-chart-construction__compaction/turn-03/figure-01.json) · [PNG](02-chart-construction__compaction/turn-03/render-01.png) |
| 图表修改基线 | [第三轮回答](03-chart-modification__baseline/turn-03/final-answer.txt) | [ChartSpec](03-chart-modification__baseline/turn-03/figure-01.json) · [PNG](03-chart-modification__baseline/turn-03/render-01.png) |
| 图表修改 25k | [第三轮回答](03-chart-modification__compaction/turn-03/final-answer.txt) | [ChartSpec](03-chart-modification__compaction/turn-03/figure-01.json) · [PNG](03-chart-modification__compaction/turn-03/render-01.png) |
| 图表分析 25k 超时 | [独立续跑失败记录](../20261102-context3cat-stress-25k-continue-01/partial-report.md) | [执行记录](../20261102-context3cat-stress-25k-continue-01/01-chart-analysis__compaction/execution.json) |
