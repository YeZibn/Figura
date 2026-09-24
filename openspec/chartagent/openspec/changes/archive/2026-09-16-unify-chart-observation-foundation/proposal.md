## Why

Figura 已经分别支持柱状图、折线图、散点图和饼图，但四个传感器仍各自维护图像几何、颜色、关联、质量和输出边界。重复的 frame、坐标、overlay 和字段逻辑会造成行为不一致，尤其容易让柱状图的 baseline、旋转图表和局部证据出现互相矛盾的结果。

现在需要建立一个与具体图表类型无关的图表视觉证据基础设施：统一原图几何、证据身份、关联、置信度、告警和观察输出，同时让 Cartesian2D 与 Polar2D 等坐标模型以及 bar/line/scatter/pie 图形检测保持独立。

## What Changes

- 新增与图表类型无关的基础证据模型，统一 source-image 坐标、尺寸、bbox、polygon、point、polyline、稳定 ID、置信度、告警和结构化错误。
- 将坐标解释抽象为可插拔模型：柱状图、折线图和散点图使用 Cartesian2D，饼图使用 Polar2D；公共基础设施不再以 Cartesian 命名或依赖某一种图表。
- 抽离通用的颜色、图例、系列关联、OCR 证据输入、质量评估和 source-sized overlay 基础逻辑。
- 让四个专用传感器只负责各自的图形检测和测量：bars、line traces、scatter markers、pie sectors。
- 统一四个传感器的结果公共外层结构，并将图形专属字段与公共证据分离；保留有实际语义的 `bars`、`trace`、`points`、`sectors` 等专属证据，只迁移或删除重复、无调用方的布局字段。
- 让柱状图的 baseline 与共享坐标/零点证据进行一致性校验，保留不确定性而不是覆盖可靠的轴证据。
- 统一 overlay 的公共 frame、坐标和告警绘制边界，同时保留各图表的专属标记样式。
- 移除 line、scatter、pie 之间通过具体传感器或 `cartesian.py` 私有函数形成的隐式依赖；Agent 工具选择顺序和 ToolResult 传输协议不变。

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `chart-understanding`: 将四类图表的视觉证据、坐标模型、专用几何、关联、质量和 overlay 统一为清晰的可组合契约，同时保持 Cartesian2D 与 Polar2D 的行为差异。

## Impact

- 影响 `src/chartagent/tools/chart/observation/` 下的公共证据、坐标、传感器和 overlay 模块。
- 影响 `review/manager.py`、图表工具测试、fixture、端到端观察结果和可能读取传感器字段的 mock 数据。
- 不新增运行时图像处理依赖；OCR 仍由 `agent` Conda 环境中的现有边界提供，基础设施只接收文本证据数据。
- 不改变饼图的极坐标测量算法，也不强制 Agent 使用新的统一工具顺序。
- 需要一次性迁移现有传感器输出字段和内部调用方；不涉及持久化 ChartSpec 数据迁移。
