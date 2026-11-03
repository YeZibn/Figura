# Figura E2E-30 正式首测报告

批次：20261102-正式首测-01；状态：complete。

只有完整执行、评分及复核后才报告完整成功率。校准任务不计入分母。

| 类别 | 计划 | 成功 | 失败 | 未裁定 | 成功率 | 95% Wilson CI |
|---|---:|---:|---:|---:|---|---|
| 图表分析 | 10 | 10 | 0 | 0 | 100% | [72.25, 100.0] |
| 图表构建 | 10 | 9 | 1 | 0 | 90% | [59.58, 98.21] |
| 多轮修改 | 10 | 8 | 2 | 0 | 80% | [49.02, 94.33] |

整体：成功 27，失败 3，未裁定 0；成功率 90.0%，95% CI [74.38, 96.54]。

| 任务 | 最终结论 | 初评 | 初评首要原因 | 关键项（初评） | 耗时/秒 | Provider Token | 复核 |
|---|---|---|---|---|---:|---:|---|
| [A01](tasks/A01/execution.json) | pass | pass | — | 4/4 | 15.767 | 40482 | — |
| [A02](tasks/A02/execution.json) | pass | pass | — | 3/3 | 8.095 | 26397 | pass |
| [A03](tasks/A03/execution.json) | pass | pass | — | 4/4 | 6.064 | 26388 | — |
| [A04](tasks/A04/execution.json) | pass | pass | — | 5/5 | 212.348 | 473588 | — |
| [A05](tasks/A05/execution.json) | pass | pass | — | 3/3 | 6.063 | 26173 | — |
| [A06](tasks/A06/execution.json) | pass | pass | — | 4/4 | 10.489 | 40593 | — |
| [A07](tasks/A07/execution.json) | pass | pass | — | 4/4 | 111.912 | 431686 | — |
| [A08](tasks/A08/execution.json) | pass | pass | — | 3/3 | 31.451 | 63774 | — |
| [A09](tasks/A09/execution.json) | pass | pass | — | 3/3 | 12.165 | 41839 | — |
| [A10](tasks/A10/execution.json) | pass | pass | — | 4/4 | 111.075 | 193413 | pass |
| [B01](tasks/B01/execution.json) | pass | pass | — | 3/3 | 8.162 | 40501 | — |
| [B02](tasks/B02/execution.json) | pass | pass | — | 3/3 | 12.327 | 71267 | — |
| [B03](tasks/B03/execution.json) | pass | pass | — | 3/3 | 6.118 | 40586 | pass |
| [B04](tasks/B04/execution.json) | pass | pass | — | 3/3 | 14.417 | 72799 | — |
| [B05](tasks/B05/execution.json) | pass | pass | — | 3/3 | 10.216 | 41071 | — |
| [B06](tasks/B06/execution.json) | pass | pass | — | 3/3 | 8.146 | 40863 | — |
| [B07](tasks/B07/execution.json) | pass | pass | — | 3/3 | 8.157 | 40823 | pass |
| [B08](tasks/B08/execution.json) | fail | fail | rendering | 2/3 | 24.604 | 88896 | fail |
| [B09](tasks/B09/execution.json) | pass | pass | — | 3/3 | 8.148 | 40676 | — |
| [B10](tasks/B10/execution.json) | pass | pass | — | 3/3 | 10.232 | 41955 | — |
| [C01](tasks/C01/execution.json) | pass | pass | — | 11/11 | 24.847 | 156620 | pass |
| [C02](tasks/C02/execution.json) | fail | fail | baseline_construction | 10/11 | 24.849 | 139681 | fail |
| [C03](tasks/C03/execution.json) | fail | fail | delivery | 10/11 | 24.88 | 141351 | fail |
| [C04](tasks/C04/execution.json) | pass | pass | — | 11/11 | 24.893 | 140105 | — |
| [C05](tasks/C05/execution.json) | pass | pass | — | 11/11 | 24.776 | 158419 | — |
| [C06](tasks/C06/execution.json) | pass | fail | non_target_corruption | 10/11 | 31.012 | 160662 | pass |
| [C07](tasks/C07/execution.json) | pass | pass | — | 11/11 | 24.82 | 174844 | pass |
| [C08](tasks/C08/execution.json) | pass | pass | — | 11/11 | 25.102 | 144815 | — |
| [C09](tasks/C09/execution.json) | pass | pass | — | 11/11 | 26.818999999999996 | 141845 | — |
| [C10](tasks/C10/execution.json) | pass | pass | — | 11/11 | 26.909 | 140833 | — |

## 资源和范围

已完成正式轮次 50；Provider 总 Token 3382945；内部重试 0。Token 包含所有可获得 usage 的物理 attempt，缺失 usage 的轮次为 0。Codex judge 用量另存 summary.json，不与 Figura 用量合并。

条件：deepseek-flash，当前生产上下文配置 200,000 tokens、thinking 开启；Codex gpt-6.1-sol 按题独立上下文评判。正式单轮超时 600 秒。详见 batch.json。

本结果属于固定30题（各类10题）的单次执行；不是生产分布、开放域准确率或浏览器 UI 全流程结果。4张真实来源图均来自 OWID，另有6张合成分析图。参考图片与实际产物严格区分。

复核覆盖全部初评失败/待复核任务，加各类通过任务20%向上取整的固定随机样本。完整选择及分歧见 review-selection.json / final-status.json。

任务 Provider Token 中位数 72033.0，范围 26173—473588。

任务执行耗时中位数 20.19 秒，范围 6.06—212.35 秒。

## 失败证据与复核裁决

- **B08**（rendering）：实际PNG存在关键数值遮挡；图下方的原值说明和正确的结构化数据不能抵消图内错误读数。 [初评](tasks/B08/verdict.json) / [复核](tasks/B08/review-independent.json)。
- **C02**（baseline_construction）：对系列高低关系的明确陈述与数据及实际图像冲突，未满足交付回答一致性要求。 [初评](tasks/C02/verdict.json) / [复核](tasks/C02/review-independent.json)。
- **C03**（delivery）：对销售趋势的明确描述与数据及实际图像冲突，不满足交付回答的一致性要求。 [初评](tasks/C03/verdict.json) / [复核](tasks/C03/review-independent.json)。

独立复核 10 题，其中 9 题任务结论一致。C06 的注释争议按冻结的空 note 等义例外裁决通过，[裁决记录](adjudications/C06.json)。原始初评与独立复核文件均保留；报告表格的“初评首要原因”和“关键项（初评）”不代表裁决后的最终结论。

初评和复核均为 Codex gpt-6.1-sol 的新独立上下文，未向复核者提供初评标签。这是同一模型下的复核一致性，不是人工标注的 judge 准确率。未为评分重跑任何正式 Figura 任务，未修改输入、标准答案、Prompt、工具或在线代码。

修改类补充诊断：首轮基线关键项通过 8/10；在这些基线任务中，最终完整任务通过 8/8。这项条件统计不替代修改类主指标。

正式运行记录的压缩操作数：0。因此本批次不形成“压缩后正确性”的单独结论。

原始运行输入已逐字核对，30个Session、50个Run互不重复，43份实际Figure/PNG摘要匹配。详见 [证据校验](evidence-validation.json)。评测专用Gateway已退出，端口已释放；原有用户会话目录未用于本批次。
