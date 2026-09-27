## Why

Figura 已有持久 Run、工具运行时和图片附件，但还没有统一、可验证的图表数据表达。ChartSpec Core 为后续工具组装、来源追踪和图表渲染提供稳定的单图语义合同，避免各阶段分别解释图表字段。

## What Changes

- 新增版本化的单图数据模型，覆盖 bar、line、pie、scatter 四种图表类型。
- 为 ChartMetadata、DataPoint、Axes 和 Axis 定义封闭字段、严格解析、规范序列化和有界文本/数据点限制。
- 提供纯领域校验，检查图表类型与数据形状、类别和系列唯一性、轴范围、数值有限性及图型专属约束，并返回稳定的字段路径问题。
- 将图表内容模型与 Run 身份、来源证据、工具组装、持久化及渲染分开；这些能力由后续 change 引入。

## Capabilities

### New Capabilities
- `chart-spec-core`: 定义 Figura 单图语义模型、版本化序列化、严格解析和生成前结构/语义校验。

### Modified Capabilities
- 无。

## Impact

- 新增 `src/figura/chartspec/` 领域模块及对应测试。
- 新增 Figura OpenSpec 主能力规格；不修改旧版 `src/chartagent/` 或其 OpenSpec store。
- 本 change 不注册工具，不修改 Run/SQLite schema，不写入附件或产物，不生成或发布图像；不新增第三方依赖。
