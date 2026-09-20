# chartspec Specification

## Purpose

Defines `ChartSpec`, the shared intermediate representation (IR) between the
understanding and generation sides: a serialization-friendly, documented data
model that carries a chart's metadata, axes, and dataset, with a structural
validator so both directions exchange data through one stable contract.

## Requirements

### Requirement: ChartSpec data model

The system SHALL provide a `ChartSpec` data class expressing a chart's
structure for both directions of ChartAgent, composed of chart metadata, chart
type, axes, and a dataset, and SHALL provide serialization to and from plain
dictionaries via `to_dict` and `from_dict`.

#### Scenario: A spec round-trips through dict

- **WHEN** a `ChartSpec` with metadata, axes, and a dataset is converted with
  `to_dict` and rebuilt with `from_dict`
- **THEN** the rebuilt spec equals the original spec

### Requirement: Chart type enumeration

The system SHALL model a chart's type as a closed `ChartType` enumeration
covering common kinds (e.g. bar, line, pie, scatter), so downstream consumers
can switch on a fixed set of values.

#### Scenario: A supported chart type is accepted

- **WHEN** a spec is constructed with a type from the `ChartType` enumeration
- **THEN** the spec holds that type and validation reports no type error

### Requirement: Axes conditional on chart type

The system SHALL require axes for cartesian chart types (bar, line, scatter)
and SHALL allow axes to be absent or empty for pie, so `validate()` judges axes
presence against the declared chart type rather than uniformly.

#### Scenario: Cartesian type without axes reports an issue

- **WHEN** a bar, line, or scatter spec is validated with missing or empty axes
- **THEN** `validate()` returns a problem locating the axes

#### Scenario: Pie without axes validates clean

- **WHEN** a pie spec carries a valid dataset but no axes
- **THEN** `validate()` returns an empty list

### Requirement: Structured validation

The system SHALL provide a `validate()` method that returns a structured list
of validation problems (each with the offending location and a message) rather
than raising a bare exception, so consumers can collect and respond to all
issues at once.

#### Scenario: Invalid data reports an issue list

- **WHEN** a spec carries invalid data (e.g. a dataset point missing a required
  value or an empty axes label)
- **THEN** `validate()` returns a non-empty list of problems describing each
  issue, without raising an uncaught exception

#### Scenario: Valid spec validates clean

- **WHEN** a spec has valid metadata, axes, and a dataset
- **THEN** `validate()` returns an empty list

### Requirement: Dataset as a list of typed points

The system SHALL represent the dataset as a list of typed data points (e.g.
explicit categories/values, or x/y pairs), so both a human and a renderer can
iterate over the restored or to-be-rendered values uniformly.

#### Scenario: Series can be enumerated

- **WHEN** a spec's dataset contains multiple points across series
- **THEN** consumers can iterate the points and read each point's values

### Requirement: Understanding-side provenance fields

The system SHALL allow understanding-side provenance to be carried on the spec
optionally (e.g. per-point measurement confidence and the source chart), without
requiring them for generation, so the understanding pipeline can attach
traceability without burdening the generation side.

#### Scenario: Provenance is optional

- **WHEN** a spec is built with provenance fields present, and another built
  without them
- **THEN** the first carries the provenance values and both validate clean,
  since provenance is optional

### Requirement: ChartSpec assembly supports independent child specs

ChartSpec 装配 SHALL 支持把多个独立的 ChartSpec 作为同一 figure 或集合的子项进行构建，同时保留每个子项原有的图表类型、数据点、类别顺序、系列身份、轴和来源元数据。装配过程不得通过合并同名类别来改变子项语义。

#### Scenario: Independent pie specs keep their own categories

- **WHEN** 装配两个来自同一面板的饼图 ChartSpec，且两个子图分别代表 Q1 和 Q2
- **THEN** 每个子项保留自己的类别和值
- **AND** 两个子项可以被集合通过稳定 ID 单独引用
- **AND** 装配结果不会生成一个含有重复类别的普通饼图

### Requirement: Single ChartSpec assembly remains compatible

新增集合能力 SHALL 保持原有单 ChartSpec 装配输入、输出和结构化错误语义兼容。调用方仅提交一个 ChartSpec 时，系统 SHALL 继续返回单图结果，不得强制调用方先包装成集合。

#### Scenario: Existing single-chart request is unchanged

- **WHEN** 调用方提交现有格式的单个 bar、line、pie 或 scatter ChartSpec 请求
- **THEN** 系统按照原有单图路径完成校验和返回
- **AND** 返回结果不要求调用方提供 figure 或 collection 字段

### Requirement: Assembly reports collection-level issues

当装配请求包含多个子图时，系统 SHALL 返回能够区分集合、figure 和子图位置的结构化问题。集合级错误不得被压缩成无法定位的单一字符串。

#### Scenario: Missing source identity is located

- **WHEN** 多子图装配请求缺少 `attachment_id` 或 `panel_id`
- **THEN** 系统返回指出来源字段位置的结构化错误
- **AND** 不生成来源不明的集合或 figure

### Requirement: Source-derived ChartSpec can identify accepted measurement provenance

源图恢复得到的 ChartSpec SHALL 能够关联其使用的已接受测量证据摘要或引用，包括源附件、面板和测量 attempt 身份；该 provenance SHALL 用于判断数据是否经过测量质量门禁，而不是把自由文本 source 标签当作证据。

#### Scenario: Assembled data points reference accepted evidence

- **WHEN** ChartSpec 的数据由某个 panel 的 accepted measurement attempt 提供
- **THEN** ChartSpec 或其受控 provenance 能够识别该 attachment、panel 和 attempt
- **AND** 下游可以区分该数据与未绑定来源的直接视觉输入

#### Scenario: Unaccepted provenance cannot be presented as verified

- **WHEN** ChartSpec 仅关联 provisional、partial 或 failed 的测量 evidence
- **THEN** 组装或发布链路保留未接受状态并返回结构化问题
- **AND** 不得把该 ChartSpec 宣称为已经由源图测量确认的数据

### Requirement: Measurement provenance does not break direct ChartSpec compatibility

测量 provenance SHALL 对没有使用测量工具的现有单 ChartSpec 输入保持可选。已有 metadata、axes、dataset 和结构化校验语义不得因为新增 provenance 关联而被迫包装成 MeasurementSession。

#### Scenario: Legacy single ChartSpec remains valid

- **WHEN** 调用方提交没有 measurement provenance 的合法单图 ChartSpec
- **THEN** ChartSpec 仍可按现有规则序列化、校验和交给生成流程
- **AND** 只有在调用方声明使用测量证据时才执行对应的接受状态检查

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
