# 压缩后资源读取 Prompt 改进对照

## 结论

在资源目录可见、问题未指定具体工具的 6 个用例中，更新后的 Prompt 使模型 6/6 首先使用目录里的正确类型化引用（基线 2/6），完整资源返回目标内容从 4/6 提升至 6/6，严格端到端直接读取成功从 1/6 提升至 4/6。OCR 两题读取成功且提取出了正确 marker code，但答案键要求输出整条 OCR 行；因此在严格字符串比对中仍记为失败。

另一个明确要求按类型化引用直读且省略 selector 的 3 题全部通过。结果支持这次 Prompt 修改改善了引用选择与字段路径使用；小样本结果不代表通用成功率。

## 对照设置

| 项目 | 基线 | Prompt 更新后 |
| --- | --- | --- |
| 批次 | `20261103-resource-direct-read-04` | `20261103-resource-direct-read-05-prompt-guidance` |
| Provider / model | DeepSeek / `deepseek-flash` | DeepSeek / `deepseek-flash` |
| Context capacity | 100,000 tokens | 100,000 tokens |
| 主读取用例 | 同一组 6 个 OCR、测量、ChartFigure 问题 | 同一组 6 个问题 |
| 定向读取用例 | 原批次未包含最终明确目标版本 | 3 类资源各 1 题，要求直接读取完整资源 |

两组使用相同合成 Run 事实、题目和资源读取后端。实时压缩摘要均由真实 Provider 生成，类型化资源引用在被测请求中可见。新批次的 `git_revision` 只记录当时的 HEAD；Prompt 改动当时尚未提交，因此此处同时记录被测文件 SHA-256：

| Prompt 文件 | 基线 SHA-256 | 本次 SHA-256 |
| --- | --- | --- |
| `src/figura/agent/prompting/execution.py` | `7f31144a1e105f6791c4176529a86d048fe88e06ae89c75c330e7b8ae094b6d3` | `ac493937727b488c887ac38e0a086f65b734f282159d21d455dfe411078729d6` |
| `src/figura/agent/prompting/assets/workflow.md` | `18818a4f647fdef1601f9497e79d4bd016f50927991df3d6032bf79b1e0ff600` | `8e04ebfbeac0963912afd577c9bfce9857e00f81740445c5bdcf8b7f6c371c3b` |
| `src/figura/tools/implementations/history.py` | `eee0a34b3d4a3efa5d40bba1f6a99238b3d5a7172e48fbd4e9550341114f5834` | `d63c18b1ab805d3165e392f8f185c8be8d89d91714a974d18634e4f26980d3eb` |

## 主读取组结果

| 指标 | 基线 | 更新后 |
| --- | ---: | ---: |
| 资源目录引用可见 | 3/3 类 | 3/3 类 |
| 首个工具调用为 `read_history` | 6/6 | 6/6 |
| 首次读取使用目标类型化引用 | 2/6 | 6/6 |
| 读取结果包含预期完整目标文本/值 | 4/6 | 6/6 |
| 最终答案与答案键严格相等 | 3/6 | 4/6 |
| 严格端到端直接读取成功 | 1/6 | 4/6 |
| 主读取用例中的字段读取调用失败 | 1 次 | 0 次 |
| 主读取用例中的失败工具调用（含后续搜索） | 2 次 | 0 次 |

逐题变化：

| 用例 | 基线 | 更新后 |
| --- | --- | --- |
| OCR 第 137 条 | 用 `tool_result` 读取成功；返回 `CODE-084920`，未匹配整行答案键 | 用 OCR 类型化引用和 `/result/snippets` 读取成功；仍只回答 code，整行严格比对未过 |
| OCR 第 149 条 | 选择 OCR 类型化引用，但误用 `/snippets`；读取与后续搜索失败 | 用 OCR 类型化引用和 `/result/snippets` 读取成功；正确返回 `CODE-179948`，但答案键要求整行 |
| 测量第 4 条 warning | 用 `tool_result` 读取并答对 | 用 measurement 类型化引用和 `/result/warnings` 读取并答对 |
| 测量第 5 条 warning | 用 `tool_result` 读取并答对 | 用 measurement 类型化引用和 `/result/warnings` 读取并答对 |
| Figure Period 08 | 用 `chart_figure` 类型化引用读取并答对 | 用 `chart_figure` 类型化引用读取并答对 |
| Figure Period 12 | 用 `tool_result` 只取得装配摘要，未答出数据 | 用 `chart_figure` 类型化引用读取并答对 |

OCR 题的自然语言查询目标是 “Observation marker code”，答案键却要求整条 `Observation NNN: marker CODE-...` 文本，而 Agent 的请求又要求返回目标字段的完整原文。为避免隐藏评分口径，表中保留严格答案键指标；按 marker code 字段值核对时，基线为 4/6、更新后为 6/6。后续扩充评测集时应把问题和答案粒度统一。

## 定向读取与搜索对照

定向组要求模型从当前目录复制类型化引用，读取完整资源并回答 OCR code、measurement warning 和 ChartFigure 数值。三题均只调用 `read_history`，引用类型和值正确，返回内容含目标，最终答案准确（3/3）；未调用 `search_history`，也没有 selector 错误。

目录引用移除对照有 2 个有效用例，均按题目要求先搜索再读取。两题最终都包含目标值，但额外输出来源或上下文，未通过当前的严格字符串答案比对。ChartFigure 控制题因答案泄漏校验失败未执行。该控制组验证了题目显式要求下的搜索路径，不能用来衡量模型自发选择搜索的概率。

## 验证范围与限制

- 主读取用例由生产 `AgentRequestBuilder` 构造请求，并通过生产历史工具运行时读取；评测没有运行完整 Gateway/Agent Run。
- OCR、测量及 Figure 内容是合成事实；实验不测真实图片理解或 OCR/测量准确率。
- 直接读取条件确保类型化引用可见，检验的是引用可见后的选用与读取，不检验压缩器在任意会话中保留引用的覆盖率。
- 更新后主读取组没有字段读取失败，因此“同一引用省略 selector 重试”分支没有被 live model 调用触发；本轮对这条回退规则的验证限于 Prompt／Schema 断言。
- 每个条件只有一次模型运行；指标用于本轮 Prompt 迭代对照，不作统计显著性或总体可靠性结论。
- 压缩摘要 token 用量在两批间有波动，不作为本次 Prompt 效果指标。

## 原始证据

- 基线：[report.json](../20261103-resource-direct-read-04/report.json)
- 基线定向读取：[typed-resource-read-followup-v3.json](../20261103-resource-direct-read-04/typed-resource-read-followup-v3.json)
- 更新后主批次：[report.json](report.json)
- 更新后定向读取：[typed-resource-read-followup-v3.json](typed-resource-read-followup-v3.json)
