## Why

当前 `render_chart` 使用 Matplotlib 默认的 DejaVu Sans，无法覆盖中文字符，导致标题、坐标轴、图例和数据标签出现 Glyph 警告或方框。Figura 的主要界面和分析内容是中文，现在修复字体渲染可以让生成图表真正可读，并为不同运行环境提供可诊断的降级行为。

## What Changes

- 增加跨平台中文字体解析，支持通过 `CHARTAGENT_FONT_PATH` 指定字体。
- 在柱状图、折线图、饼图和散点图中统一应用解析出的字体到所有用户可见文字。
- 在无法找到中文字体时保留可用的 fallback，并返回明确的字体状态或 warning。
- 增加覆盖中文标题、轴标签、刻度、图例、分类标签和数值标注的渲染测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `chart-generation`: 生成图表必须正确处理中文文字，并对字体 fallback 或不可用状态提供明确诊断。

## Impact

- 主要影响 `src/chartagent/tools/chart/generation.py` 及其测试。
- 可能增加字体发现或渲染辅助代码，但不新增 Python 运行时依赖。
- 不修改 `ChartSpec`、Gateway API、artifact 格式或前端协议。
