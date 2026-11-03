# 上下文压缩三类任务配对评测：20261102-chart-analysis-400k-rerun-01

- Provider / Model：deepseek / deepseek-flash
- 条件：配置组 400000 tokens；基线组 100,000,000 tokens。
- 配置组的压缩触发线为容量的 80%（约 320,000 tokens）。Provider 总 Token 包含所有模型请求；压缩正确性只对至少成功压缩一次的任务评分。
- 原始 usage 差异按 `(基线 - 配置组) / 基线` 计算；只有成功触发压缩后才计算可归因压缩降幅。

| 任务 | 基线总 Token | 400k 配置组总 Token | 原始 usage 差异 | 可归因压缩降幅 | 成功压缩次数 | usage 完整 |
|---|---:|---:|---:|---:|---:|---|
| 01-chart-analysis | 325672 | 365803 | -12.32% | 不适用 | 0 | 是 |

## Codex（LLM-as-Judge）任务评分

| 任务 | 100M 基线 | 400k 配置组 | 说明 |
|---|---|---|---|
| 图表分析 | 通过（1/1） | 通过（1/1） | 两组答案均满足固定 scorecard；400k 配置组未触发压缩，不能算作压缩后的正确性样本。 |

逐项判分依据及复核材料见 [scorecard-results.md](scorecard-results.md)。该固定样本结果不并入 30 项 Agent 端到端评测，也不与 25k 压力运行合并统计。

400k 组的 80% 触发线约为 320,000 tokens，但三轮中没有成功压缩操作。其 365,803 总 Token 比基线 325,672 多 12.32%；这只是两次运行的原始差异，不能称为压缩节省或压缩开销。

## 未在本批次启动的项目

- 02-chart-construction / baseline（原计划序号 2）
- 02-chart-construction / compaction（原计划序号 3）
- 03-chart-modification / compaction（原计划序号 4）
- 03-chart-modification / baseline（原计划序号 5）
