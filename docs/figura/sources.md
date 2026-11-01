# Sources：附件、Panel 与生成图像

> 更新日期：2026-10-22。[返回总览](../figura-implementation-overview.md)。范围：当前 `src/figura/sources/` 中的附件与 Panel 生命周期、图像文件、OCR/测量标注和 ChartFigure 渲染 PNG 私有存储及授权读取。Sources 是 Session 附件和 Panel 元数据的共同 owner，也为工具生成的标注与渲染图像提供受控文件存储；Agent 的 `RunExecutionState.resources` 是从 Runtime 与 Sources 重建的调用期类型化目录，完整字段归 [Agent](agent.md#4-runexecutionstate-资源合同与完整字段)。Agent 的 `RunExecutionImageReader` 经目录授权后调用 Sources 服务读取源图、已保存标注 PNG 或 render PNG。Sources 不拥有 OCR 或测量结果；当前工作树中的 Tools 提供独立 OCR 与统一十类图表视觉观察，并在相应证据门槛满足时输出标定值，观察坐标始终留在源像素框。通用 Evidence 模型和证据生命周期尚未实现，观察工具合同见 [Tools](tools.md#6-图像与测量工具合同)。

## 1. 职责与边界

Sources 将用户上传的 `AttachmentMetadata` 与从附件分割出的 `PanelRecord` 作为两类来源元数据写入同一个 Figura SQLite 数据库；附件与 Panel 服务分别负责内容验证、私有文件操作、图像读取和分割。它也保存 OCR/测量标注和 ChartFigure 渲染 PNG，但这些生成媒体只以文件形式存储，不新增附件/Panel 元数据实体。数据库连接、事务和 schema 由共享 [Storage](../../src/figura/storage/) 使用的基础设施提供。

附件字节位于私有 `attachments/` 文件，Panel 字节位于私有 `panels/` 文件，工具标注 PNG 位于私有 `tool-media/` 文件，ChartFigure 渲染 PNG 位于私有 `chart-renders/` 文件区。Panel 的所有图像都是独立 PNG；多边形外区域透明。标注与渲染文件分别由媒体和渲染服务管理，不对应 SourcesRepository 记录或新的业务模型。文件路径、图像字节、图像尺寸和是否已在 Agent 清单中可用都不是 `PanelRecord` 字段。公开 DTO 属于 [Web](web.md#4-web-dto-字段)，Provider 请求期的 `ImageBlock` 属于 [Provider](provider.md#4-完整模型字段)。

Panel PNG 的透明外区可能仍保留源 RGB，但这些颜色不属于可见证据。Tools 的共享 [观察解码](../../src/figura/tools/measurements/observation_scope.py) 将图像按白底合成，完全透明像素排除、半透明像素保留合成色，并与本次 scope 相交；标注反馈底图也作白底 alpha 合成，不改写私有文件、尺寸或坐标。OCR 整框跨出有效区域即舍弃，几何只能分析保留下来的部分。解码与错误合同归 [Tools](tools.md#6-图像与测量工具合同)，Sources 仍负责原 PNG 的存储与读取。

Runtime 创建 Run 时只接受附件 ID，并在 Run 创建事务内检查附件归属；Runtime 不执行附件 CRUD 或文件管理。Panel 在 `SourcesRepository` 中保存后，也不因此自动对 Agent 或 Web 可见：Agent 根据 Run 中已提交成功的 `decompose_chart_image` 结果重建可用 Panel 清单。

## 2. 内部流转与不变量

1. **接收附件**：Gateway 将图片字节和文件名交给 `FiguraAttachmentService`。服务验证 Session、文件名、大小与实际图像媒体类型，生成 opaque `attachment_id`，再协调 metadata 写入与私有文件安装。上传响应只返回安全元数据。
2. **Run 引用附件**：Run 创建请求按用户顺序携带附件 ID。`RunRepository` 在创建事务内校验每个 ID 属于该 Session 且没有重复，再将 ID 保存到 `RunInput.attachment_ids`。Run 已引用的附件不能删除或替换；附件元数据与文件路径不直接写进 Run。
3. **重建类型化资源目录**：Agent 的 `RunExecutionStateService` 读取目标 Run 已提交前缀、较早终态 Run 和 Sources 元数据，按权威事实重建附件、Panel、OCR、测量、ChartFigure 与 ChartRender 资源。只有 Run 输入引用的附件和成功分割结果对应的 Panel 才进入目录；完整字段与顺序规则见 [Agent 资源合同](agent.md#4-runexecutionstate-资源合同与完整字段)。
4. **授权读取或分割图像**：Tools 中的 `load_image` 与测量/OCR handler 先从目标目录获取类型化来源引用，再通过 Agent `RunExecutionImageReader` 调用 Sources 验证归属并读取字节。`decompose_chart_image` 在附件读权限通过后由 `FiguraPanelService` 将归一化多边形映射到像素，生成带透明 mask 的独立 PNG。矩形也用四点多边形表达；每个 Panel 单独保存。
5. **提交与恢复**：Panel ID 为 `SHA256("<call-scoped idempotency key>:<zero-based panel index>")`。服务把每个 PNG 写入私有临时目录、flush 并 `fsync`，再用硬链接安装文件；`SourcesRepository` 在 SQLite 写事务中调用文件安装并登记元数据。若数据库登记或提交失败，Panel Service 会补偿删除本次已安装文件。相同幂等身份会校验并复用既有 Panel 记录。只有对应成功 ToolResultFact 经 Runtime 提交后，Agent 才把 Panel 纳入可用清单和网页列表。
6. **保存 ChartFigure 渲染图**：`render_chart_figure` 调用 Charts 生成 PNG 后，`FiguraChartRenderService.store(run_id, call_id, content)` 将其写到 `data_root/chart-renders/`。文件名是 canonical JSON `[run_id, call_id]` 的 SHA-256，不接收模型控制的路径；目录为 `0700`、文件为 `0600`。服务先写私有临时文件并 `fsync`，再以硬链接原子安装；相同身份重放时读取并复用既有文件，不替换。存储校验 PNG 格式、可解码性、正尺寸、`MAX_IMAGE_BYTES` 字节上限和 40,000,000 像素上限。渲染元数据仍只在成功 `ToolResultFact` 中；文件在结果成功提交前不进入 Agent 或 Web 投影。
7. **列出、读取与对账**：Gateway 以 Session ID 委托 Sources 列出附件/Panel 或读取图像内容。跨 Session 访问须拒绝；单个附件删除须确认没有 Run 引用。附件服务先对账单附件 trash 和附件文件，Panel 服务先清理孤儿 PNG/临时目录；随后 Gateway 删除协调器处理 `session-trash`，再清理无持久 render 调用对应的 PNG/临时目录，最后逐一验证已登记 Panel PNG。Panel 的完整性校验在会话暂存恢复之后执行，避免将删除回滚中暂存的文件误判为缺失。渲染对账保留所有耐久 render 调用对应的文件，包括结果尚未提交者，供显式幂等恢复；公开读取仍要求成功 ToolResultFact。文件路径与像素字节不进入 DTO、事件或工具 JSON；Runtime 结果只保存附件描述，Agent 在 native TOOL 消息内单独投影图片块。
8. **删除整个 Session**：Gateway 删除协调器在共享 SQLite 写事务中取得 Sources 附件/Panel 身份和 Runtime 的 render 调用身份，再调用附件、Panel、render 和标注媒体四个 Sources 文件服务的 `stage_session_deletion`，把已存在文件移入私有 `session-trash/<session_id>/` 的附件、Panel、render、tool-media 子目录并同步目录。SourcesRepository 在同一事务删除 Panel/附件行；Session 提交删除后丢弃暂存树，回滚则恢复原路径。Session 删除是单附件“被引用禁止删除”的受控整体删除例外，不能用于删掉单个已使用来源。恢复、重启和清理失败语义见[Web 删除协调](web.md#会话删除与恢复)。

## 3. 完整模型字段

附件与 Panel 元数据模型由 Sources 定义；中立媒体值位于 shared/media，完整字段也在本篇集中说明。字段完整列出；网页 DTO、Agent 派生清单及图像内容不属于这些模型。

### `AttachmentMetadata`

Session 所拥有的附件元数据；六个字段保存在 `attachments` 表，图像字节另存私有文件。**写入者：**`FiguraAttachmentService` / `SourcesRepository`。**权威位置：**`attachments` 表。**读取与公开：**Sources 附件查询、Run 输入归属校验及 Web 的有限附件 DTO；不公开本机路径。[定义](../../src/figura/sources/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义、约束与流转 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| `AttachmentMetadata.attachment_id` | `str` | 必传 | 附件的 opaque 身份 | Attachment Service / SourcesRepository → `attachments.attachment_id` → 附件查询、Run 创建校验和 Session 授权读取 |
| `AttachmentMetadata.session_id` | `str` | 必传 | 所属 Session 身份；跨 Session 读取须拒绝 | Attachment Service / SourcesRepository → `attachments.session_id` → Session-scoped 查询与授权 |
| `AttachmentMetadata.filename` | `str` | 必传 | 净化后的上传文件名 | Attachment Service / SourcesRepository → `attachments.filename` → 安全附件 DTO、图像清单 |
| `AttachmentMetadata.media_type` | `str` | 必传 | 根据实际图像内容验证得到的媒体类型 | Attachment Service / SourcesRepository → `attachments.media_type` → 内容响应和安全 DTO |
| `AttachmentMetadata.byte_count` | `int` | 必传 | 原始图像字节数 | Attachment Service / SourcesRepository → `attachments.byte_count` → 安全 DTO 与资源限制校验 |
| `AttachmentMetadata.created_at` | `str` | 必传 | 创建时间的 UTC 文本 | Attachment Service / SourcesRepository → `attachments.created_at` → Session 列表聚合和安全 DTO |

### `PanelPoint`

不可变多边形顶点，作为 `PanelRecord.points` 的元素编码在 `points_json` 中。坐标必须是精确 `int`（布尔值不接受），范围为 0–1000，包含端点。[定义](../../src/figura/sources/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义、约束与流转 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| `PanelPoint.x` | `int` | 必传 | 原图宽度方向的归一化坐标，范围 0–1000；创建独立 PNG 时映射为像素 | Tool 参数 → `PanelRecord.points` / `points_json` → Panel 分割与 Web 多边形投影 |
| `PanelPoint.y` | `int` | 必传 | 原图高度方向的归一化坐标，范围 0–1000；创建独立 PNG 时映射为像素 | Tool 参数 → `PanelRecord.points` / `points_json` → Panel 分割与 Web 多边形投影 |

### `PanelRecord`

Session 所拥有的不可变分区记录。SQLite 保存六项元数据；`points` 编码为 `points_json`。模型不含创建时间、文件路径、图像尺寸或可见状态。[定义](../../src/figura/sources/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义、约束与流转 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| `PanelRecord.panel_id` | `str` | 必传 | opaque Panel 身份；按 call-scoped 幂等键与结果序号确定性生成，存储校验为小写 64 位十六进制；用于派生 PNG 文件名 | `FiguraPanelService` / SourcesRepository → `panels.panel_id` → Agent 清单与 Session-scoped Web DTO |
| `PanelRecord.session_id` | `str` | 必传 | 所属 Session 身份；数据库外键关联 Session，作为列表和内容读取授权范围 | `FiguraPanelService` / SourcesRepository → `panels.session_id` → Session-scoped 查询；不进入公开 DTO |
| `PanelRecord.run_id` | `str` | 必传 | 产生 Panel 的 Run 身份；数据库复合外键验证 Session 归属 | `FiguraPanelService` / SourcesRepository → `panels.run_id` → Agent 事实匹配与 Web Run 分组 |
| `PanelRecord.source_attachment_id` | `str` | 必传 | 被切分的来源附件身份；外键关联附件，不改变来源图像 | `FiguraPanelService` / SourcesRepository → `panels.source_attachment_id` → Tool 结果、Agent 清单及 Web DTO |
| `PanelRecord.name` | `str` | 必传 | 模型给出的显示名；非空白，UTF-8 长度不超过 256 bytes | Tool 参数 → `panels.name` → 安全工具结果、图像清单和 Web DTO |
| `PanelRecord.points` | `tuple[PanelPoint, ...]` | 必传 | 原图坐标系中的完整顶点顺序；3–64 个点，作为 JSON 数组保存，不简化边界 | Tool 参数 → `panels.points_json` → PNG mask 生成与 Web 多边形投影 |

## 4. 存储失败与访问边界

- Sources 与 Runtime 使用同一个 `SqliteDatabase` 和 schema v12；表及事务初始化由 `storage/` 负责。迁移及 Session 删除授权触发器见 [Runtime schema 迁移说明](runtime.md#sqlite-schema-v12-迁移)。附件和 Panel 行操作集中在 `SourcesRepository`，不再由 Runtime Store 代管附件 CRUD；整会话删除在共享连接内协作完成。
- 附件内容在校验后安装到私有文件；Panel 内容为每个分区单独生成的 PNG。每个 Panel 最多 40,000,000 个源像素；单张 Panel PNG 不超过 `MAX_IMAGE_BYTES`，一批所有 PNG 合计不超过 `MAX_TOTAL_IMAGE_BYTES`，最多 32 个 Panel。Panel 文件在 SQLite 写事务内安装并登记，数据库失败时通过清理已安装文件补偿；这不是跨文件系统和 SQLite 的原子事务。启动时校验已登记内容并清理孤儿 PNG 和临时目录。
- Panel 的坐标点数为 3–64，名称上限为 256 UTF-8 bytes。输入顺序、模型给出的边界点和重叠区域都按原提议保留；工具不判定分区语义、准确性、重叠是否合理或图表类型。
- Panel 记录本身不证明其分割工具调用已成功提交。Agent 以 Runtime 成功 ToolResultFact 与 PanelRecord 的 Session、Run、ID、名称及来源附件字段匹配，决定是否可供当前 Run 使用或在 Web 列表显示。
- Chart render 文件本身也不证明渲染调用已成功提交。Agent 与 Gateway 只根据同 Session 已接受 Figure 和成功的渲染 ToolResultFact 投影、读取对应文件；摘要与文件哈希或尺寸不符时拒绝使用。
- Sources 管理附件和 Panel 元数据，并提供附件、Panel、生成 PNG 文件的私有存取；这不代表通用 Source、Observation、Measurement 或 Evidence 实体已实现。
- Session 删除的文件 staging 与 SQLite 提交不是跨系统原子事务：重启时以 Session 是否仍存在决定恢复或销毁暂存文件。恢复碰撞、非法暂存项或符号链接不能被静默接受；其他 Session 的文件不在删除集合内。

## 5. 代码与规格依据

代码：[模型](../../src/figura/sources/models.py)、[Sources Repository](../../src/figura/sources/repository.py)、[附件服务](../../src/figura/sources/attachments.py)、[Panel 服务](../../src/figura/sources/panels.py)、[图像处理](../../src/figura/sources/imaging.py)、[私有文件工具](../../src/figura/sources/storage.py)、[ChartFigure PNG 存储](../../src/figura/sources/chart_renders.py)、[SQLite schema](../../src/figura/storage/schema.py)、[Run 附件归属校验](../../src/figura/runtime/persistence/runs.py)、[资源目录重建](../../src/figura/agent/execution_state.py)、[统一图片读取](../../src/figura/agent/execution_images.py)、[图像工具](../../src/figura/tools/implementations/image.py)。主规格：[图片附件存储](../../openspec/figura/openspec/specs/image-attachment-storage/spec.md)、[Panel 图像观察](../../openspec/figura/openspec/specs/panel-image-observation/spec.md)、[Web Gateway](../../openspec/figura/openspec/specs/figura-web-gateway/spec.md)。

附件、Panel 文件与授权边界见 [图片附件存储](../../openspec/figura/openspec/specs/image-attachment-storage/spec.md)、[Panel 图像观察](../../openspec/figura/openspec/specs/panel-image-observation/spec.md)、[工具结果媒体](../../openspec/figura/openspec/specs/tool-result-media/spec.md)和 [Web Gateway](../../openspec/figura/openspec/specs/figura-web-gateway/spec.md)主规格。透明像素与观察范围如何作用于 OCR/测量输入由 [图像观察解码](../../openspec/figura/openspec/specs/image-observation-decoding/spec.md)定义；来源文件本身不被改写。

## 中立媒体值与附件描述

当前工作树以 `shared/media.py` 的中立值返回图片，Attachment/Panel 服务不再依赖 Provider.ImageBlock。Shared 只定义值，Sources 管理实际文件；Provider 块只在 Agent 投影时生成。资源引用位于 `shared/resource_refs.py`，完整引用字段仍集中列于 [Agent 资源合同](agent.md#4-runexecutionstate-资源合同与完整字段)，所有消费者直接使用公共模块。

| 完整字段路径 | 类型／默认 | 语义、权威位置与流转 |
|---|---|---|
| ResourceImage.media_type | str，必传 | 实际验证的 JPEG/PNG/GIF/WebP 类型；Sources 或工具准备阶段写入，调用期只读 |
| ResourceImage.image_bytes | bytes，必传；repr=False | 非空、遵守原图片保护；真实像素只在 Sources 文件和调用期内存，不进入事实或 DTO |
| ResourceImage.width | int，必传 | 正整数、与解码尺寸一致；图片准备 → Runtime/Agent 校验 |
| ResourceImage.height | int，必传 | 正整数、与解码尺寸一致；图片准备 → Runtime/Agent 校验 |
| ToolImageAttachment.resource_ref | ResourceRef，必传 | attachment/panel 使用 kind+id，ocr/measurement/chart_render 使用 kind+run_id+call_id；读取保留原身份 |
| ToolImageAttachment.image_kind | ImageKind，必传 | original、ocr_annotation、measurement_annotation、rendered；分别匹配原图/Panel、OCR、测量、ChartRender |
| ToolImageAttachment.media_type | str，必传 | 原图允许已验证媒体；标注与渲染必须 PNG |
| ToolImageAttachment.width | int，必传 | 实际正整数宽度；描述与保存文件必须一致 |
| ToolImageAttachment.height | int，必传 | 实际正整数高度；描述与保存文件必须一致 |
| ToolImageAttachment.byte_count | int，必传 | 正整数原始字节数，受既有单图保护 |
| ToolImageAttachment.sha256 | str，必传 | 精确原始文件的 64 位小写 SHA-256，不是业务 ID |
| ToolImageAttachment.provenance | MediaProvenance，recorded | recorded / migration_reconstructed；后者仅用于维护时重建的旧标注；历史重载不得更改 |

ToolImageAttachment 的唯一持久权威是 Runtime 的 ToolResultFact.attachments。描述由通用媒体提交器生成，Memory 和资源目录只派生它；不允许模型传入文件路径、URL、存储键或附件描述。ToolOutput/ToolImageOutput 合同见 [Tools](tools.md#tooloutput-与-toolimageoutput)。

OCR/测量标注在工具执行阶段生成，存入 Session 私有的 `tool-media/<session_id>/<sha256>.png`。不可变原子安装、fsync、同摘要去重复用；同一逻辑调用重算得到不同图片时按新摘要安装，绝不按 call_id 复用旧候选图。Attachment、Panel 与 ChartRender 复用原文件，不复制为第二套媒体。

文件先安装，再由 Runtime 事务提交结果、描述、checkpoint 与进度事件。文件系统与 SQLite 不假装属于一个原子事务；安装后未提交的候选不进入资源目录。`reconcile_idle` 在数据库写屏障下确认没有 running Run、preparing 压缩操作，并取得全部 Run owner 后才清理无引用文件；不能证明独占就保留候选。构造媒体服务不会清理在途文件。媒体参与 Session 删除暂存、回滚恢复和启动暂存对账，跨 Session 相同内容分别所有。

正常图片读取只能按“授权目录引用 → 已提交描述 → 保存文件”解析并校验摘要、类型、尺寸与字节数。缺失或损坏时安全失败，不重绘、不修复、不重跑 OCR 或测量。公开 Gateway JSON/SSE 不包含附件数组、hint、私有路径或原始字节。一次性切换流程见 [Runtime 维护迁移](runtime.md#多模态结果维护迁移)。
