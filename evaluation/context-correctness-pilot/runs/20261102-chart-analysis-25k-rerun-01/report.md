# 上下文压缩三类任务配对评测：20261102-chart-analysis-25k-rerun-01

- Provider / Model：deepseek / deepseek-flash
- 条件：压缩组 25000 tokens；基线组 100,000,000 tokens。
- Provider 总 Token 包含摘要压缩请求；压缩正确性只对至少成功压缩一次的任务评分。
- 原始 usage 差异与可归因于压缩的降幅分开列示。

| 任务 | 基线总 Token | 压缩组总 Token | 原始 usage 差异 | 可归因压缩降幅 | 成功压缩次数 | usage 完整 |
|---|---:|---:|---:|---:|---:|---|
| 01-chart-analysis | 231527 | 46323 | 79.99% | 不适用 | 1 | 否 |

## 未在本批次启动的项目

- 02-chart-construction / baseline（原计划序号 2）
- 02-chart-construction / compaction（原计划序号 3）
- 03-chart-modification / compaction（原计划序号 4）
- 03-chart-modification / baseline（原计划序号 5）

## 执行失败

- 01-chart-analysis / compaction: RuntimeError: 01-chart-analysis compaction turn 1 ended as interrupted; remaining turns in this session were not submitted

压缩组只运行了首轮，而基线完成三轮，因此表中的原始 usage 差异不具可比性；79.99% 不是节省率。

## 任务语义评分

Codex 已按 scorecard 完成 LLM-as-Judge 复核：100M 基线通过；25k 压缩组因首轮中断、无最终回答而按端到端失败记录。逐项依据见 [scorecard-results.md](scorecard-results.md)。
