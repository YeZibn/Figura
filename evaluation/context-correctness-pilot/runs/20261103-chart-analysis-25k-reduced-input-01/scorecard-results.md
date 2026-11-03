# 图表分析 25k 精简输入配对重跑评分

评判官：Codex（LLM-as-Judge）。按原 `scorecard.md` 逐项核对两组最终回答、三轮对话和工具轨迹。原图、answer-key 和 scorecard 未变；三轮提示由 537 字符缩至 366 字符，并加入已取得视觉证据不重复读取的要求。本批次是独立的精简输入变体。

## 任务判分

| 关键项 | 25k 配置组 | 100M 基线 |
|---|---|---|
| 面板识别 | 通过：双面板及标题正确。 | 通过：双面板及标题正确。 |
| 图表类型 | 通过：分组柱状图、折线图。 | 通过：分组柱状图、折线图。 |
| 类别与系列 | 通过：Q1–Q4、Jan–Jul 和系列归属正确。 | 通过：类别顺序和系列归属正确。 |
| 数据值 | 通过：估算值均在 scorecard 容差内。 | 通过：估算值均在容差内。 |
| 轴标签与单位 | 通过：轴标题正确；说明原图未另标订单单位。 | 通过：轴标题正确；未混淆收入与订单。 |
| 季度差值和极值季度 | **未通过**：最终答案称 Q1（+4.03）单独最大；scorecard 要求 Q1/Q2 并列。 | **未通过**：最终答案称 Q1（+4.1）最大，没有保留 Q1/Q2 并列。 |
| 月度净变化和极值月份 | 通过：+31，最低 Jan≈22.2，最高 Jul≈53.2。 | **未通过**：第二轮误报最低月份为 Mar；最终轮列出 Jan≈22.1，但没有明确更正最低月份，也遗漏极值判定。 |
| 历史检索 | **未通过**：成功的 Q3 搜索为空，另有 3 次 `invalid_result`；虽成功读取历史记录，但没有证明按搜索结果完成 Q3 和 May/Jul 的检索链。 | 通过（重试后）：搜索找到 Q3 测量记录并由 `read_history` 读取；工具校验/引用失败均重试成功。 |
| 历史数值 | 通过：Q3 Target≈48、Actual≈45，May≈44、Jul≈53。 | 通过：四个指定数值均在容差内。 |
| 结论边界 | 通过：没有无依据的因果解释。 | 通过：没有无依据的因果解释。 |

**端到端判定：两组均未通过（各 0/1）。** 两组都未满足季度最大差值 Q1/Q2 并列这一关键项；基线还将月度最低月份答错且没有在最终轮明确更正。基线同样失败，因此不能把这些语义错误单独归因于压缩。

## Token 与运行表现

- 两组都完成三轮，usage 完整。25k 组成功压缩 **8 次**。
- 25k 配置组总用量 **475,742 Tokens**；100M 基线 **253,977 Tokens**。按 `(基线 - 配置组) / 基线` 计算为 **-87.32%**，即配置组多用 **221,765 Tokens（+87.32%）**。这是单个配对样本的观察值，不外推为稳定开销比例。
- 精简提示从 537 字符缩至 366 字符；压缩组 `load_image` 共 2 次，没有重现旧压力批次中 26 次加载图片的情况。但第三轮仍触发 6 次压缩、耗时约 389 秒。该轮 `search_history` 有 3 次 `invalid_result`，`read_history` 有一次引用不可用后重试成功，工具错误仍带来额外调用。
- 本批次与原始 25k 压力运行、400k 配对运行和 30 项 Agent 端到端评测分开统计。

## 可复核材料

- 精简提示：[本次提示](input-materials/01-chart-analysis/conversation.md) · [原始提示备份](input-materials/01-chart-analysis/original-conversation.md)
- 25k 组：[第 1 轮](01-chart-analysis__compaction/turn-01/final-answer.txt) · [第 2 轮](01-chart-analysis__compaction/turn-02/final-answer.txt) · [第 3 轮](01-chart-analysis__compaction/turn-03/final-answer.txt) · [工具轨迹](01-chart-analysis__compaction/turn-03/tool-overview.json)
- 基线：[第 1 轮](01-chart-analysis__baseline/turn-01/final-answer.txt) · [第 2 轮](01-chart-analysis__baseline/turn-02/final-answer.txt) · [第 3 轮](01-chart-analysis__baseline/turn-03/final-answer.txt) · [工具轨迹](01-chart-analysis__baseline/turn-03/tool-overview.json)
- [批次摘要](summary.json) · [25k 执行记录](01-chart-analysis__compaction/execution.json) · [基线执行记录](01-chart-analysis__baseline/execution.json)
