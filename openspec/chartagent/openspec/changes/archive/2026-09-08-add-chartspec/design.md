# Design: add-chartspec

## Context

ChartAgent 是双向架构，理解侧与生成侧通过一个共享 IR 交换图表语义。本 change 只定义这个 IR（`ChartSpec` 数据模型 + 校验契约），不实现任何算法。设计目标是 zero-dependency、可序列化、可测试、对两侧都友好。

## Key Decisions

### D1: 纯 Python 数据类（Option A）

用 `dataclasses` 实现 `ChartSpec`，不用 pydantic。理由：
- 与现有代码风格一致（工具系统、client 均为纯 Python）。
- 零新依赖，契合项目 "最小依赖" 的约求。
- schema 通过字段类型 + `validate()` 显式表达，已在 spec 中定义为返回问题列表而非抛异常。

### D2: `ChartType` 用 `enum.Enum`

封闭枚举，避免 magic string 漂移。覆盖 bar / line / pie / scatter 作为起步集合，后续可按需扩展。

### D3: 结构拆分为 metadata / axes / dataset 三块

- `metadata`：标题、图表类型、可选来源与备注、理解侧 provenance。
- `axes`：x/y（或值/类目）的 label 与取值信息。
- `dataset`：`list[DataPoint]`，每点含类目/坐标与值，可跨 series。

### D4: 序列化契约 `to_dict` / `from_dict`

对称且可往返（round-trip 相等），保证两侧与外部（JSON、网络、文件）可交换。

### D5: axes 按图型条件化

不同图型对 axes 的需求不同：bar/line/scatter 是笛卡尔图，必须有 axes；pie 没有坐标轴。因此：
- `ChartSpec.axes` 字段类型为可选（`Optional[Axes]`，默认 `None`）。
- `validate()` 按 `chart_type` 判定：笛卡尔类型缺 axes → 报问题；pie 有无 axes 均合法（有 axes 也不报错，宽容持有）。
- 该规则集中在一处（`validate()` 内的类型→约束映射），后续新增图型只改这张表。

## File Layout

```
src/chartagent/spec/__init__.py      # 导出 ChartSpec, ChartType, DataPoint
src/chartagent/spec/chartspec.py     # ChartSpec 数据类、ChartType、DataPoint、validate
tests/test_chartspec.py              # 单元测试
```

`from_dict` 需容忍未知字段（丢弃）与缺失可选字段（用默认值），以保持 schema 演进兼容。

## Validation Semantics

`validate()` 返回 `list[ValidationIssue]`，每项含 `location`（如 `"dataset[2].value"`）与 `message`。返回空列表表示完全合法。未知内容不改动数据、不静默吞错——所有问题都进结果列表。

## Open Questions

- series 的表示：先以单系列为主（每点一个值），多系列作为可扩展字段预留。待理解侧工具真正落地再细化。非本 change 阻塞项。

## Risks

- schema 过设计：通过"最小字段集 + 可选 provenance"控制范围，能承载 U0（带数字标注柱状图）即可。
- 过度抽象：data point 保持扁平，不引入跨维度抽象层。