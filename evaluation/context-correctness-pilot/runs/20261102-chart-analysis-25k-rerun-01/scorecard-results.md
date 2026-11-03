# 图表分析 25k 重跑评分

评判官：Codex（LLM-as-Judge），逐项对照固定对话、answer-key、scorecard 和工具轨迹。本次基线有完整三轮输出；25k 压缩组未完成任务，不能进行压缩后正确性判定。

## 结果

| 条件 | 结论 | 关键依据 |
|---|---|---|
| 100M 基线 | **通过** | 两面板结构、系列、类别、单位、全部估算值、季度差值、月度净变化和极值均符合 scorecard。第三轮成功使用 `search_history` 与 `read_history`。Q1/Q2 的估算差值为 4.1/3.9，模型指出 0.2 差异低于约 ±0.5 的图像换算误差，并说明按图面整数值两者并列；Q3/Q4 最小差值均为 3.0。 |
| 25k 压缩 | **未完成，按端到端任务记失败** | 首轮运行中完成 1 次压缩；随后 Provider 流连续约 12 分钟无新事件。停止请求后 Run 为 `interrupted`，没有最终回答，且 usage 不完整。 |

## Token 口径

- 基线三轮完整 Provider usage：**231,527 Tokens**。
- 压缩组仅首轮记录 **46,323 Tokens**，其中含一次压缩；至少 1 个 Provider attempt 缺少 usage，且后两轮未运行。
- `summary.json` 中的 79.99% 是完整基线与未完成首轮之间的原始数值差，**不可比较，也不是压缩节省率**。本次压缩节省率不适用。

## 可复核证据

- 基线三轮回答：[第 1 轮](01-chart-analysis__baseline/turn-01/final-answer.txt) · [第 2 轮](01-chart-analysis__baseline/turn-02/final-answer.txt) · [第 3 轮](01-chart-analysis__baseline/turn-03/final-answer.txt)
- 基线历史工具轨迹：[工具调用记录](01-chart-analysis__baseline/turn-03/tool-overview.json)
- 压缩组中断记录：[执行 JSON](01-chart-analysis__compaction/execution.json) · [Provider attempts](01-chart-analysis__compaction/turn-01/provider-attempts.json) · [部分回答](01-chart-analysis__compaction/turn-01/final-answer.txt)
