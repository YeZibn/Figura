# 压缩后资源目录读取试验结果

## 结论

实验确认：当类型化资源引用出现在压缩请求的资源目录中时，模型可以通过 `read_history` 直接读取 OCR、测量和 ChartFigure 的完整内容，并回答针对性问题。定向组 3 类各 1 题，正确读取并提取 3/3。

但在不要求特定工具用法的自由选择组中，模型虽然 6/6 首先调用了 `read_history`，只有 2/6 首次引用与资源目录中的类型化引用完全一致，端到端直接读取成功 1/6。常见偏差是使用摘要中出现的 `tool_result` 引用，或自行猜测错误的 selector 路径。因此，实验支持“目录引用可用、模型在明确目标下能直接使用”，不能据此声称“模型总能自发正确选择类型化引用”。

## 实验设置

- 日期：2026-11-03。
- Provider / model：DeepSeek / `deepseek-flash`。
- 隔离历史由确定性合成的 OCR、测量、ChartFigure 和填充内容构成；评测资源检索与提取，不评测真实图像 OCR 或测量准确性。
- 使用真实模型生成压缩摘要，并通过生产 `AgentRequestBuilder` 生成请求。主批次的压缩检查点会显式纳入资源来源引用，并移除摘要中包含目标答案的条目；生产请求投影实际显示了 OCR、measurement、chart_figure 三类引用。
- 模型可用的历史工具限定为 `read_history` 和 `search_history`；工具调用经生产历史工具运行时执行，不是完整的 Gateway/Agent Run。

## 结果

### 自由选择组：6 题

| 指标 | 结果 | 说明 |
| --- | ---: | --- |
| 资源目录显示目标类型引用 | 3/3 类 | OCR、measurement、chart_figure 均可见 |
| 首个工具调用为 `read_history` | 6/6 | 模型没有先调用 `search_history` |
| 首次引用与目录中的目标类型化引用完全一致 | 2/6 | 1 次 OCR，1 次 ChartFigure |
| 直接读取端到端成功 | 1/6 | 必须同时正确选引用、读到目标内容并答对 |
| 最终答案正确 | 3/6 | 包含通过 `tool_result` 读取成功的测量题 |

具体表现：

- OCR 第 137 条使用 `tool_result` 引用读取了内容，但最终只给出 code，而预设答案要求完整行，严格答案比对未通过。
- OCR 第 149 条选对 OCR 类型引用，但猜错 selector 路径；读取失败后尝试 `search_history`，该次搜索也失败。
- 两道测量题使用 `tool_result` 引用并答对，但不计作“直接从类型化资源目录引用读取”。
- Figure Period 08 使用目录中的 `chart_figure` 引用并答对。
- Figure Period 12 使用 `tool_result` 引用，仅取得装配结果摘要，没有读取完整 Figure 数据，未答对。

### 定向类型化读取组：3 题

评测题分别要求 OCR 第 137 条 code、测量结果第 4 条 warning、Figure Period 08 的 Revenue 值。提示要求模型从当前请求的目录复制对应类型化引用，直接调用 `read_history`，只传引用并读取完整资源。

| 资源类型 | 目录引用选择 | 完整资源读取 | 目标答案正确 |
| --- | ---: | ---: | ---: |
| OCR | 1/1 | 1/1 | 1/1 (`CODE-084920`) |
| Measurement | 1/1 | 1/1 | 1/1 (`Detailed warning token: WARN-7QK-491.`) |
| ChartFigure | 1/1 | 1/1 | 1/1 (`817.4`) |
| **合计** | **3/3** | **3/3** | **3/3** |

三题均只调用 `read_history`，引用与目录条目完全相同，未调用 `search_history`，也未传 selector。请求文本不含预期答案，返回的完整资源内容包含答案。

## selector 观察

额外的一轮尝试要求针对字段读取，但未规定路径。模型选对 OCR 与 measurement 类型化引用，却分别猜出 `/snippets` 和 `/warnings`，与可读资源的真实路径不符，工具返回 `history_reference_unavailable`；ChartFigure 的 `/figure` 读取成功并答对。因此当前情况下，不给 selector、让 `read_history` 返回完整资源后由模型提取，是这三类资源中更稳妥的方式。该观察来自小样本，不代表 selector 的普遍成功率。

## 对照组与限制

- 去掉摘要来源引用的 OCR 和 measurement 两个控制题，均先 `search_history` 再 `read_history`；OCR 答对，measurement 读取后回答不符合严格答案。ChartFigure 控制题因摘要答案泄漏校验失败而未运行，所以控制组只有 2 个有效样本。
- 样本规模是探索性试验，不支持总体成功率或显著性结论。
- 资源及答案是合成夹具，不代表真实图表内容识别质量。
- 定向组显式要求从目录复制引用，测的是“引用可见且任务目标明确时能否读取”，不是模型自发选择行为。
- 自由选择组也采用受控压缩检查点，并去除目标答案摘要条目；它不能单独证明任意自然对话经过压缩后都有同样表现。

## 产物

- 主实验逐例证据：[report.json](report.json)
- 定向读取 1（目标表述过于笼统，保留为过程记录）：[typed-resource-read-followup.json](typed-resource-read-followup.json)
- 定向字段尝试（OCR / measurement selector 路径错误）：[typed-resource-read-followup-v2.json](typed-resource-read-followup-v2.json)
- 定向完整资源读取（最终有效结果）：[typed-resource-read-followup-v3.json](typed-resource-read-followup-v3.json)
- 运行时隔离数据位于仓库 `.figura/evaluation/resource-read-20261103-resource-direct-read-04/`，不应提交。
