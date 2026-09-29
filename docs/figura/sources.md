# Sources：附件与 Panel 图像资源

> [返回总览](../figura-implementation-overview.md)。范围：当前 `src/figura/sources/` 中的附件和 Panel 生命周期、图像文件及授权读取。Sources 是这两类 Session 图像资源的共同 owner；Agent 的 `RunExecutionState` 是从 Runtime 与 Sources 重建的调用期视图，见 [Agent](agent.md#4-运行时状态字段)。Sources 不拥有测量结果；当前工作树中的 Tools 提供柱状图、折线图和散点图像素几何，并在轴标定通过时输出图表单位观察。通用 Evidence 模型和证据生命周期尚未实现，测量结果合同见 [Tools](tools.md#6-图像与测量工具合同)。

## 1. 职责与边界

Sources 管理两种有不同身份和生命周期的图像资源：用户上传的 `AttachmentMetadata`，以及从附件分割出的 `PanelRecord`。`SourcesRepository` 将两类元数据写入同一个 Figura SQLite 数据库；附件与 Panel 服务分别负责内容验证、私有文件操作、图像读取和分割。数据库连接、事务和 schema 由共享 [Storage](../../src/figura/storage/) 使用的基础设施提供。

附件字节位于私有 `attachments/` 文件，Panel 字节位于私有 `panels/` 文件。Panel 的所有图像都是独立 PNG；多边形外区域透明。文件路径、图像字节、图像尺寸和是否已在 Agent 清单中可用都不是 `PanelRecord` 字段。公开 DTO 属于 [Web](web.md#4-web-dto-字段)，Provider 请求期的 `ImageBlock` 属于 [Provider](provider.md#4-完整模型字段)。

Runtime 创建 Run 时只接受附件 ID，并在 Run 创建事务内检查附件归属；Runtime 不执行附件 CRUD 或文件管理。Panel 在 `SourcesRepository` 中保存后，也不因此自动对 Agent 或 Web 可见：Agent 根据 Run 中已提交成功的 `decompose_chart_image` 结果重建可用 Panel 清单。

## 2. 内部流转与不变量

1. **接收附件**：Gateway 将图片字节和文件名交给 `FiguraAttachmentService`。服务验证 Session、文件名、大小与实际图像媒体类型，生成 opaque `attachment_id`，再协调 metadata 写入与私有文件安装。上传响应只返回安全元数据。
2. **Run 引用附件**：Run 创建请求按用户顺序携带附件 ID。`RunRepository` 在创建事务内校验每个 ID 属于该 Session 且没有重复，再将 ID 保存到 `RunInput.attachment_ids`。Run 已引用的附件不能删除或替换；附件元数据与文件路径不直接写进 Run。
3. **构建可用资源清单**：Agent 的 `RunExecutionStateService` 读取目标 Run、较早终态 Run 和 Sources 元数据。它从 Run 输入重建当前 Session 已引用附件，并按成功的 Panel 分割 ToolResultFact 过滤 Sources 中保存的 Panel。字段及完整重建规则见 [Agent 运行时状态](agent.md#4-运行时状态字段)。
4. **显式加载或分割图像**：Tools 中的 `load_image` 与 `decompose_chart_image` 只能使用该 Run 清单授权的附件或已提交 Panel。`FiguraPanelService` 将归一化多边形坐标映射到原图像素，生成带透明 mask 的独立 PNG。矩形也用四点多边形表达；每个 Panel 单独保存。
5. **提交与恢复**：Panel ID 为 `SHA256("<call-scoped idempotency key>:<zero-based panel index>")`。服务把每个 PNG 写入私有临时目录、flush 并 `fsync`，再用硬链接安装文件；`SourcesRepository` 在 SQLite 写事务中调用文件安装并登记元数据。若数据库登记或提交失败，Panel Service 会补偿删除本次已安装文件。相同幂等身份会校验并复用既有 Panel 记录。只有对应成功 ToolResultFact 经 Runtime 提交后，Agent 才把 Panel 纳入可用清单和网页列表。
6. **列出、读取与对账**：Gateway 以 Session ID 委托 Sources 列出附件/Panel 或读取图像内容。跨 Session 访问须拒绝；附件删除须确认没有 Run 引用。服务启动时在数据库写事务内移除孤儿 Panel PNG 与遗留临时目录，并逐一读取、解码已登记的 PNG；缺失、损坏、格式不符或超限时启动失败。文件路径与图像字节不进入 DTO、事件或工具结果。

## 3. 完整模型字段

以下三个冻结 dataclass 由 Sources 定义。字段完整列出；网页 DTO、Agent 派生清单及图像内容不属于这些模型。

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

## 4. 存储、失败与范围

- Sources 与 Runtime 使用同一个 `SqliteDatabase` 和 schema v6；表及事务初始化由 `storage/` 负责。附件和 Panel 行操作集中在 `SourcesRepository`，不再由 Runtime Store 代管附件 CRUD。
- 附件内容在校验后安装到私有文件；Panel 内容为每个分区单独生成的 PNG。每个 Panel 最多 40,000,000 个源像素；单张 Panel PNG 不超过 `MAX_IMAGE_BYTES`，一批所有 PNG 合计不超过 `MAX_TOTAL_IMAGE_BYTES`，最多 32 个 Panel。Panel 文件在 SQLite 写事务内安装并登记，数据库失败时通过清理已安装文件补偿；这不是跨文件系统和 SQLite 的原子事务。启动时校验已登记内容并清理孤儿 PNG 和临时目录。
- Panel 的坐标点数为 3–64，名称上限为 256 UTF-8 bytes。输入顺序、模型给出的边界点和重叠区域都按原提议保留；工具不判定分区语义、准确性、重叠是否合理或图表类型。
- Panel 记录本身不证明其分割工具调用已成功提交。Agent 以 Runtime 成功 ToolResultFact 与 PanelRecord 的 Session、Run、ID、名称及来源附件字段匹配，决定是否可供当前 Run 使用或在 Web 列表显示。
- Sources 目前覆盖附件和 Panel 图像资源，不代表通用 Source、Observation、Measurement 或 Evidence 实体已实现。

## 5. 代码与规格依据

代码：[模型](../../src/figura/sources/models.py)、[Sources Repository](../../src/figura/sources/repository.py)、[附件服务](../../src/figura/sources/attachments.py)、[Panel 服务](../../src/figura/sources/panels.py)、[图像处理](../../src/figura/sources/imaging.py)、[私有文件工具](../../src/figura/sources/storage.py)、[SQLite schema](../../src/figura/storage/schema.py)、[Run 附件归属校验](../../src/figura/runtime/persistence/runs.py)、[Agent 清单](../../src/figura/agent/execution_state.py)、[图像工具](../../src/figura/tools/implementations/image.py)。主规格：[图片附件存储](../../openspec/figura/openspec/specs/image-attachment-storage/spec.md)、[Panel 图像观察](../../openspec/figura/openspec/specs/panel-image-observation/spec.md)、[Web Gateway](../../openspec/figura/openspec/specs/figura-web-gateway/spec.md)。
