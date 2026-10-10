# Evaluation：图表测量离线回归

> 更新日期：2026-10-09。[返回系统总览](../figura-implementation-overview.md)。本篇说明当前可运行的测量回归脚本及其报告；它不是在线评测服务，也不拥有 Run 事实。

## 1. 职责与边界

当前测量回归入口是 [`scripts/evaluate_figura_measurements.py`](../../scripts/evaluate_figura_measurements.py)，固定样例和参考目标位于 [`tests/fixtures/figura_measurement/`](../../tests/fixtures/figura_measurement/)。它通过 `measure_chart` 的生产授权、来源解析、工具运行和结果校验路径，衡量固定图像中声明可见对象的结构、关联、位置和数值表现。测量工具与 schema v3 结果的权威合同归 [Tools](tools.md#6-图像与测量工具合同)，评测要求归 [chart-measurement-regression 主规格](../../openspec/figura/openspec/specs/chart-measurement-regression/spec.md)。

另有独立的[上下文摘要与历史检索对照实验](../evaluations/context-compaction-ablation.md)，使用固定合成历史、真实模型摘要、生产请求构建及只读历史工具，对比输入占用和事实恢复。它不属于本篇测量回归，也不是完整 Agent/Gateway 端到端评测；实验记录另列本地估算、Provider usage 和事实/格式分数。

该实验后续增加了[摘要 Token 软目标复测](../evaluations/context-compaction-token-target.md)：加入约 4,000 tokens 目标后，摘要均值变长、请求 Token 降幅低于无目标基线；样本量较小且 Provider 输出无固定随机种子，结论仅作方向性参考。

另有[上下文容量预算实验](../evaluations/context-compaction-capacity.md)，对固定合成历史在 100,000 和 200,000 容量下比较动态 10%/10% 历史预算，记录首请求本地估算、摘要输出长度、Provider 累计用量和源事实恢复。试验结论只适用于其固定样例；数值提示小样本未显示收益，因此生产摘要提示不包含预算数字。

这是一套可重复的合成样例回归，不是开放域图表基准、Provider 模型评测或 Agent 端到端完成率。它不会发起 Provider 网络请求；脚本用合成响应记录工具意图，仅为让 `DurableToolExecutor` 经正常 Run/Tool 路径执行工具。Gateway 与 Web 不提供评测工作区或评测 API。

## 2. 执行路径

1. 脚本读取固定 manifest，并校验每张输入图的 SHA-256；图片和参考目标由同一 fixture 生成来源维护。
2. 每个 case 在临时 SQLite 与私有文件目录中创建 Session、Run 和已授权 Attachment。多图画布通过普通 Panel 分割工具建立由 fixture 预先定义的 Panel 范围，以隔离测量算法和 Agent 的分图决策。
3. 对每个 Panel 或单图来源显式传入 `chart_type`，再通过 `DurableToolExecutor` 调用 `measure_chart`。生产测量输入不包含期望标签、数值、目标位置或文件名；OCR 使用真实 RapidOCR。
4. 工具结果产生后，评测器再将 family observations 展平，与参考目标做一对一匹配，分别检查缺失/误检、语义关联、几何容差、数值缺失/误差及工具校验过的数值来源。阈值预先记录在 fixture 中。
5. 每个 case 的摘要写入 JSON 报告。默认输出为被忽略的 `.figura/evaluation/measurement-regression.json`，可用 `--output` 改到其他路径；临时 Run 和图像不进入报告。

固定 Gallery Panel 只用于测量回归，不能证明 Panel 自动分割准确。另有单测覆盖固定 OCR 候选和算法变体；本脚本的指标来自真实 OCR 路径。

## 3. 报告字段

报告由脚本直接构造为 JSON，没有独立数据库、领域实体或单独的 report schema version。下表列出当前输出的全部字段。

### 根对象

| 字段 | 类型 | 含义 |
|---|---|---|
| `scope` | `str` | 固定说明本报告属于合成样例离线测量回归，不代表 Agent 完成率或外部基准准确率 |
| `python` | `str` | 执行时 Python 版本 |
| `git_revision` | `str` | 执行时仓库 HEAD commit |
| `measurement_source_sha256` | `str` | `src/figura/tools/measurements/*.py` 按文件名排序后计算的代码摘要 |
| `manifest_sha256` | `str` | fixture manifest 的 SHA-256 |
| `contract_version` | `int` | 测量结果合同版本；当前为 `3` |
| `cases` | `list[MeasurementRegressionCase]` | 按 manifest 顺序排列的逐实例结果 |

### `MeasurementRegressionCase`

每条 case 都含有以下公共字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `case_id` | `str` | fixture 中稳定的 case 身份 |
| `chart_type` | `str` | 本次显式请求的家族：`bar`、`line`、`scatter`、`pie`、`area`、`histogram`、`box_plot`、`radar`、`heatmap`、`treemap` |
| `sha256` | `str` | 对应输入图像摘要；不写入图片路径或字节 |
| `ocr_mode` | `str` | OCR 路径标识；当前真实路径为 `real_rapidocr` |
| `passed` | `bool` | 是否满足该实例的全部预设结构、关联、几何、数值和来源校验条件 |

工具成功时还包含：

| 字段 | 类型 | 含义 |
|---|---|---|
| `expected_objects`、`observed_objects`、`matched_objects` | `int` | 参考目标数、观察对象数和一对一匹配数 |
| `missing_objects`、`spurious_objects` | `int` | 未匹配的参考对象数和额外观察对象数 |
| `association_errors` | `list[AssociationError]` | 系列、类别、行列、父子关系或对象角色不一致 |
| `geometry_errors` | `list[GeometryError]` | 超过预设像素容差的目标与观察位置差异 |
| `numeric_missing` | `list[NumericMissing]` | 参考目标要求但观察结果缺失的数值字段 |
| `numeric_errors` | `list[NumericError]` | 超出预设误差容差的数值比较 |
| `provenance_validation` | `str` | 当前 schema v3 成功结果为 `validated_by_tool` |
| `calibration_support` | `list[CalibrationSupport]` | 测量结果使用的校准类型、支持域、残差及可选线性参数摘要 |
| `measurement_status` | `str` | 工具结果状态：`measured`、`partial`、`no_evidence` 或 `unsupported`；partial 不自动等同回归失败 |

嵌套错误项字段如下：

| 对象 | 全部字段 |
|---|---|
| `AssociationError` | `target: str`、`field: str`、`expected: str \| null`、`actual: str \| null` |
| `GeometryError` | `target: str`、`expected_position_px: [number, number]`、`actual_position_px: [number, number]`、`distance_px: number` |
| `NumericMissing` | `target: str`、`field: str` |
| `NumericError` | `target: str`、`field: str`、`expected: number`、`actual: number`、`error: number`、`tolerance: number` |
| `CalibrationSupport` | `id: str`、`kind: str`、`axis_role: str`、`support_domain`（结构由 [Tools 的测量结果合同](tools.md#6-图像与测量工具合同)定义）、`residual_value: number \| null`、`parameters: object`；`parameters` 只保留存在的 `slope`、`intercept` |

工具失败时不包含成功比较字段，而增加 `tool_error` 对象，字段为 `code: str` 和 `message: str`。成功分支的错误列表可为空；失败分支以工具错误记录失败原因，不伪造对象级比较结果。

## 4. 当前验证结果与适用范围

2026-10-07 使用以下命令复跑（本次输出重定向到系统临时目录，未写入仓库）：

```bash
conda run -n agent python scripts/evaluate_figura_measurements.py
```

当前 fixture 包含十张单图和三张多图画布，共 13 张图片、20 个图表实例，覆盖十类图表。20 个实例全部通过；188 个声明可见目标全部匹配，缺失与误检均为 0，关联、几何、数值缺失和数值误差列表均无失败项。结果状态为 14 个 `measured`、6 个 `partial`。`partial` 保留已观察到的结构，同时表达标定或覆盖不足；它不宣称所有隐藏对象和未支持数值均已恢复。

结果只说明当前实现通过这组固定合成样例及其预设容差。它不验证任意真实图表、自动 Panel 识别、模型选择策略、Agent 对话完成、生成图审核或发布，也不能替代外部评测集。评估开放域能力前仍需建立代表真实分布的人工标注集和任务级指标。

## 5. 依据

- 实现与命令：[`evaluate_figura_measurements.py`](../../scripts/evaluate_figura_measurements.py)
- 样例和参考目标：[`tests/fixtures/figura_measurement/`](../../tests/fixtures/figura_measurement/)
- 回归合同：[chart-measurement-regression](../../openspec/figura/openspec/specs/chart-measurement-regression/spec.md)
- 测量结果合同：[chart-family-measurement](../../openspec/figura/openspec/specs/chart-family-measurement/spec.md)
- 授权工具执行：[Tools](tools.md#6-图像与测量工具合同)
