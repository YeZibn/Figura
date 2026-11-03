# 100k 三类上下文压缩评测：Judge 结果

## 判定口径

Codex 按各任务 scorecard 对最终回答、tool overview、ChartFigure JSON、PNG 和 Provider usage 做 LLM-as-Judge 与规则化交叉核验。压缩后正确性仅在运行记录存在成功 compaction operation、任务完整结束且 usage 完整时计分。固定任务各只有一组配对样本，结果是描述性观察，不外推为总体准确率。

Token 差异按 (100M 基线总 Token − 100k 压缩组总 Token) / 基线总 Token 计算。负数表示压缩组总用量更高；总用量包含 context_compaction 请求。

## 最终任务判定

| 任务 | 100M 基线 | 100k 压缩组 | Codex Judge | 压缩后核对 |
|---|---|---|---|---|
| 图表分析，20 轮 | 20/20 完成，usage 完整 | 20/20 完成；成功 compaction 2 次 | 通过。四面板、48 个值与核心计算一致；关联结论未越界 | turn 19 四次 read_history 均成功；Q2 South=44、November Orders=205，派生计算一致 |
| 图表构建，30 轮 | turn 2 Provider invalid_provider_response，停在 2/30 | turn 2 Provider invalid_provider_response，停在 2/30 | 未完成，不能判 ChartFigure 语义或渲染成功 | 未触发 compaction；不计压缩后正确率 |
| 多轮修改，34 轮 | 34/34 完成，usage 完整 | 34/34 完成；成功 compaction 1 次 | 通过，附一项非关键事实错误：turn 33 的附加收入表将 Q2 Central 写成 36，答案键为 26；四项指定读取值正确，最终 Figure 字段差异符合要求 | turn 33 四次 read_history 均成功；North Q4=50、Orders Jun/Jul/Aug=108/105/115、Conversion Dec=3.8；turn 34 Figure 和 PNG 完成 |

压缩组端到端完整任务为 2/3。两项完整且发生压缩的任务均通过其关键压缩后资源读取标准；构建任务因 Provider 响应失败未形成可判分产物，按端到端失败记录，而不推断为 ChartSpec 校验失败。

## Token 用量

| 任务 | 100M 基线总 Token | 100k 压缩组总 Token | 触发次数 | Token 差异 | 解释 |
|---|---:|---:|---:|---:|---|
| 图表分析 | 1,650,148 | 1,717,554 | 2 | -4.08% | 压缩组多用 67,406 Token，未节省总用量 |
| 图表构建（最新重跑） | 33,179 | 33,325 | 0 | 不适用 | 两组均在 turn 2 收到 `invalid_provider_response`，未完成，不能比较 |
| 多轮修改 | 2,692,738 | 2,838,430 | 1 | -5.41% | 压缩组多用 145,692 Token，未节省总用量 |

修改任务的 34 轮压缩组本地估算输入峰值为 77,828 tokens，turn 28 成功压缩；100M 基线峰值为 90,745 tokens且不触发。该差异说明本地 context estimate 与 Provider usage 不是同一计量口径，阈值判定以 Figura 记录的本地估算和 compaction operation 为准。

## 文件证据与异常

- 10 轮校准批次：runs/20261103-100k-three-task-01。分析和修改没有触发压缩；构建压缩组在 turn 2 失败，不作为压缩结果。
- 20 轮诊断批次：runs/20261103-100k-three-task-02。分析配对发生 2 次成功压缩；构建基线和压缩组均在 turn 2 失败；修改配对 20 轮完成但未触发压缩。
- 构建/修改补跑批次：runs/20261103-100k-build-modify-03。构建的两组再次在 turn 2 失败；修改 34 轮基线完成，压缩组于 turn 20 因 Provider invalid_provider_response 停止。
- 修改独立配对重试：runs/20261103-100k-modification-retry-04。修改压缩组与基线均 34 轮完成，压缩组 turn 28 有成功 operation，形成最终修改任务配对。
- 图表构建最新配对重试：runs/20261103-100k-construction-retry-05。两组 turn 1 完成、turn 2 再次收到 `invalid_provider_response`；基线和压缩组分别记录 33,179 与 33,325 Provider Token，均未触发压缩。

构建任务的失败记录为 Provider invalid_provider_response，发生在 streaming 阶段；该轮没有已提交的 tool call，usage 有记录，Provider 原始响应正文未由运行器保存。因此只报告 Provider 响应无效这一可观察事实，不据此断言 ChartSpec 工具本身失败。

## 结论范围

当前 100k 方案已经验证：分析和修改任务可触发压缩，Agent 可在之后通过类型化资源 ref 调用 read_history 并完成关键核对。当前两个可比较任务的 Provider 总 Token 都高于无压缩基线；因此本批数据支持“压缩后关键内容可检索”，不支持“100k 压缩降低总 Token 消耗”。构建任务尚无有效完整配对，需先解决其 Provider 响应失败后再补充结果。
