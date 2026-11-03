# Figura 上下文压缩评测：100k 容量版

本目录是独立的 100k 评测版本，不覆盖旧的 25k、50k、400k 运行或原始三轮任务。首轮 10 轮校准发现三类任务都没有触发压缩；20 轮批次证明分析任务可触发压缩，但构建在 turn 2 Provider 响应失败，修改任务也没有触发。后续将构建扩为 30 轮并拆分初始装配步骤，修改扩为 34 轮；各校准/中间批次均保留，不作为完整三类结果。

## 实验条件

- 压缩组：`context_window_tokens=100000`，Figura 按约 80% 输入估算触发压缩。
- 对照组：`context_window_tokens=100000000`，用于关闭本评测中的压缩触发；这不是 Provider 的实际上下文规格。
- 分析/构建/修改分别为 20/30/34 轮。三个任务各用独立 Session；同一配对两组使用相同脚本、文件和当前提示版本。
- 设计目标是在资源读取轮开始前观察到至少一次成功压缩；实际是否触发以执行记录为准。未触发时按“未触发”记录，不计算压缩后正确率或 Token 节省。

## 任务与材料

| 任务 | 输入 | 关键考查点 |
|---|---|---|
| `01-chart-analysis` | 四面板带数值标注的运营仪表盘 | 20 轮数据提取、计算与审计；压缩后按类型化资源引用核对早期数值 |
| `02-chart-construction` | 4 面板、88 个数据位置的结构化数据 | 30 轮递进 Figure 装配、数据审计与候选布局撤销；压缩后从 `read_history` 还原数据与缺失值 |
| `03-chart-modification` | 三面板运营图像 | 34 轮增量修改、定量核算、临时方案撤销与压缩后目标/非目标差异审计 |

图表输出评分只要求当前 ChartSpec/ChartFigure 可表达的字段：数据、顺序、类型、标题、来源/备注、轴标签和 Figure 列布局。不要求自定义颜色、笛卡尔轴范围/刻度间距或任意数据标签。

## 运行

运行器通过 `FIGURA_CONTEXT_PILOT_DIR` 选择本目录；默认行为仍指向旧 pilot。正式批次运行后在 `runs/<batch-id>/` 保存输入哈希、每轮记录、Provider usage、压缩操作与报告。评测结果只对完整运行且 usage 完整的配对计算 Token 差值；压缩请求计入总量。

冻结材料验证和正式配对运行命令：

```bash
conda run -n agent python evaluation/context-correctness-100k/validate_materials.py
FIGURA_CONTEXT_PILOT_DIR=evaluation/context-correctness-100k \
  conda run -n agent python evaluation/context-correctness-pilot/run_paired.py \
  20261103-100k-three-task-03 100000

# 仅补跑构建和修改配对（SCHEDULE 索引 2–5）
FIGURA_CONTEXT_PILOT_DIR=evaluation/context-correctness-100k \
  conda run -n agent python evaluation/context-correctness-pilot/run_paired.py \
  20261103-100k-build-modify-03 100000 2 6
```

固定脚本和答案键不得作为 Agent 输入。Codex 盲评按每项任务的 scorecard 执行；JSON/数据/PNG完整性优先规则化核验，答案与渲染一致性再做 LLM-as-Judge。

## 当前评测结果

最终判分与限制见 [judge-results.md](judge-results.md)。分析与修改任务都完成了压缩，并在压缩后通过 `read_history` 找回指定信息；但两项压缩组的 Provider 总 Token 分别比基线高 4.08% 和 5.41%。构建任务的配对运行均在第 2 轮收到 `invalid_provider_response`，没有可判分的最终图表，因此当前不能报告三类任务的完整成功率，也不能声称 100k 方案降低了总 Token。
