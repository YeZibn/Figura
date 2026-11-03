# 上下文压缩三类任务配对评测：20261103-100k-construction-retry-05

- Provider / Model：deepseek / deepseek-flash
- 条件：压缩组 100000 tokens；基线组 100,000,000 tokens。
- Provider 总 Token 包含摘要压缩请求；压缩正确性只对至少成功压缩一次的任务评分。
- 原始 usage 差异与可归因于压缩的降幅分开列示。

| 任务 | 条件 | 总 Token | 最大估算输入 | 成功压缩次数 | 全部轮次完成 | usage 完整 |
|---|---|---:|---:|---:|---|---|
| 02-chart-construction | baseline | 33179 | 16357 | 0 | 否 | 是 |
| 02-chart-construction | compaction | 33325 | 16404 | 0 | 否 | 是 |

## 配对 Token 用量对比

| 任务 | 基线总 Token | 压缩组总 Token | 原始 usage 差异 | 可归因压缩降幅 | 可归因 |
|---|---:|---:|---:|---:|---|
| 02-chart-construction | 33179 | 33325 | -0.44% | 不适用 | 否 |

## 未在本批次启动的项目

- 01-chart-analysis / compaction（原计划序号 0）
- 01-chart-analysis / baseline（原计划序号 1）
- 03-chart-modification / compaction（原计划序号 4）
- 03-chart-modification / baseline（原计划序号 5）

## 执行失败

- 02-chart-construction / baseline: RuntimeError: 02-chart-construction baseline turn 2 ended as failed; remaining turns in this session were not submitted
- 02-chart-construction / compaction: RuntimeError: 02-chart-construction compaction turn 2 ended as failed; remaining turns in this session were not submitted

任务语义评分待按对应 scorecard 完成后补入。
