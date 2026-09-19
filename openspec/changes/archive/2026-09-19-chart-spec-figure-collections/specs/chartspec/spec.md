## ADDED Requirements

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
