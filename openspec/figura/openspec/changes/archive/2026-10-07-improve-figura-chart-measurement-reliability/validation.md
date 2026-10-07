# 实施验证记录

## 初始基线

- 原始 ChartSpec/ChartFigure 生成数据可恢复；13 张基线图片与 `photo/` 图像的 SHA-256 一致。评测标准来自生成数据，不把模型估读作为真值，也不将标准答案传入生产测量输入。
- 使用生产授权和工具调用路径、真实 RapidOCR 离线执行基线；未发起 Provider 请求。初始报告保存在本机忽略目录 `.figura/evaluation/measurement-baseline.json`。
- 20 个图表实例均未满足结构、关联、几何和数值的严格全通过标准。该基线衡量固定合成样例，不代表 Agent 完成率或外部数据集准确率。
- 初始测量结果合同为 schema_version 2；逐值来源与校准支持尚未纳入合同。

## 当前实现验收

- 固定评测命令：`conda run -n agent python scripts/evaluate_figura_measurements.py`。
- 评测覆盖 13 张图片、20 个实例，包含十类图表各两例；Gallery 实例通过预先授权的固定 Panel 范围测量。全部 20 个实例通过严格检查。
- 188 个预期对象全部匹配；缺失和误检均为 0。类别/系列关联、几何误差、数值缺失、数值误差和工具内 provenance 校验均无失败项。
- 20 例使用真实 RapidOCR；结果状态为 14 个 `measured`、6 个 `partial`。`partial` 保留了结构证据，但不表示所有实例都具备可读刻度和数值校准。
- 当前合同为 schema_version 3。非空语义值均经工具内支持校验；标注图直接由已验证结果生成，不再运行第二套检测。
- 最新评测 JSON 位于本机忽略目录 `.figura/evaluation/measurement-regression.json`，不提交图像评测的逐次输出。
- 该评测只验证当前生成的合成样例和固定 Panel 范围；不衡量开放域真实图表、模型自主分图、Agent 对话完成率，也不能替代外部基准。

## 变体与测试

- 测量专项、契约、支持闭包、历史读取、工具授权、可视化、十类适配器和 Registry cutover 测试在 agent 环境中执行；专项合计 109 项通过，新增边界变体与离线 Gateway 探针用例 20 项通过。
- 受控变体覆盖颜色、尺寸、透明度、OCR 文本框尺寸、同色相邻热力格、反向非零轴、缺刻度、局部范围、遮挡/重叠、空白输入、错误家族及不支持几何。
- Gateway 离线单测中的模拟 Runtime 显式提供就绪探针，避免依赖开发机 Provider 密钥或配置。
- 全量 Python 测试：`conda run -n agent python -m pytest -q`，1251 passed、1 skipped。唯一跳过项依赖未提供的可选真实图附件 `tests/fixtures/real_chart_diagnostic/rotated_label_line_chart.png`。
- `git diff --check` 通过；`openspec validate improve-figura-chart-measurement-reliability --store figura --type change --strict --no-interactive` 通过。
