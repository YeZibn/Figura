## Context

当前 `AgentRequestBuilder` 生成完整历史、三层指令、工具 Schema 和执行资源目录，`ProviderClient.prepare` 解析模型选项后生成精确 payload 与指纹。图片在适配器中编码，Provider continuation 只在实际回放时进入消息。

Executor 首次 claim 将 `ProviderRequestBinding` 与 attempt 原子保存；binding 使用 JSON 存于现有表。恢复和重试既比较实际 prepared request 指纹，也比较原 binding 的编码结果。当前 binding codec 只接受 schema version 1 的精确键集合。

Gateway `run_summary` 已拥有完整 RunState；前端现有 controller 通过进度通知与 history compensation 更新 Run summary。无需引入新的计量服务。动机见 proposal.md。

## Goals / Non-Goals

**Goals:**

- 计量归属 Provider，请求快照归属 Runtime，公开摘要归属 Gateway，百分比展示归属前端。
- 一次逻辑请求估算一次；用最近 durable binding 定义“最近一次请求”，避免恢复、失败和重试造成显示漂移。
- 展示值始终可追溯至原 Run 的 Provider/model、原容量和原估算版本。

**Non-Goals:**

- 不估算未发送草稿或下一轮潜在请求，不逐 token 更新输出。
- 不改造 Memory、continuation 回放、工具执行或 Provider 重试策略。
- 不做 usage 校准、多 tokenizer 映射、按 Provider 区分的视觉分词或额外报告。

## Decisions

### 1. 单一 Provider 本地估算模块

新增聚焦模块，例如 `providers/token_estimation.py`，使用官方 `o200k_base` 定义与经过 SHA-256 验证的本地缓存构造共享 `tiktoken.Encoding` 实例，分词结果与 `tiktoken.get_encoding("o200k_base")` 一致，使用 `encode_ordinary` 处理文本。声明直接依赖并锁定经过验证的兼容版本范围。

模块接收 adapter 已形成的 payload，仅投影模型输入 `messages` 和存在时的 `tools`；不计 `model`、timeout、stream、输出控制、thinking 配置、endpoint 或 descriptor。消息中的 role、tool_calls、tool_call_id、reasoning_content 等实际输入字段保留。工具定义完整保留。投影保持数组顺序，以 `ensure_ascii=False`、`sort_keys=True`、紧凑分隔符做确定性 JSON 序列化后一次分词。

这覆盖协议结构的近似开销，但不声称 JSON 序列化就是模型服务端的聊天模板。相比逐字段分词，它只需要一套可复现规则，且不会遗漏工具 Schema。相比字符除以固定系数，它能反映中文、代码、JSON 等文本的分词差异。

只识别已支持 adapter 的真实图片 block，替换其中 image URL/data URL 载荷为统一常量标记，保留有意义的图片选项，并按每次出现增加 1,024 tokens。不按 URL 去重，不读取或再解码图片，不用全局字符串正则移除用户文本。固定图像近似规则属于 `tiktoken-o200k-v1`，以后调整需换版本。

在 prepare 完成有效 payload 构造后附加私有估算结果，作为 `_PreparedProviderCall` 的独立可选元数据；不写入实际 payload、descriptor options 或 asset manifest，不参与指纹。重试 prepare 支持跳过估算，直接保留原 binding。

编码实例在服务初始化阶段尝试预热并复用，编码资源使用安装/部署时准备好的缓存。运行期直接解析已验证缓存并构造官方 Encoding，避免 get_encoding 在缓存丢失时自动下载；测试验证其与官方加载器的分词结果相同。请求路径不主动下载编码资源；缓存不可用时该服务实例禁用估算并给出安全诊断，不阻止 Provider 使用。单次估算发生普通异常时返回无估算，避免输出 payload 或原始异常内容。

### 2. 容量是可选的模型显示配置

`ProviderProfile` 增加 `context_window_tokens: int | None`；使用 `FIGURA_<PROVIDER>_CONTEXT_WINDOW_TOKENS` 配置当前固定模型的容量，正整数有效，缺失、空白或无效值解析为未知，不影响现有 availability。

不猜测当前模型容量，也不先引入可变的在线模型元数据查询。部署者根据实际模型服务合同填写；`.env.example` 说明配置用途，不用未核实的数字填默认。若无容量，产品显示 token 数即可。

### 3. binding 使用独立的版本化计量元数据

新增不可变值对象，字段和所有权如下：

| 字段 | 类型 | 写入时机 / 用途 |
|---|---|---|
| `context_estimate.input_tokens` | 非负整数 | Provider prepare 计算，首次 claim 固化 |
| `context_estimate.context_window_tokens` | 正整数或 null | 复制当前模型配置，作为原请求显示分母 |
| `context_estimate.estimator_version` | 非空字符串 | 固定规则 `tiktoken-o200k-v1` |
| `ProviderRequestBinding.context_estimate` | 上述对象或 null | Runtime 私有持久化，不包含输入副本 |

新增 binding schema version 2，保留 v1 解码与校验。新 binding 即使估算失败，也允许 v2 且 `context_estimate=null`。数字校验拒绝 bool、负数及非法容量。v1 读取在内存中映射为空，但 **v1 编码必须维持原精确键集合与序列化结果**，不能因新增 dataclass 字段就输出额外 null 键；否则现有 retry 的 byte comparison 会拒绝旧绑定。

新增数据使用现有 `payload_json` 存储；不增加计量表，不改 SQL 表结构。实现时验证历史 schema 读取路径与 binding codec 兼容。读取不重算或升级旧记录，不更改 request/retry policy version。新快照和首次 attempt 在现有事务内一起保存，事务失败则两者均不发布。

重试继续使用原对象和编码，容量配置或估算器变化不修改旧 binding。旧 binding 也不补算。响应 usage 按当前事实模型保持原样。

### 4. Gateway 投影最近 binding，不执行计量

`run_summary` 选择 RunState 中 base record sequence 最新的逻辑 binding。它没有估算时公开 null，不退回更早的有值 binding；没有 binding 也公开 null。

公开结构仅为：

```json
{"contextUsage":{"inputTokens":46000,"contextWindowTokens":256000}}
```

示例容量不代表实际模型配置。Provider/model 从 enclosing Run 读取，不公开版本、operation ID、指纹或原请求输入。不增加 health 元数据或新端点。创建 Run 返回的 handle 可以缺省，后续 Session/history Run 摘要返回快照。

首次 claim 后复用现有 activity/progress 与 controller history compensation 的通知路径，使模型等待期间即可读取。检查现有通知是否足以触发 summary reread；若需补充，仍由同一 execution/lifecycle owner 发既有进度通知，不新增 token 事件类型。SSE 序号、事件身份与 reconnect 合同保留。

### 5. 前端依照 Run 快照展示

`FiguraRunDto` 与共享 `RunSummary` 增加可选 `contextUsage`，通过 `api/figura/workspace.ts` 传递，保留 `api/gatewayClient.ts`、`types/protocol.ts` 等兼容 façade。其他模式与无字段旧响应不受影响。

选择当前 active Run；没有 active Run 时取 ordinal 最新的 Run，而非最后一个有估算的 Run。选定 Run 无值显示“上下文待估算”。输入区显示 `上下文 ≈ 18%`；详细提示包含 `约 46,000 / 256,000 tokens`、原请求模型与“根据最近一次模型请求估算，包含指令、工具和历史消息”。无分母则显示 `上下文 ≈ 46,000 tokens`。

百分比 `Math.round(inputTokens / contextWindowTokens * 100)`；正数但不足 1% 时显示 `<1%`。数值可超过 100%，视觉进度填充限制在 0–100%，不禁用提交、不加入警告弹窗。不把新回复计入旧请求、不把未发送草稿计入、也不把服务端 prompt_tokens 或 total_tokens 替换进显示。切换下一 Run 的 Provider 时提示仍标识原 Run 模型，不改变分母。

## Risks / Trade-offs

- [统一编码和图像常数偏离原生 token] → 始终使用“≈”，明确最近请求近似口径，不用于准入或费用结算。
- [准备大型请求增加 CPU 和临时内存] → 单次逻辑请求分词一次，实例复用；不为读接口重复构造请求，不新增历史缓存体系。沿用现有结构化载荷保护。
- [编码首次加载依赖缓存] → 部署时准备编码资源并验证离线初始化，运行期缺失则无估算，避免请求被下载等待阻塞。
- [新增字段破坏 legacy retry 编码比较] → 分版本精确编码测试，并覆盖真实 v1 编码原样往返与重启重试。
- [用户把指标理解成实时草稿容量] → 提示明确最近模型请求；第一版只在请求提交边界刷新。
- [旧版本无法读取新 binding] → 发布后新增 v2 数据不支持直接降级到仅认识 v1 的程序，升级前备份 Runtime 数据。

## Migration Plan

1. 增加依赖、编码资源准备说明、可选容量配置与估算模块；默认容量未知。
2. 升级 binding codec，同时保留 v1 原样编码与读取。无需回填或新增 SQL 表。
3. 接入 Executor、Gateway 和前端可选字段，完成请求等待、失败、重试、刷新和跨 Provider 显示验证。
4. 回退时可通过清空容量配置退回仅 token 数展示；完整代码降级需要还原升级前数据库备份，不能删除 binding 字段来伪造 v1。
