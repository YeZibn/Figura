# Panels：图像分区与运行时清单

> [返回系统总览](../figura-implementation-overview.md)。范围：当前工作树 `src/figura/panels/`、Panel 图像工具、Agent 请求中的临时图像清单，以及 Session 内 Panel 读取。当前代码已存在；OpenSpec change `add-figura-panel-image-tools` 尚未归档。本文以当前代码和该活动 change 为实现依据，不代表主规格已同步。

## 1. 职责与所有权

Panel 是从一个 Session 附件图像中，按模型提供的多边形切出的独立 PNG 与元数据。`PanelRecord` 的权威 owner 是 Panels domain；SQLite `panels` 表保存其元数据，`data_root/panels/<panel_id>.png` 保存对应图像。每个 Panel 都有完整独立图像；多边形之外像素透明。文件路径、图像字节、图像宽高不属于 `PanelRecord`。

`RunExecutionState` 是每次读取时从 Runtime、附件元数据和 PanelRepository 重建的只读视图，不持久化、不加入 RunState/SessionSnapshot。它汇集目标 Run 已引用的附件，以及当前 Session 中已提交的 Panels。Panel 记录只有在对应成功 `decompose_chart_image` 的 ToolResultFact 已提交后才可见；PanelRepository 自己有记录不代表工具结果已完成。

边界：附件仍由 [Sources](sources.md) 拥有；工具输入/结果及 ReplayEffect 由 [Tools](tools.md#6-图像工具合同) 拥有；Web DTO 和 Session 路由由 [Web](web.md) 拥有；Run 输入、工具事实、checkpoint 和事务由 [Runtime](runtime.md) 拥有。

## 2. 内部流转

1. **构建运行时清单**：`RunExecutionStateService` 读取目标 Run、所有较早 RunState 和当前 Session snapshot。较早 Run 必须为终态且 ordinal 从 1 连续。清单按 Run ordinal 顺序遍历较早 Run 的输入附件 ID，再遍历当前 Run 输入；附件 ID 全局去重，文件名从同 Session `AttachmentMetadata` 读取。缺失元数据视为数据完整性错误，不返回部分清单。
2. **读取已提交 Panels**：PanelRepository 提供该 Session 的全部 Panel metadata；投影器按 Session 中 Run 的 ordinal、Run 内工具事实顺序和工具结果数组顺序扫描成功的 `decompose_chart_image` 结果。只有 ToolResultFact 中的 Panel ID、name、source attachment ID 与 PanelRecord 的 Session/Run/字段全部匹配时才加入结果；重复、缺失或不匹配记录视为完整性错误。
3. **授权并加载图像**：`load_image` 先要求 `source_id` 出现在本 RunExecutionState 的附件或已提交 Panel 清单，再由所属 Session 的 Attachment/Panel Service 读取内容。工具结果只返回资源 ID、名称和宽高。紧接本次模型响应之后，最新已提交工具批次中成功的 `load_image` 结果由 AgentRequestBuilder 读取并转为下一条 user 消息里的 ImageBlock；调用顺序保留、同一资源去重。下一轮批次不继承旧图片；新 Run 也不会继承前一 Run 已加载的图片字节。
4. **切分并写入 Panel**：`decompose_chart_image` 只接收可用清单里的 Attachment ID。Panel Service 按原图宽高把整数坐标 0–1000 映射到像素，创建多边形 mask，裁剪包围区域并输出透明 PNG。矩形也是四点多边形；重叠区域分别生成独立文件。只检查结构、图像解码和资源上限，不判断分区语义、视觉准确度、Panel 重叠或图表类型。
5. **本地提交与可见性**：Panel ID 是 `SHA256("<call-scoped idempotency key>:<zero-based panel index>")`。图片先写入私有临时目录并 fsync，再通过硬链接安装；metadata 在 SQLite 写事务中写入。写入失败清理已安装文件。进程启动时清理孤儿 PNG 和临时目录，并验证所有已登记 PNG；登记记录缺少/损坏图像时启动失败为数据完整性错误。若图片和 metadata 已写入而 ToolResultFact 尚未提交，Panel 暂不进入投影；工具恢复通过同一 ID 复用记录，提交成功结果后才展示。
6. **提供网页预览**：Gateway 使用 Session ID 授权列出可见 Panel 或读取 PNG；内容响应为 `image/png`、`Cache-Control: no-store`。Web DTO 不暴露 Panel 内部 session_id、文件路径和图片字节；React 按 `run_id` 分组，图片进入可见区域后由浏览器懒加载。

## 3. 完整字段合同

以下三个值由本领域定义。前三者为冻结 dataclass；字段完整列出。未写持久化的值是调用期投影，不新增数据库字段。

### `PanelPoint`

不可变多边形顶点；随 `PanelRecord.points` 存入 `points_json`。Python 校验要求坐标类型是精确 `int`（布尔值不接受），值域为 0–1000，包含两端点。

| 完整字段路径 | 类型 | 默认 | 含义、约束与流转 |
|---|---|---|---|
| `PanelPoint.x` | `int` | 必传 | 原图宽度方向的归一化坐标，0–1000；由工具参数创建，序列化到所属 Panel 的 `points_json`，切分时映射成像素；不单独公开 |
| `PanelPoint.y` | `int` | 必传 | 原图高度方向的归一化坐标，0–1000；由工具参数创建，序列化到所属 Panel 的 `points_json`，切分时映射成像素；不单独公开 |

### `PanelRecord`

Session 所拥有的不可变分区记录。Python 模型六项字段与公开 DTO 不同；DTO 是 Web 投影，由 [Web 专题](web.md#4-web-dto-字段)定义。SQLite 存六列，其中 `points` 编码为 `points_json`；无创建时间、文件路径、图像尺寸或状态字段。

| 完整字段路径 | 类型 | 默认 | 含义、约束与流转 |
|---|---|---|---|
| `PanelRecord.panel_id` | `str` | 必传 | 不透明 Panel ID；由 call-scoped 幂等键和 Panel 顺序确定性生成，SQLite 校验为小写 64 位十六进制；用于派生 PNG 文件名，不含路径 |
| `PanelRecord.session_id` | `str` | 必传 | 所属 Session ID；SQLite 外键关联 Session，作为读取授权范围；不进入 Panel Web DTO |
| `PanelRecord.run_id` | `str` | 必传 | 产生本 Panel 的 Run ID；SQLite `(run_id, session_id)` 外键验证归属，关联工具结果和 UI 分组 |
| `PanelRecord.source_attachment_id` | `str` | 必传 | 被切分的来源附件 ID；SQLite 外键关联附件，不改变来源图像；工具结果和 Web DTO 引用此 ID |
| `PanelRecord.name` | `str` | 必传 | 模型给出的显示名；非空白且 UTF-8 长度不超过 256 bytes；进入安全工具结果、Web DTO 和图片替代文本 |
| `PanelRecord.points` | `tuple[PanelPoint, ...]` | 必传 | 原图坐标系的完整顶点序列；3–64 个点；保存为 JSON 数组，不简化或取代模型给出的边界 |

### `AvailableAttachment`

目标 Run 图像清单中的一条附件引用；只在 RunExecutionState 内存在，字段来自 RunInput 和 Session 附件元数据。

| 完整字段路径 | 类型 | 默认 | 含义、约束与流转 |
|---|---|---|---|
| `AvailableAttachment.attachment_id` | `str` | 必传 | 不透明 Attachment ID；按 earlier Run 再 current Run 的输入顺序去重，交给 `load_image`/`decompose_chart_image` 做清单授权；清单不是持久新状态 |
| `AvailableAttachment.filename` | `str` | 必传 | 从拥有附件的 Session 元数据读取的显示文件名；放入临时图像清单和 `load_image` 结果；不把图像内容写进清单 |

### `RunExecutionState`

目标 Run 的完整图像与 Panel 可用性投影。`RunExecutionStateService` 每次由协调器状态与 PanelRepository 重建，不持久化。其字段只有以下三项。

| 完整字段路径 | 类型 | 默认 | 含义、约束与流转 |
|---|---|---|---|
| `RunExecutionState.run_id` | `str` | 必传 | 该视图所属 Run 的 ID；来自目标 `RunState.run.run_id`，不持久化 |
| `RunExecutionState.available_attachments` | `tuple[AvailableAttachment, ...]` | 必传 | 按 earlier Run ordinal、各 Run 输入顺序、当前 Run 输入顺序去重的附件清单；仅包含当前 Session Run 输入实际引用的附件 |
| `RunExecutionState.panels` | `tuple[PanelRecord, ...]` | 必传 | 本 Session 中有已提交成功分割结果事实的所有 Panel，按产生 Run 和分割结果顺序排列；在目标 Run 工具调用中用于读取授权 |

## 4. 存储、错误与不变量

- SQLite schema v6 的 `panels` 表字段为 `panel_id`、`session_id`、`run_id`、`source_attachment_id`、`name`、`points_json`；表由 PanelRepository 管理，更新和删除由数据库触发器拒绝。`PanelRecord` 是这六项值的领域模型。启动时缺失文件或损坏图像会阻止服务启动；孤儿图像和临时目录会被清理。
- 图像保存为独立 PNG，透明多边形外区域；每 Panel 最多 40,000,000 source pixels，单 PNG 与批次总字节数受现有 Provider 图像字节上限约束。面板数量最多 32，名称最多 256 UTF-8 bytes，点数最多 64。超限不会静默裁剪区域或更改坐标。
- 工具调用的资源身份必须属于目标 Session 的 RunExecutionState；跨 Session、未进入任何 Run 输入的附件、尚未提交的 Panel 均拒绝读取或分割。
- `load_image` 的成功事实本身不持久化图片 bytes；只有其立即后继模型请求会读取图片。ToolResultFact 仍是 bounded JSON，分割结果只含 panel ID、name 和来源附件 ID。
- 按主规格的事实/设计分层：Panel 不是通用 Observation/Evidence，也不表达测量正确性；模型负责给分区，工具只安全地产生图像文件并保存原边界。

## 5. 代码与 OpenSpec 依据

代码：[模型](../../src/figura/panels/models.py)、[SQLite Repository](../../src/figura/panels/repository.py)、[图像服务](../../src/figura/panels/service.py)、[RunExecutionState 投影](../../src/figura/panels/execution_state.py)、[图像工具](../../src/figura/tools/image_tools.py)、[schema v6](../../src/figura/runtime/persistence/schema.py)。活动 change：[proposal](../../openspec/figura/openspec/changes/add-figura-panel-image-tools/proposal.md)、[design](../../openspec/figura/openspec/changes/add-figura-panel-image-tools/design.md)、[tasks](../../openspec/figura/openspec/changes/add-figura-panel-image-tools/tasks.md)。
