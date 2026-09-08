# Tasks: add-chartspec

## Requirements

- [x] T1: 建立 `src/chartagent/spec/` 包，添加 `__init__.py` 导出 `ChartSpec`, `ChartType`, `DataPoint`。
- [x] T2: 在 `src/chartagent/spec/chartspec.py` 定义 `ChartType` 枚举（bar/line/pie/scatter）。
- [x] T3: 定义 `DataPoint` 数据类，支持单值（类目+值）与 x/y 坐标两种形态。
- [x] T4: 定义 `ChartSpec` 数据类，含 `metadata`、`axes`（可选，默认 `None`）、`dataset` 字段；`metadata` 含标题、类型、可选来源与理解侧 provenance。
- [x] T5: 实现 `ChartSpec.to_dict()` / `classmethod from_dict()`，可往返、`from_dict` 容忍未知字段与缺失可选字段。
- [x] T6: 实现 `ChartSpec.validate()` 返回 `list[ValidationIssue]`（含 location 与 message），不抛裸异常；axes 存在性按图型条件化——bar/line/scatter 缺 axes 报问题，pie 有无 axes 均合法。
- [x] T7: `tests/test_chartspec.py` 覆盖：round-trip 相等、ChartType 封闭性、非法数据返回问题列表、合法 spec 验证干净、provenance 可选、笛卡尔类型缺 axes 报问题、pie 无 axes 验证干净。

## Engineering Notes

- 零新依赖，用 dataclasses + enum。
- `ValidationIssue` 用 NamedTuple 或简单 dataclass。
- 尽量让 `from_dict` 的未知字段策略与容错显式化并测试。