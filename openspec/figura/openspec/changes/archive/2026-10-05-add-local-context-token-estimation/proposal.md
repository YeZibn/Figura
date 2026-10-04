## Why

Figura 已取消通用 Run 调用次数和累计 token 硬上限，但目前没有可用于前端展示的上下文占用数据。需要用统一的本地分词规则估算实际模型请求，让用户了解最近一次请求的上下文占比，同时保持现有执行、重试与历史语义。

## What Changes

- 所有 Provider 统一使用 `tiktoken` 的 `o200k_base`，对实际 prepared payload 中的模型输入做完整估算。
- 计入指令、历史、工具定义、参数、结果和实际回放的 continuation；图片采用统一每张 1,024 tokens 的近似值，排除 base64 文本和传输配置。
- 模型配置支持可选上下文容量，仅作为显示分母；未知容量时显示 token 数。
- 在逻辑请求 binding 中持久化轻量估算快照，兼容旧 binding，重试复用原快照。
- Gateway Run 摘要增加可选 `contextUsage`，前端输入区展示最近一次模型请求的估算占比。
- 本次不增加输出限制、Run 预算、准入校验、压缩、摘要、历史裁断、计量报告或服务端 usage 校准。

## Capabilities

### New Capabilities

- `local-context-token-estimation`: 统一分词编码、输入投影、图片近似、模型容量配置及非阻塞估算行为。

### Modified Capabilities

- `provider-request-retries`: 请求 binding 保存兼容旧版本的估算元数据，重试和恢复不重算、不累加、不改变请求身份。
- `figura-web-gateway`: Session/Run 读取返回最近逻辑请求的安全上下文估算摘要。
- `figura-web-client`: 输入区展示估算 token 和占比，使用现有生命周期读取与兼容适配层。

## Impact

- 后端：`src/figura/providers/`、`agent/executor.py`、Runtime binding 模型与 codec、`gateway/web_projection.py`。
- 前端：Figura DTO、workspace 适配、共享 Run 类型、现有 Run controller 接入及输入区展示。
- 配置和依赖：声明 `tiktoken` 为直接依赖；增加可选模型容量配置；初始化并缓存编码资源。
- 兼容性：仅增加可选元数据和 DTO 字段；保留既有响应 usage、旧历史读取、请求指纹、重试合同、HTTP/SSE 身份和兼容 façade。旧记录不回填或重算。
