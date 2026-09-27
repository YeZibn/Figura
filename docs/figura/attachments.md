# Attachment Service：Session 图片与来源边界

> [返回总览](../figura-implementation-overview.md)。范围：当前 `src/figura/attachments/` 和 Runtime 中的附件元数据；新 Figura 尚无 Gateway 上传入口，也没有已实现的 Panel、Evidence 或通用 Source 实体。

## 1. 职责与边界

`FiguraAttachmentService` 验证图片内容，把元数据交给 `FiguraRunStore`，把字节写在由 opaque 附件 ID 派生的私有文件中。它只允许以所属 Session 解析附件。调用期返回的 `ImageBlock` 在[Provider 合同](provider.md#4-完整模型字段)定义；图片字节不进入 `RunInput` 或生命周期事件。

## 2. 内部流转

1. **上传**：先验证 Session、文件名、非空且有界的图片内容和实际媒体类型；生成 `attachment_id`，登记元数据并安装私有文件。元数据仅有下表六项，没有本机路径、hash 或删除状态字段。
2. **引用**：`RunCreateRequest.attachment_ids` 按提交顺序进入唯一 `RunInput`；Store 在 Run 创建事务里校验所有附件属于该 Session 且不重复。Run 引用后，附件不能静默删除或换字节。
3. **解析**：Agent 构建请求时用 `session_id + attachment_id` 解析为内存 `ImageBlock`，核对文件大小和请求总限制；失败时不应先 claim Provider attempt。
4. **删除与对账**：只删除未被 Run 引用的附件；私有目录启动时对账，处理孤儿文件或中断清理。服务端路径不作为公开引用。

## 3. 完整模型字段

### AttachmentMetadata

Session 所拥有的图片元数据；图片字节另存私有文件。 **写入者：**FiguraAttachmentService / Store。**权威位置：**attachments 表。**读取与公开：**附件列表、Run 创建和解析；不公开本机路径。[定义](../../src/figura/runtime/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| AttachmentMetadata.attachment_id | str | 必传 | 附件的不透明身份 | FiguraAttachmentService / Store → attachments 表 → 附件列表、Run 创建和解析；不公开本机路径 |
| AttachmentMetadata.session_id | str | 必传 | 所属 Session 的不透明身份；跨 Session 读取须拒绝 | FiguraAttachmentService / Store → attachments 表 → 附件列表、Run 创建和解析；不公开本机路径 |
| AttachmentMetadata.filename | str | 必传 | 净化后的上传文件名 | FiguraAttachmentService / Store → attachments 表 → 附件列表、Run 创建和解析；不公开本机路径 |
| AttachmentMetadata.media_type | str | 必传 | 由图片内容验证得到的媒体类型 | FiguraAttachmentService / Store → attachments 表 → 附件列表、Run 创建和解析；不公开本机路径 |
| AttachmentMetadata.byte_count | int | 必传 | 原始图片字节数 | FiguraAttachmentService / Store → attachments 表 → 附件列表、Run 创建和解析；不公开本机路径 |
| AttachmentMetadata.created_at | str | 必传 | 创建时的 UTC 时间 | FiguraAttachmentService / Store → attachments 表 → 附件列表、Run 创建和解析；不公开本机路径 |

## 4. 与后续 Source/Panel/Evidence 的边界

当前附件是输入资源，不等于后续设计中的 `SourceRef` 或 `PanelRecord`。完整目标来源/证据链见[后续能力边界](future-boundaries.md)，该链当前尚未进入新 Figura 的 Runtime。代码：[附件服务](../../src/figura/attachments/service.py)、[元数据模型](../../src/figura/runtime/models.py)、[存储](../../src/figura/runtime/store.py)；主规格：[图片附件](../../openspec/figura/openspec/specs/image-attachment-storage/spec.md)。
