## ADDED Requirements

### Requirement: Categorical Cartesian axes preserve ordered labels

当 cartesian ChartSpec 的 `axes.x.categories` 被提供时，系统 SHALL 将其视为
横轴的有序、离散类别域，并与 `axes.x.label`（轴标题）严格区分。类别域的顺序
和文本 SHALL 在序列化、装配和生成链路中保持不变；数据点 SHALL 能够被无歧义地
映射到该域中的位置。未提供类别域时，系统 SHALL 保留数值型横轴语义。

#### Scenario: Line categories survive the ChartSpec boundary

- **WHEN** 一个折线 ChartSpec 提供 `Jan`、`Feb`、`Mar` 的有序类别和对应的数值位置
- **THEN** `to_dict`/`from_dict`、集合装配和后续生成输入仍保留这三个类别及其原始顺序
- **AND** `axes.x.label` 仅作为轴标题，不得替代或覆盖类别标签

#### Scenario: Category mapping is unambiguous

- **WHEN** 类别型 cartesian ChartSpec 的数据点无法映射到类别域、位置超出类别域，或
  类别数量与数据位置不一致
- **THEN** `validate()` 返回包含具体字段位置的结构化问题
- **AND** 系统不得把该数据点静默映射到另一个类别或补成确定值

#### Scenario: Numeric line axes remain compatible

- **WHEN** 折线或散点 ChartSpec 未提供 `axes.x.categories`，但提供合法的数值 `x`
- **THEN** ChartSpec 继续按数值型横轴语义通过结构校验
- **AND** 不要求调用方额外伪造类别标签

### Requirement: ChartSpec assembly preserves categorical axis evidence

`assemble_spec` 的单图和 figure 子图输入 SHALL 支持可选的有序横轴类别字段，并在
构建 line、scatter 或其他适用 cartesian ChartSpec 时原样保留为 `axes.x.categories`。
当调用方未提供该字段时，装配 SHALL 保持现有数值横轴兼容行为；当调用方提供类别时，
装配不得只保留 `x_label` 而丢弃类别文本。

#### Scenario: Assembly carries line tick labels into ChartSpec

- **WHEN** line 子图输入包含 `x_label: "Month"`、`x_categories: ["Jan", "Feb", "Mar"]`
  和对应的 numeric x/y points
- **THEN** `assemble_spec` 成功结果的 `axes.x.label` 为 `Month`
- **AND** `axes.x.categories` 保持 `Jan`、`Feb`、`Mar` 的原始顺序

#### Scenario: Figure child preserves its own category domain

- **WHEN** 同一个 figure 中的某个 line 子图提供自己的 `x_categories`，其他子图使用
  不同类别或没有类别
- **THEN** 每个子图的 ChartSpec 只携带自己的类别域
- **AND** 装配不得把不同 panel 或不同子图的类别拼接到一起

#### Scenario: Missing category input keeps numeric compatibility

- **WHEN** line/scatter 装配输入只提供 `x_label`、`y_label` 和 numeric points
- **THEN** `assemble_spec` 成功结果不强制生成类别列表
- **AND** 该结果继续按数值型横轴交给生成器
