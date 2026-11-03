# 上下文压缩三类任务配对评测：20261103-100k-three-task-02

- Provider / Model：deepseek / deepseek-flash
- 条件：压缩组 100000 tokens；基线组 100,000,000 tokens。
- Provider 总 Token 包含摘要压缩请求；压缩正确性只对至少成功压缩一次的任务评分。
- 原始 usage 差异与可归因于压缩的降幅分开列示。

| 任务 | 基线总 Token | 压缩组总 Token | 原始 usage 差异 | 可归因压缩降幅 | 成功压缩次数 | usage 完整 |
|---|---:|---:|---:|---:|---:|---|
| 01-chart-analysis | 1650148 | 1717554 | -4.08% | -4.08% | 2 | 是 |
| 02-chart-construction | 33223 | 34395 | -3.53% | 不适用 | 0 | 是 |
| 03-chart-modification | 1330167 | 1093944 | 17.76% | 不适用 | 0 | 是 |

## 执行失败

- 02-chart-construction / baseline: RuntimeError: 02-chart-construction baseline turn 2 ended as failed; remaining turns in this session were not submitted
- 02-chart-construction / compaction: RuntimeError: 02-chart-construction compaction turn 2 ended as failed; remaining turns in this session were not submitted

任务语义评分待按对应 scorecard 完成后补入。
