# Validation：共享 JSON Schema 合同

> 核对日期：2026-10-03。[返回总览](../figura-implementation-overview.md)。`figura.shared.json_schema` 与 `figura.shared.image_limits` 是多个能力复用的基础合同；它们不属于 Agent、Provider 或 Tool 的业务事实。

## 1. 职责与边界

共享校验模块规范化有界 JSON 值，验证受支持的 JSON Schema 子集，并返回不回显原始输入的 `SchemaIssue`。工具定义和运行时使用它校验参数/结果；ChartSpec Core 的 Schema 也须符合其支持的方言。各领域仍拥有自己的语义校验规则。

## 2. 内部流转

`validate_schema_definition` 检查 Schema 形状、深度、属性、关键字和大小；`validate_instance` 先规范化输入和 Schema，再返回首个安全问题或 `None`。工具运行时把这些问题翻译到自己的 `ToolExecutionError`，图表内容则有独立的 `ChartSpecIssue`；共享层不接管它们的错误所有权。

## 3. 完整模型字段

### ExecutionPayloadLimits

| 完整字段路径 | 类型 | 默认 | 语义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| ExecutionPayloadLimits.max_json_bytes | int | 33,554,432 | 完整执行 JSON 单元的 UTF-8 字节 guard，有限正整数；由 FIGURA_EXECUTION_PAYLOAD_MAX_BYTES 解析 | 组合根 → 不可变配置实例 → Runtime/Provider/Registry/Gateway；不进 prompt |

实际 JSON container depth 固定64，根容器深度0，不按 Schema 语义层计数。编码使用 compact UTF-8、排序对象 keys、保留数组顺序；拒绝重复 keys、非有限数、非法 Unicode、非 JSON 值。编码前以最小可能字节数限制规范化副本，接收先检查字节/深度再严格解析。配置是每个完整单元的物理保护，无 Run 累计 bytes/token/time 限额。

| 范围 | 删除的通用微限制 | 保留的合同 |
|---|---|---|
| Run | 8 Provider attempts、32 started tools、模型轮次、累计 token/time/bytes | 每逻辑 Provider operation 4 attempts；未知 Tool call 3 attempts；stop/CAS/独占 owner |
| Provider | messages256、instructions32、tools/calls64、text1 MiB、completion131072、默认4096、images16、timeout600 | 完整 JSON guard、真实 adapter 能力、positive optional completion、positive finite timeout |
| Tool/codec | registry64、Schema/description/args/result/batch 微字节限、call ID256、generic name64 | 完整 Registry/observation/fact/batch guard、非空有效身份、唯一/配对、名称字符集、领域 Schema |
| 共享 JSON | properties256、enum256、Schema depth16 | 实际容器 depth64、JSON/Schema 正确性、领域 maxItems/maxLength |
| 隐私与协议 | 无 | message512 B、pointer256 B、terminal256 B、event16 KiB；公共投影 allowlist |
| 图像/并发/领域 | 无 | 单图24 MiB减64 B、Provider原图总量32 MiB、格式/像素安全、3 worker/8 queue、Sources/Charts/Measurement 限制 |

完整 Registry、结构化 Provider request、整个 model response+intents+continuation、单 record/fact/continuation、工具 observation 都各自有完整单元校验；arguments 的字符串 escaping 按 envelope 真实编码计算。图像 metadata/digest 占位计 JSON，raw bytes另行校验。部署 guard 降低后的历史读上限由 [Runtime metadata](runtime.md#持久重试和-schema-v11) 管理。

### SchemaIssue

JSON Schema 验证的无 payload 问题。 **写入者：**`figura.shared.json_schema`。**权威位置：**调用期。**读取与公开：**ToolRuntime/Schema 调用方；不回显输入值。[定义](../../src/figura/shared/json_schema.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| SchemaIssue.code | str | 必传 | 稳定错误/问题码 | `figura.shared.json_schema` → 调用期 → ToolRuntime/Schema 调用方；不回显输入值 |
| SchemaIssue.pointer | str | '' | JSON Pointer 问题路径 | `figura.shared.json_schema` → 调用期 → ToolRuntime/Schema 调用方；不回显输入值 |

## 4. 依据

代码：[共享 JSON Schema](../../src/figura/shared/json_schema.py)、[图像限制](../../src/figura/shared/image_limits.py)。`JsonValueError` 和 `SchemaDefinitionError` 是异常机制；后者携带 code/pointer，但不是持久领域模型。
