# Charts：图表内容、画布与渲染

> 更新日期：2026-10-06。[返回系统总览](../figura-implementation-overview.md)。本文说明当前工作树中的 ChartSpec v2、ChartFigure v2 与纯 PNG renderer。Charts 只拥有图表内容值、严格解析、语义校验、规范序列化和绘制；Run 身份、测量来源授权、事实持久化、PNG 文件与审核状态归其他领域所有。

## 1. 职责与数据流

`ChartSpecData` 是一张图的完整语义数据，`ChartFigure` 是按顺序组织 1–4 张图的画布。模型通过 `assemble_chart_figure` 提交完整 ChartFigure；Tools 校验所选测量引用确实指向当前 Session 授权前缀中的成功 `measure_chart` 调用。成功组装后，完整 Figure 位于既有 Runtime `ToolCallFact.arguments_json`，成功摘要位于 `ToolResultFact.result`，Agent 再由已提交事实重建类型化资源。渲染时 Charts 从校验通过的 Figure 生成 PNG 字节；Sources 负责私有保存，Web 负责安全预览与下载。

```text
模型提出完整 ChartFigure v2
          │
          ├── ChartSpec v2 严格解析与语义校验
          ├── 成功 measure_chart 引用授权核验（Tools）
          └── 通用 Run 工具事实提交（Runtime）
                    │
                    ├── Agent 从事实重建 ChartFigure 资源
                    └── render_chart_figure → Charts 生成 PNG → Sources 保存
```

Charts 不读取图片、Run、数据库或文件，不推断测量结果，也不替用户修复无效数据。测量结果只是候选证据；即使 Figure 引用了某次成功测量，也不代表其中每个值都与图像一致。

## 2. 十类图表与坐标合同

ChartSpec v2 使用封闭联合类型。`metadata.chart_type` 决定 `dataset` 的唯一形状，`coordinate_system.kind` 必须与图表类型匹配。

| `chart_type` | 坐标系统 | 数据表达与关键规则 |
|---|---|---|
| `bar` | `cartesian` | `orientation` 为纵向/横向，`mode` 为分组/堆叠；类别与每个系列的值一一对应 |
| `line` | `cartesian` | 多系列 x/y 点；x 可为数字、类别文本或 RFC 3339 时间，y 可为 null 表示缺口 |
| `scatter` | `cartesian` | 多系列数值 x/y 点；可选正数 `size` 表示气泡大小，size 必须在所有点上一致提供或一致省略 |
| `pie` | `none` | 正总量的非负切片；可选 `inner_radius_ratio` 表示甜甜圈内半径，范围 0–0.75 |
| `area` | `cartesian` | 多系列 x/y 边界，支持 `none` 或 `stacked`；堆叠系列必须具有相同顺序的 x 且不含空值 |
| `histogram` | `cartesian` | 数值区间 `start/end/value`；区间必须递增、有序且不重叠，测量量为 count/frequency/probability/density/unknown |
| `box_plot` | `cartesian` | 按方向排列分组统计，要求 lower whisker ≤ q1 ≤ median ≤ q3 ≤ upper whisker；离群值必须显式给出 |
| `radar` | `polar` | 至少三个有序维度，每个系列为每个维度提供一个值，值须落在声明的极坐标范围内 |
| `heatmap` | `matrix` | x/y 类别与矩阵值；行列尺寸必须分别匹配 y/x 类别数，null 表示无值 |
| `treemap` | `hierarchical` | 以 `root_id` 为根的节点树；节点父级必须存在且无环，叶节点需有正权重 |

这套表达只覆盖选定的常见二维图表。气泡图沿用散点数据加 `size`；甜甜圈图沿用饼图数据加 `inner_radius_ratio`。不包含组合/多轴、3D、烛台、漏斗、玫瑰等专业图型。

## 3. ChartSpec v2 字段

下表列出模型完整字段；行中的模型名与字段名共同构成完整字段路径。除注明可选或有默认值的字段外，字段均必需。所有模型均为冻结 dataclass；JSON parser 额外拒绝未知字段、重复 key、字段强制转换、布尔数值、字符串数值、NaN 与无穷。未显式说明的数组顺序按输入保留。

**字段流转：**模型通过 `assemble_chart_figure` 提交完整 Figure；Tools 调用 Charts 解析和校验。已提交的原始内容以 Runtime `ToolCallFact.arguments_json` 为权威，只有配对成功结果才代表接受的 Figure；Charts renderer 读取该不可变内容。当前没有单图或 Figure 的独立编辑 API，也不原位修订已提交内容；修改会形成新的组装调用。Web 仅公开受授权的 Figure 摘要和渲染 PNG。

| 模型 | 字段 | 类型与语义 |
|---|---|---|
| `ChartSpecData` | `schema_version` | `int`，固定为 2 |
|  | `metadata` | `ChartMetadata`，图表类型与显示信息 |
|  | `coordinate_system` | `CartesianCoordinateSystem`、`PolarCoordinateSystem` 或 `SimpleCoordinateSystem` |
|  | `dataset` | 十个 `ChartDataset` 分支之一，必须与 `metadata.chart_type` 匹配 |
| `ChartMetadata` | `chart_type` | 十类之一：bar/line/scatter/pie/area/histogram/box_plot/radar/heatmap/treemap |
|  | `title` | `str`，默认空文本，最多 160 字符 |
|  | `source` | `str \| None`，默认 null；仅展示文本，不授予来源访问权 |
|  | `note` | `str`，默认空文本，最多 160 字符 |
| `CartesianAxis` | `kind` | `AxisKind`：`categorical`、`numeric`、`time` |
|  | `label` | `str \| None`，默认 null，最多 160 字符 |
| `CartesianCoordinateSystem` | `kind` | 固定 `cartesian` |
|  | `x_axis`, `y_axis` | 两个 `CartesianAxis` |
| `PolarCoordinateSystem` | `kind` | `CoordinateSystemKind`，默认 `polar`；JSON 固定为 `polar` |
|  | `minimum`, `maximum` | 有限极坐标数值范围下界与上界；序列化到 JSON `value_range.min`、`value_range.max`，且 `minimum < maximum` |
| `SimpleCoordinateSystem` | `kind` | `matrix`、`hierarchical` 或 `none` |
| `ChartCategory` / `RadarDimension` | `id`, `label` | 唯一 ID 与显示文本；ID 最多 64 字符，文本最多 160 字符 |
| `ValueSeries` | `id`, `label`, `values` | 系列身份、显示名、有序数值；bar/radar 使用，值数须匹配类别/维度 |
| `XYPoint` | `x` | `str \| int \| float`；类型须符合 x 轴 kind |
|  | `y` | `int \| float \| None`；null 表示线/非堆叠面积数据缺口 |
| `XYSeries` | `id`, `label`, `points` | line/area 系列身份、显示名及有序 `XYPoint` |
| `BarDataset` | `orientation`, `mode` | `BarOrientation`（vertical/horizontal）、`BarMode`（grouped/stacked） |
|  | `categories`, `series` | `ChartCategory[]` 与 `ValueSeries[]`；每个系列值数须等于类别数 |
| `LineDataset` | `series` | 非空 `XYSeries[]` |
| `AreaDataset` | `stacking`, `series` | `none`/`stacked` 与非空 `XYSeries[]` |
| `ScatterPoint` | `x`, `y` | 有限数值坐标 |
|  | `size` | 可选正数；全体点必须一致提供或省略，用于气泡面积 |
| `ScatterSeries` / `ScatterDataset` | `id`, `label`, `points` / `series` | 有序散点系列；每系列至少一个点 |
| `PieSlice` | `id`, `label`, `value` | 切片 ID、显示名、非负值；ID 在图内唯一 |
| `PieDataset` | `slices` | 非空切片数组且总值为有限正数 |
|  | `inner_radius_ratio` | 可选数值，0–0.75；0 或省略为饼图，正值表现为甜甜圈 |
| `HistogramBin` | `start`, `end`, `value` | 数值区间和非负测量值，必须 `start < end` |
| `HistogramDataset` | `measure`, `bins` | 五种 `HistogramMeasure` 之一与有序不重叠区间数组 |
| `BoxPlotGroup` | `id`, `label` | 分组身份与显示文本 |
|  | `lower_whisker`, `q1`, `median`, `q3`, `upper_whisker` | 五个有限数值，按统计顺序非递减 |
|  | `outliers` | `tuple[number, ...]`，默认空；只绘制显式离群值 |
| `BoxPlotDataset` | `orientation`, `groups` | vertical/horizontal 与非空 `BoxPlotGroup[]` |
| `RadarDataset` | `dimensions`, `series` | 至少三个 `RadarDimension` 与非空 `ValueSeries[]`；每系列值数相同 |
| `HeatmapDataset` | `x_categories`, `y_categories` | 两个非空且各自 ID 唯一的 `ChartCategory[]` |
|  | `values` | `tuple[tuple[number \| None, ...], ...]`；矩阵行数等于 y 类别数、列数等于 x 类别数 |
| `TreemapNode` | `id`, `parent_id`, `label` | 唯一节点 ID、父 ID 或 null、显示文本 |
|  | `value` | 可选非负数；叶节点必须为正数，内节点若给值必须等于后代叶节点总值；布局按叶节点权重递归计算父级面积 |
| `TreemapDataset` | `root_id`, `nodes` | 根节点 ID 与节点列表；恰有一个匹配根，父引用闭合且不能有环 |

每个有序集合最多 512 项；ChartSpec 规范 JSON 最多 256 KiB；文本最多 160 字符。语义校验是确定且无副作用的，最多返回 32 条稳定排序的安全问题，路径使用 JSON Pointer；不修复、截断或重排无效输入。序列化始终输出 schema version 2，并对同一内容保持确定性。

## 4. ChartFigure v2 字段与测量引用

Figure 是有序的完整内容，不接受 patch。`assemble_chart_figure` 的输入必须包含 `schema_version: 2`、`layout` 与 1–4 个 `charts`；可省略的标题和引用在规范序列化时分别表现为空字符串和空数组。

| 模型 | 字段 | 类型与语义 |
|---|---|---|
| `ChartFigure` | `schema_version` | `int`，固定为 2 |
|  | `title` | `str`，默认空文本，最多 160 字符 |
|  | `layout` | `FigureLayout` |
|  | `charts` | 有序 `tuple[ChartFigureItem, ...]`，1–4 项 |
| `FigureLayout` | `columns` | `int`，1 或 2，且不大于子图数；行数由子图数推导 |
| `ChartFigureItem` | `chart_id` | Figure 内唯一 ID，匹配 `[A-Za-z0-9_-]{1,64}` |
|  | `chart_spec` | 完整 `ChartSpecData` v2 |
|  | `measurement_refs` | `tuple[MeasurementRef, ...]`，默认空，最多 16 个且不能重复 |
| `MeasurementRef` | `run_id`, `call_id` | 成功测量工具的实际 `(run_id, call_id)`；不能为空 |

完整 Figure 规范 JSON 最多 64 KiB。Charts 只检查引用形状；装配工具按新鲜 `RunExecutionState` 精确解析引用，且只接受同 Session 授权前缀中已提交成功的 `measure_chart`。失败、未提交、未授权或不存在的引用会使整张 Figure 失败。引用仅表示模型选择了这次观察，不证明 Figure 数据值与观察一致。

## 5. 确定性 PNG renderer

`render_chart_figure_image(value)` 先重新校验 Figure，再按列数和子图顺序渲染十种图表，返回 `(png_bytes, width, height)`。画布尺寸、字体、颜色、标签布局由服务端固定；调用方不能覆盖。散点 `size` 映射为固定范围内的 marker 面积；Pie 的内半径实现 Donut；热力图对非空数值使用线性颜色刻度，Treemap 使用稳定的矩形布局与输入顺序打破权重并列。过长文本、标签冲突、越界或 PNG 超出限制时返回有界失败，不返回部分图片。

PNG 函数不保存文件、不读 Run/Sources，也不审核测量正确性。生产调用由 `render_chart_figure` 工具完成，并由 Sources 私有保存；Agent 只把成功渲染事实投影为 ChartRender 资源。

## 6. 实现与规格依据

- ChartSpec：[`models.py`](../../src/figura/charts/chartspec/models.py)、[`schema.py`](../../src/figura/charts/chartspec/schema.py)、[`codec.py`](../../src/figura/charts/chartspec/codec.py)、[`validation.py`](../../src/figura/charts/chartspec/validation.py)。
- ChartFigure：[`models.py`](../../src/figura/charts/chartfigure/models.py)、[`schema.py`](../../src/figura/charts/chartfigure/schema.py)、[`codec.py`](../../src/figura/charts/chartfigure/codec.py)、[`validation.py`](../../src/figura/charts/chartfigure/validation.py)。
- PNG 绘制：[`rendering.py`](../../src/figura/charts/chartfigure/rendering.py)。
- 主规格：[ChartSpec v2](../../openspec/figura/openspec/specs/chart-spec-core/spec.md)、[Figure 装配](../../openspec/figura/openspec/specs/chart-figure-assembly/spec.md)、[统一图表测量](../../openspec/figura/openspec/specs/chart-family-measurement/spec.md)、[渲染](../../openspec/figura/openspec/specs/chart-rendering/spec.md)。对应 change 已归档，合同以当前主规格为准。
