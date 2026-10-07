# Figura 图表示例

本目录中的图像由当前 ChartSpec v2、ChartFigure v2 与 PNG renderer 生成。图中数据均为用于展示的模拟数据，不代表真实业务数据或图像测量结果。

## 单图示例

`single/` 包含当前支持的十类图表：

- `bar.png`：柱状图
- `line.png`：折线图
- `scatter.png`：散点图与气泡尺寸
- `pie.png`：甜甜圈图（饼图的内半径变体）
- `area.png`：堆叠面积图
- `histogram.png`：直方图
- `box_plot.png`：箱线图
- `radar.png`：雷达图
- `heatmap.png`：热力图
- `treemap.png`：矩形树图

## 多图画布

`gallery/` 使用 ChartFigure 组合多张图表：

- `01_sales_and_market.png`：柱状、折线、气泡散点、甜甜圈
- `02_trends_and_distributions.png`：面积、直方、箱线、雷达
- `03_operations_and_revenue.png`：热力图、矩形树图

## 可复现生成与测量评测

模拟源数据与标准答案保存在 `tests/fixtures/figura_measurement/`，不进入 Agent 或测量工具输入。更新展示图片运行：

```bash
conda run -n agent python scripts/generate_figura_measurement_fixtures.py --update-photo
conda run -n agent python scripts/evaluate_figura_measurements.py
```

评测共覆盖 13 张图片、20 个图表实例，分别核对对象、类别/系列关联、几何、数值缺失及误差。Gallery 使用固定授权 Panel 范围，结果不能代表模型自主分图或整次 Run 完成率。输出报告保存在本地 `.figura/evaluation/`；严格通过情况以报告为准。

当前固定合成回归中 20/20 个实例通过，188 个目标对象全部匹配，无缺失、误检、关联错误、几何超差或数值超差。该结果仅说明当前合成样例通过既定检查，不代表开放域真实图表准确率或 Agent 端到端完成率。
