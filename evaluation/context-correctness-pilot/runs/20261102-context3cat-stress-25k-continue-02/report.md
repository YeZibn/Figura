# 上下文压缩三类任务配对评测：20261102-context3cat-stress-25k-continue-02

- Provider / Model：deepseek / deepseek-flash
- 条件：压缩组 25000 tokens；基线组 100,000,000 tokens。
- Provider 总 Token 包含摘要压缩请求；压缩正确性只对至少成功压缩一次的任务评分。
- 原始 usage 差异与可归因于压缩的降幅分开列示。

| 任务 | 基线总 Token | 压缩组总 Token | 原始 usage 差异 | 可归因压缩降幅 | 成功压缩次数 | usage 完整 |
|---|---:|---:|---:|---:|---:|---|
| 02-chart-construction | 123236 | 133444 | -8.28% | -8.28% | 1 | 是 |
| 03-chart-modification | 352364 | 248523 | 29.47% | 29.47% | 3 | 是 |

## 未在本批次启动的项目

- 01-chart-analysis / compaction（原计划序号 0）

## 任务语义评分

Codex 已按固定 scorecard 完成 LLM-as-Judge 复核，逐项结论见 [scorecard-results.md](scorecard-results.md)。本批次完成的基线与压缩任务均未通过全部关键项。图表分析压缩条件在前序独立续跑中超时，见 [25k 汇总报告](../20261102-context3cat-stress-25k-overview.md)。

Token 变化只统计本批次中两组都完成、usage 完整且确实触发过压缩的配对任务；图表分析不在本表中，也不计入平均值。
