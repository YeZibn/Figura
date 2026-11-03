# 上下文压缩配对评测：20261103-chart-analysis-25k-reduced-input-01

- Provider / Model：deepseek / deepseek-flash；thinking mode=true，reasoning effort=high。
- 条件：压缩组 25,000 tokens；基线组 100,000,000 tokens；触发线为容量的 80%。
- 精简输入变体：三轮提示从 537 字符缩至 366 字符，增加已取得证据不重复读取要求；原图和评分标准不变。本批次与原始固定提示分开归档。
- 用量差异按 `(基线 - 压缩组) / 基线` 计算；负值表示压缩组用了更多 Token。总 usage 包含压缩请求。

| 任务 | 基线总 Token | 25k 配置组总 Token | usage 差异 | 成功压缩次数 | usage 完整 | 三轮完成 |
|---|---:|---:|---:|---:|---|---|
| 图表分析（精简输入） | 253977 | 475742 | -87.32% | 8 | 是 | 是 |

25k 组比基线多用 **221,765 Tokens（+87.32%）**。这是本配对样本的实际差异，不代表所有任务的稳定压缩开销。

## Codex（LLM-as-Judge）评分

| 条件 | 任务结果 |
|---|---|
| 100M 基线 | 未通过（0/1） |
| 25k 配置组 | 未通过（0/1） |

两组都没有保留季度最大差值 Q1/Q2 并列；基线还把月度最低月份报错，压缩组的历史搜索未能按要求完成。基线也未通过，因此不能把语义错误单独归因于压缩。逐项理由见 [scorecard-results.md](scorecard-results.md)。

## 运行概况

两组均完整完成三轮且 usage 完整；25k 组成功压缩 8 次。精简提示减少了重复读图，但第三轮仍压缩 6 次、耗时约 389 秒。该轮 `search_history` 有 3 次 `invalid_result`，`read_history` 有一次历史引用不可用后重试成功。运行输入和原提示备份位于 [`input-materials/01-chart-analysis/`](input-materials/01-chart-analysis/)。
