# Validation：共享 JSON Schema 合同

> [返回总览](../figura-implementation-overview.md)。`figura.shared.json_schema` 与 `figura.shared.image_limits` 是多个能力复用的基础合同；它们不属于 Agent、Provider 或 Tool 的业务事实。

## 1. 职责与边界

共享校验模块规范化有界 JSON 值，验证受支持的 JSON Schema 子集，并返回不回显原始输入的 `SchemaIssue`。工具定义和运行时使用它校验参数/结果；ChartSpec Core 的 Schema 也须符合其支持的方言。各领域仍拥有自己的语义校验规则。

## 2. 内部流转

`validate_schema_definition` 检查 Schema 形状、深度、属性、关键字和大小；`validate_instance` 先规范化输入和 Schema，再返回首个安全问题或 `None`。工具运行时把这些问题翻译到自己的 `ToolExecutionError`，图表内容则有独立的 `ChartSpecIssue`；共享层不接管它们的错误所有权。

## 3. 完整模型字段

### SchemaIssue

JSON Schema 验证的无 payload 问题。 **写入者：**`figura.shared.json_schema`。**权威位置：**调用期。**读取与公开：**ToolRuntime/Schema 调用方；不回显输入值。[定义](../../src/figura/shared/json_schema.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| SchemaIssue.code | str | 必传 | 稳定错误/问题码 | `figura.shared.json_schema` → 调用期 → ToolRuntime/Schema 调用方；不回显输入值 |
| SchemaIssue.pointer | str | '' | JSON Pointer 问题路径 | `figura.shared.json_schema` → 调用期 → ToolRuntime/Schema 调用方；不回显输入值 |

## 4. 依据

代码：[共享 JSON Schema](../../src/figura/shared/json_schema.py)、[图像限制](../../src/figura/shared/image_limits.py)。`JsonValueError` 和 `SchemaDefinitionError` 是异常机制；后者携带 code/pointer，但不是持久领域模型。
