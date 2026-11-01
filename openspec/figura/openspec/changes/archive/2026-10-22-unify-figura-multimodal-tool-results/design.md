## Context

动机见 [proposal.md](proposal.md)。本设计针对 `src/figura`，不修改旧 chartagent。

当前事实：
- `tools/contracts.py` 的成功结果仅含 JSON；`memory/models.py` 的 ToolMessage 只含字符串。
- `agent/request.py` 在对话末尾调用 `build_observation_messages`；`agent/prompting/observations.py` 按工具名推断图片并组成普通 user 消息。
- `agent/execution_images.py` 临时重绘 OCR／测量标注图；ChartRender PNG 已由 Sources 按原 Run/call 私有保存。
- Provider 的通用校验只允许 user 图片；序列化器本身已有文本／图片内容块能力。
- 当前 RunExecutionState 是从 Sources 和已提交 Run 事实派生的目录，顶层只有 run_id、resources；Prompt 使用筛选后的定位投影。
- Provider 请求通过 prepare/claim/dispatch 绑定精确 payload、资产摘要和指纹。当前 schema 为 13；本 change 实施时再依据实际 schema 分配后继版本。

参考边界：
- [Claude tool results](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)：外层 user 可以承载有 tool_use_id 的类型化 tool_result；不能将其等同于普通 user 图片消息。
- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)：Responses 支持图像／文件函数输出。本次不据此迁移 Figura 的全部请求协议。
- [LangChain multimodal tools](https://docs.langchain.com/oss/python/langchain/tools#return-multimodal-content)：模型可见 content 与仅供应用使用的 artifact 不等价。
- [MCP result contract](https://modelcontextprotocol.io/specification/2025-06-18/server/tools#tool-result)：结构化结果和有序多模态内容可并存。
- [DeepSeek Chat Completions](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/) 文档明确声明 tool.content 支持文本／图片内容块。文档支持不是实际识别验收。

## Goals / Non-Goals

**Goals**
- 每个调用只有一个逻辑工具结果；结构化数据、图像附件和观察 hint 具有可验证的关联。
- 事实、资源目录、历史读取和 Provider 使用同一资源引用；媒体可恢复且不重复创建业务产物。
- 九个 handler、结果编解码和请求投影一次切换，在线只有一种输出合同。
- 附图失败在正确边界报告；历史图片不因请求投影省略而丢失。
- 既有 Session 授权、完整交互压缩、流式请求、重试绑定和网页安全边界继续成立。

**Non-Goals**
- 不修改 ChartSpec、ChartFigure、测量数值算法或 OCR 业务字段；不引入审核服务、强制 verify、第二个 Agent 或新执行队列。
- 不新增任意 URL／路径图片读取、媒体上传 API、通用文件／音视频框架或媒体结果数据库。
- 不重做 80% 压缩触发、各约 10% 的软预算或图片估算口径；不引入累计 Run 配额。
- 不通过普通 user 附图、丢弃图片、自动切 Provider／协议来兼容不支持的接口。
- 一次性迁移不构成在线兼容层；不保留旧 handler 返回对象升级器或旧附图管线。

## Decisions

### 1. Provider-neutral 值类型与唯一所有者

| 位置／owner | 合同 | 责任 |
|---|---|---|
| shared/resource_refs | ImageResourceRef、ToolResourceRef、ResourceRef | 复用既有字段，移出 Agent；不新增另一套资源 ID |
| shared/media | ImageKind、ResourceImage、ToolImageAttachment | 中立媒体值；不依赖 Agent、Provider、Runtime 仓储 |
| Tools | ToolOutput、ToolImageOutput、ToolExecutionResult | handler 输出、业务和媒体校验、调用关联 |
| Sources | 私有媒体安装／解析、会话暂存删除 | 图片字节和存储完整性 |
| Runtime | ToolResultFact.attachments | 唯一已提交附件描述，与原结果同一事实 |
| Memory | ToolMessage 的结构化观察字段 | 不读文件的规范历史投影 |
| Agent | 资源目录、图片发送选择、hint、内容块水合 | 模型本次实际看到什么 |
| Provider | 原生编码和能力验证 | 保持调用关联，拒绝不能忠实表示的组合 |

只移动公共引用值类型；RunExecutionState 和资源目录重建仍由 Agent 拥有。Sources 的 Attachment/Panel resolve 改为返回中立 ResourceImage，不再返回 Provider.ImageBlock。所有直接调用方在本 change 中迁移，不保留 re-export 兼容门面。

### 2. 唯一工具输出合同

成功 handler 统一返回 `ToolOutput(result, images)`；失败继续抛受控 ToolFailure。九个定义全部迁移；纯 dict、dict/ToolOutput 联合输入以及 result_schema 外塞图片字节均拒绝。

| 模型字段 | 类型／约束 | 生命周期 |
|---|---|---|
| ToolOutput.result | Mapping[str, JSONValue]，严格符合原工具 result_schema | handler → ToolRuntime |
| ToolOutput.images | tuple[ToolImageOutput, ...]，可空，有序 | 调用期候选，不持久化 |
| ToolImageOutput.resource_ref | 完整 ResourceRef | 原图指向原资源；新 OCR／测量／渲染指向当前逻辑调用资源 |
| ToolImageOutput.image_kind | ImageKind | 选择 hint 的唯一业务 discriminator |
| ToolImageOutput.provenance | recorded / migration_reconstructed | 新生产图片只能为 recorded；读取历史媒体必须沿用已提交描述，不能自行更改来源 |
| ToolImageOutput.image | ResourceImage | 媒体类型、字节、宽高；只在调用期存在 |
| ResourceImage.media_type | 支持的已验证媒体类型 | 不接受模型传入 |
| ResourceImage.image_bytes | 非空 bytes，repr 隐藏 | 不进入事实、事件、普通日志 |
| ResourceImage.width / height | 真实正整数尺寸 | 必须与解码一致 |
| ToolExecutionResult.attachments | tuple[ToolImageAttachment, ...]，必有字段、默认空 | 规范化后只含描述，不含字节 |
| ToolResultFact.attachments | 同上，序列化时必有数组 | 同一结果事实持久化 |

ToolExecutionResult 原有 call_id、tool_name、outcome、result、error 语义保留。失败必须 result=null、error 非空、attachments=[]；成功必须 result 非空、error=null。ToolRuntime 先校验业务结果、完整 JSON 描述和所有媒体，再完成媒体安装和规范化输出，不裁剪已验证结果。

每个 ToolImageAttachment 的完整字段：

| 字段 | 约束与语义 |
|---|---|
| resource_ref | attachment/panel 使用 kind+id；其余使用 kind+run_id+call_id |
| image_kind | original / ocr_annotation / measurement_annotation / rendered |
| media_type | image/jpeg、image/png、image/gif、image/webp；标注与渲染固定 PNG |
| width、height | 与实际文件一致的正整数 |
| byte_count | 实际原始字节数 |
| sha256 | 实际字节 SHA-256；不等于逻辑资源 ID |
| provenance | recorded / migration_reconstructed；重载保留原值 |

image_kind 与 resource_ref.kind 必须匹配；original 只对应 Attachment/Panel，其他三类分别对应 OCR、measurement、chart_render。新产生的资源引用必须与当前 Run/call 相等；重载的引用必须已在授权目录中。模型不能通过参数提交附件描述或私有存储键。

provenance 是媒体来源事实，不是旧格式分支；新合同的所有记录都使用同一字段集。migration_reconstructed 只允许一次性迁移生成的旧 OCR／测量标注媒体，不能宣称是原始反馈图片。

采用现有 result + 附件描述，而不是额外保存一份序列化 JSON 文本；模型文本在投影时生成一次。也不把图片仅放入应用私有 artifact 而误认为模型已经看见。

### 3. 九个工具的媒体输出

| 工具 | images 与规范附件 |
|---|---|
| load_image | 一个 original，指向选定 Attachment/Panel |
| extract_text | 一个 ocr_annotation，来源为当前 OCR 资源；available=false 或空 snippets 也可绘制如实的空观察标注图 |
| measure_chart | 一个 measurement_annotation，保留部分／不支持／空观察的原质量状态 |
| render_chart_figure | 一个 rendered，指向当前 ChartRender，元数据与 result 的 PNG 摘要完全一致 |
| read_resource_image | 一个原资源图片，类型与 provenance 由被读取资源决定 |
| decompose_chart_image | images=[]，返回 Panel 引用；不隐式加载新 Panel |
| assemble_chart_figure | images=[]，返回 Figure 引用和摘要 |
| search_history / read_history | images=[]；数据中可含附件引用，但不隐式读取媒体 |

在工具执行阶段完成标注绘制，移除请求构建和 Gateway 的绘图依赖。图像工具成功意味着承诺返回的图片已经准备完毕；不能默默去掉附件并仍报告新调用成功。

已知且效果已确定的图像生成／安装／校验失败使用安全错误 `image_feedback_unavailable` 或已有更精确错误。不能因为 PNG 准备失败捏造全局业务失败；若写操作效果未知，继续遵守现有 ToolOutcomeUnknown 路径，不能提交伪装为已知失败的结果。模型自主决定新调用，错误不触发自动工具重试。

### 4. Sources 安装、发布与恢复

- Attachment、Panel 和 ChartRender 复用现有私有文件与身份，不复制成第二份原图／生成图。
- 新 OCR／测量标注图片安装到 Session 私有、按内容摘要定位的媒体区；路径由服务端组成，不接受模型指定。以原子安装、fsync、不可变内容和相同摘要去重保证可重复安装。
- ToolRuntime 通过注入的通用媒体提交器校验／安装临时媒体，形成描述；Sources 不接收 Prompt、ProviderMessage 或 hint。
- 基础设施媒体安装的幂等性不改变 handler 的业务 replay_effect；OCR／测量仍为 replay_safe，现有渲染业务写入仍保持 idempotent_local_write。
- 先完成媒体安装，再由原事务提交 ToolResultFact(result/error/attachments)、tool sequence、checkpoint 与进度事件。数据库与文件不假装属于同一个事务。
- 文件存在而无成功事实时，不进入资源目录、工具时间线图片读取或 Provider 请求；未提交候选可在合规恢复时重算。
- 重算产生新结果时按新图片指纹安装，不能仅凭相同 call_id 复用旧标注 PNG。已提交结果永远匹配其附件指纹。
- 只有确认无活动写入的启动前／独占维护阶段可清理无引用媒体；不得在 Sources 构造时不加所有权检查地删除在途文件。
- 整会话删除暂存同 Session 媒体区，与原 Sources 删除流程一起恢复／清理；读工具不创建新资源文件。恢复只读、Gateway 读取和 Provider prepare 都不补绘或修复缺失图片。

### 5. Memory、资源目录和检索

Memory.ToolMessage 改为 run_id、run_ordinal、source_tool_sequence、tool_call_id、outcome、result、error、attachments 的中立结构；不再权威保存 `content: str`。用于历史读取／摘要的 JSON 文本由统一观察序列化器生成，不能各层各自拼装不同业务 envelope。

RunExecutionState 顶层 run_id/resources 不变。已提交 OCR／measurement／ChartRender content 派生附件描述；不把完整目录另存数据库。Prompt 索引只添加图片是否可读及 image_kind 等定位信息，不复制完整结果、图片字节或 hint。服务端完整目录与筛选后的 Prompt 索引分离，水合从完整目录读取并校验已选附件，不能用 Prompt 子集代替授权目录。

read_history 返回原始结构化结果／错误和附件描述，保留既有 reference、selector、range、trust 规则；不读取图片。search_history 返回完整稳定引用。read_resource_image 使用完整授权前缀解析，读取已保存图片并校验所有元数据；不新建旧资源、不重跑业务工具、不重新绘制标注图。

原资源引用与当前读取调用分别存在：Provider.tool_call_id 属于当前 read 调用，attachments.resource_ref 仍指向原 Run/call。ChartFigure 不是图片，仍须显式渲染；失败、未决和无可用附件的历史资源返回安全不可读错误。

### 6. 统一工具消息、hint 与发送选择

正常请求的每个已闭合调用仅有一条 TOOL ProviderMessage；同一 content 中依序为：
1. 唯一一份序列化 outcome + result/error + attachments 定位信息；
2. 对每个实际发送的附件：图片身份／provenance 与简短 hint；
3. 紧邻的 ImageBlock。

多图保留附件数组顺序；同一批多个调用保留 Provider call order。不同调用即使读取相同资源，也分别保留该调用的图片，不再跨调用 source-ID 去重。底层文件可去重，但逻辑结果不能因为去重丢失所属图片；实际发送次数进入成本估算。

`image_feedback.md` Common/Rules 进入稳定 System 规则；Cue 仅作为同图相邻短文本，由 Agent 按 image_kind 选择。失败、无图片的历史投影和资源索引不生成每图 hint。历史图片按被读取资源类型选择 Cue，工具名不决定图片语义。

新路径以附件列表驱动，不再匹配 load_image/extract_text/measure_chart/render_chart_figure 等名称来补图。删除 `build_observation_messages` 的普通 user 输出、旧工具名路由和双份观察序列化路径。保留观察自主性，不引入检查报告、门控、审核状态或追加模型轮次。

首次普通模型请求不自动加载用户附件。最新完整工具批次的图片在下一次普通逻辑模型请求及其替代 attempts 中发送；成功模型响应前不标记为已消费。后续请求对较早工具结果保留数据和附件描述，增加请求投影标记 `images_loaded: false`；最新实际发送的工具消息标记 `images_loaded: true`。该标记不写回事实，不改变资源是否存在。

### 7. 压缩边界与估算

- 交互单元始终包含完整 assistant 工具调用和全部 TOOL 结果；结构化结果、附件描述不能与其调用拆开。
- 最新尚未被普通模型观察的带图完整批次必须保留在 raw 尾部，不得提前被摘要覆盖。即使 protected history 已用尽预算，也保护这个批次；各约 10% 是软预算。当前 Run 较早的完整交互仍可压缩。
- 冻结 operation 的已有 coverage 不允许被新投影悄悄拓展；旧 operation 若覆盖新要求必须保护的批次，则切换前处理，运行时按版本／coverage 不匹配拒绝重用。
- 摘要请求只发送业务结果、图片引用和必要元数据，不发送图像字节、不注入 Cue、不将 hint 写成事实或用户要求。摘要保存资源引用以便之后精确读取。
- 完整请求仍按实际 payload 估算；工具消息和 user 消息中的图片采用同一个每次出现 1024 tokens 近似成本，Base64／URL 不作为普通文本计数。只引用未加载图片不收图片成本，实际 hint 文本计入文本估算。
- 不新增硬输出限制、图片数量微限制或累计 Run 预算。

### 8. Provider 原生编码与请求身份

内部 ProviderMessage 允许 TOOL 的有序 TextBlock/ImageBlock，保留一个 tool_call_id。通用校验检查关联、内容和字节限制；具体图片角色／能力限制交给每个 ProviderPolicy。

每个固定 Provider/model 显式声明 `supports_tool_result_images`，默认 false：
- DeepSeek/deepseek-flash：按官方 Chat Completions tool.content 原生块实现，并执行识别验收。
- Qwen/qwen3.8-flash、MiMo/mimo-v2.6-flash：先核对真实接口支持，再用同形状两图最小实验验证。只有合同和验证均满足才启用；无法忠实表示则明确 unsupported_capability。
- 能力缺口不通过附加普通 user、自动切 Responses／Anthropic endpoint、切换模型或丢弃图片掩盖。任何新协议支持须另行明确规划。

已知不支持的组合在本地 Provider 准备／工具目录准入时拒绝，不能先花费一次模型请求再假装已启用视觉循环。保留安全配置可用性与能力不可用的区别，不泄露 endpoint 或配置值。

原 request_fingerprint 已涵盖消息角色、tool_call_id、内容顺序、hint 和图片 data URL，继续作为完整绑定权威。现有资产 manifest 的 source_ref、media_type、byte_count、sha256 继续从同一附件导出；其 Provider 私有粗分类 observation_kind 仅投影 original/annotated/rendered，OCR／measurement 的具体语义仍以统一 image_kind 和资源 kind 为准，不引入新的在线业务枚举。已有历史 Provider 请求记录和指纹不改写。

hint／Prompt 或图片指纹发生变化时，遵守现有绑定不匹配拒绝行为，不能给旧 attempt 发送新 body。本次不存另一份 hint 文本、不补造 continuation、不重置重试额度。已完成请求仅供审计，切换后不作为待发送请求重新准备。

### 9. Gateway、隐私和删除

现有观察图片接口按 Session/Run/call 读取规范附件、校验来源授权和 SHA-256，返回同一已保存 PNG，不再调用 overlay renderer。图片详情接口保留原 URL、PNG/no-store、错误边界和安全摘要形状，未知／无媒体调用不推断图片。

工具详情与 Run DTO 不直接暴露整个 attachments 数组或业务结果；由安全投影选取现有 observation references。run_progress/SSE 不携带图像、hint、Prompt、字节或本地路径。Sources 新媒体区加入既有删除暂存、回滚恢复和启动对账，不改变外部 Session 删除协议。

### 10. 错误与资源完整性

| 触发点 | 行为 |
|---|---|
| handler 返回 dict、结果 Schema 或附件类型不合法 | 原调用的 invalid_result；有写入效果不明时转原 unknown 恢复合同 |
| 原资源未知／跨 Session／未提交／未来 Run | 现有安全 reference 不可用错误；不读文件 |
| 新图片无法生成或安装、效果已确定 | 工具失败，attachments=[]，不提交缺图成功 |
| 已提交文件丢失／指纹不匹配 | 不替换、不重绘；工具读取为安全不可读错误，Provider prepare 为现有安全准备失败 |
| Provider 不支持 TOOL 图片 | unsupported_capability；不 claim attempt、不降级消息语义 |
| 请求重建后 hint／媒体／顺序变化 | 原绑定不匹配行为，不重发不同请求 |
| migration 缺少可验证媒体 | 保留原业务事实、附件数组为空，审计报告记录不可用；不捏造图片或成功读取 |

新 Registry 的图像生产工具必须提供附件；一次迁移后无附件的历史结果仍使用同一个合法规范字段集，不根据旧版本在运行时推断／补绘图片。

## Risks / Trade-offs

- [部分 Provider 不支持工具结果图片] → capability 明确拒绝；交付报告逐 Provider 记录已通过／缺口，不能宣称三家全部支持。
- [跨调用图片不再去重会增加输入] → 仅发送最新批次、按实际出现次数估算；不以去重破坏调用关联。
- [标注 PNG 增加私有磁盘占用] → Session 内内容去重、现有图片大小保护、整会话删除和无活动 owner 时清理；本次不新增自动历史驱逐。
- [保存文件后数据库失败] → 图片暂不发布，重算可使用不同摘要，checkpoint 和事实原子提交；无 owner 的维护阶段清理孤儿。
- [新数据合同造成历史误读] → 一次性转换外层附件字段、备份原始序列化值、保留业务结果；不能把迁移重建图宣称为当时看到的图。
- [Prompt 子集遗漏图片引用] → 选择和授权使用完整目录，Prompt 只管模型定位展示。
- [切换时仍有冻结旧请求] → 激活前拒绝有 running Run／活跃 owner／非终态压缩 operation；不自动停止用户 Run 或重绑定请求。

## Migration Plan

1. 停止新调度，完成或由用户明确停止运行中的 Run；取得独占迁移锁。任何 running Run、活动执行 owner、未完成压缩 operation 都阻止迁移。不得通过自动终结 Run 绕过。
2. 建立 SQLite 一致备份、Sources 文件备份和私有迁移审计清单；审计不进入 Git 或普通日志。记录 schema、Registry 与源文件摘要。
3. 在事务和独立 staging 区规划转换：只为外层工具结果增加规范 attachments，不改变原 call/attempt/record ID、业务 result/error、测量 Schema、输入参数、终态、事件序列和 Provider 请求审计记录。所有旧结果统一转换为当前外层合同；运行时无需版本猜测／字典适配。
4. 可验证的 Attachment/Panel/ChartRender 生成 recorded 描述；支持且源图可读的旧 OCR／measure_chart 可在迁移过程依据已提交结果绘制一次标注，标记 migration_reconstructed。此步骤是媒体物化，不调用 OCR sensor、measure_chart、Provider、Figure assembly 或 render 工具。
5. 不支持的旧领域合同不升级为当前测量／ChartFigure资源；缺失或不可验证的媒体不补造，外层 attachments=[]，原事实继续可精确读取。迁移报告记录原因，线上读取明确不可用。主规格涉及“历史事实不转换”的约束解释为业务 payload 保持原样，外层媒体字段迁移必须在对应 delta 明示。
   历史读取和迁移沿用已有受支持事实读取边界，不得把外层描述增加或部署新写入限额降低当作删除／裁剪已接受历史的理由；新调用继续使用统一的新写入 payload guard。
6. 先安装 staging 媒体，再事务提交外层结果和新 schema。失败回滚数据库，保留／恢复原文件，清理只属于本次失败迁移的候选；重入迁移不覆盖已确定附件。
7. 同时激活新 Registry、handler、codec、Memory、Agent、Provider 和 Gateway；移除迁移工具与在线服务之间的导入依赖，不运行双管线。migration 工具只在显式维护入口使用，后续启动只验证 canonical schema。
8. 本地回归通过后，执行每个声明支持的 Provider 最小识别验收。回滚必须停止新版本写入，恢复配对的数据库＋Sources 备份和旧应用版本；已经产生新数据时不得直接把旧代码指向新数据库。

## Validation Strategy

- 合同：九个 handler、纯 dict 拒绝、JSON/附件超界、类型与身份不匹配、失败附件为空，保持全部业务 Schema。
- 媒体：输出 PNG 匹配 result，崩溃发生在安装后／事实提交前及提交后；不同重算结果不混用旧图片；读操作不重绘。
- 身份：同批 A/B 两图、重复读取同资源但不同 call ID、历史资源与当前读取调用分离、跨 Session／未来引用拒绝。
- 上下文：最新带图批次保护、压缩前后引用可取回、无媒体历史无 hint、文本与图片 occurrence 成本、原始用户输入不变。
- 绑定：重试同 body／hint／图片；资产变化 fail closed；continuation 和流式合同不变。
- Web：原观察图／render URL、Session 删除回滚、no-store、无 raw payload／路径／Prompt 泄露。
- 切换：备份恢复、失败事务重入、不可读旧图片保留文本事实、不重跑业务工具、无旧在线分支。
- 线上：每家支持 Provider 使用同一最小两图任务，文本和文件名不透露图片答案，要求读出各调用图片的可见特征；记录实际识别、usage 和失败类别。HTTP 200、mock 和离线 payload 通过不能替代识别成功；无有效凭据时明确记录未验证。

