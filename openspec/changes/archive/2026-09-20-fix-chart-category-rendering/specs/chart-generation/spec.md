## ADDED Requirements

### Requirement: Line charts render categorical x-axis labels

当有效的折线 ChartSpec 提供 `axes.x.categories` 时，生成结果 SHALL 在横轴上显示与
ChartSpec 完全一致的类别文本和顺序，并使每个系列在相同类别位置对齐。类别标签的
可读性布局（包括必要的间距或旋转）不得改变类别顺序、丢失标签，或把类别轴降级为
未解释的数字刻度。没有类别域的折线图 SHALL 继续使用数值横轴。

#### Scenario: Monthly categories are visible in the rendered line chart

- **WHEN** 渲染包含 `Jan` 至 `Jul` 类别的单系列或多系列折线 ChartSpec
- **THEN** 生成图片的横轴显示 `Jan`、`Feb`、`Mar`、`Apr`、`May`、`Jun`、`Jul`
- **AND** 标签顺序与 ChartSpec 一致，折线点按对应类别位置绘制
- **AND** 图片不得仅显示 `0`–`6`、`1`–`7` 等未解释的数字刻度

#### Scenario: Multiple series share the same category positions

- **WHEN** 多个折线系列使用同一组类别域
- **THEN** 每个系列在每个类别位置使用同一横坐标
- **AND** 系列身份、点数和 y 值保持不变

#### Scenario: Numeric x-axis remains numeric

- **WHEN** 折线 ChartSpec 未声明类别域并使用数值 `x`
- **THEN** 生成结果继续按数值横轴绘制和显示
- **AND** 系统不得将数值刻度误替换为不存在的类别文本

### Requirement: Category fidelity is part of deterministic render auditing

对于声明了类别横轴的折线图，生成前后的确定性检查 SHALL 验证类别刻度的数量、文本、
顺序以及数据点到类别位置的映射。任何缺失、错序、错文本或映射不一致 SHALL 产生
可定位的语义/保真问题，并阻止该候选以通过状态发布。

#### Scenario: Missing line tick labels fail the audit

- **WHEN** 渲染器生成了折线，但最终图的横轴类别标签缺失、被数字刻度替代或顺序不同
- **THEN** 审计返回定位到横轴类别或数据映射的结构化失败
- **AND** 候选图不会以 verified 或 published 状态返回

#### Scenario: Correct line category labels pass the audit

- **WHEN** 最终图的类别标签、顺序、数量和所有系列的横坐标映射均与 ChartSpec 一致
- **THEN** 类别保真检查通过
- **AND** 该检查结果与其他语义、布局和 artifact 检查一起参与发布门禁
