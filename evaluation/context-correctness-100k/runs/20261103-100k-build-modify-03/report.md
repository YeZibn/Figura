# 上下文压缩三类任务配对评测：20261103-100k-build-modify-03

- Provider / Model：deepseek / deepseek-flash
- 条件：压缩组 100000 tokens；基线组 100,000,000 tokens。
- Provider 总 Token 包含摘要压缩请求；压缩正确性只对至少成功压缩一次的任务评分。
- 原始 usage 差异与可归因于压缩的降幅分开列示。

| 任务 | 条件 | 总 Token | 最大估算输入 | 成功压缩次数 | 全部轮次完成 | usage 完整 |
|---|---|---:|---:|---:|---|---|
| 02-chart-construction | baseline | 33051 | 16357 | 0 | 否 | 是 |
| 02-chart-construction | compaction | 32835 | 16298 | 0 | 否 | 是 |
| 03-chart-modification | compaction | 1071197 | 52490 | 0 | 否 | 是 |
| 03-chart-modification | baseline | 3047733 | 93974 | 0 | 是 | 是 |

## 配对 Token 用量对比

| 任务 | 基线总 Token | 压缩组总 Token | 原始 usage 差异 | 可归因压缩降幅 | 可归因 |
|---|---:|---:|---:|---:|---|
| 02-chart-construction | 33051 | 32835 | 0.65% | 不适用 | 否 |
| 03-chart-modification | 3047733 | 1071197 | 64.85% | 不适用 | 否 |

## 未在本批次启动的项目

- 01-chart-analysis / compaction（原计划序号 0）
- 01-chart-analysis / baseline（原计划序号 1）

## 执行失败

- 02-chart-construction / baseline: RuntimeError: 02-chart-construction baseline turn 2 ended as failed; remaining turns in this session were not submitted
- 02-chart-construction / compaction: RuntimeError: 02-chart-construction compaction turn 2 ended as failed; remaining turns in this session were not submitted
- 03-chart-modification / compaction: RuntimeError: 03-chart-modification compaction turn 20 ended as failed; remaining turns in this session were not submitted

任务语义评分待按对应 scorecard 完成后补入。
