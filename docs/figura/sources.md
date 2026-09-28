# Sources：当前附件输入与授权

> [返回总览](../figura-implementation-overview.md)。范围：当前 `src/figura/attachments/`、Runtime 中的附件元数据和 Web Gateway 对附件服务的调用。Panel 有独立 owner，见[Panels 专题](panels.md)；Evidence 或通用 Source 实体仍未实现。

## 1. 职责与边界

`FiguraAttachmentService` 验证图片内容，把元数据交给 `FiguraRunStore`，把字节写在由 opaque 附件 ID 派生的私有文件中。它只允许以所属 Session 解析附件。Web Gateway 将此能力映射为 Session 内上传、列表、内容读取和删除端点；公开元数据 DTO 归[网页端边界](web.md#4-web-dto-字段)，本篇仍是附件元数据的权威 owner。调用期返回的 `ImageBlock` 在[Provider 合同](provider.md#4-完整模型字段)定义；图片字节不进入 `RunInput` 或生命周期事件。

## 2. 内部流转

1. **网页上传**：浏览器向 Gateway 的 Session attachment 路由提交原始图片字节和文件名 query。Gateway 委托 Attachment Service；服务验证 Session、文件名、非空且有界的图片内容和实际媒体类型，生成 `attachment_id`，登记元数据并安装私有文件。元数据仅有下表六项，没有本机路径、hash 或删除状态字段；返回值再映射为公开 DTO。
2. **引用**：`RunCreateRequest.attachment_ids` 按提交顺序进入唯一 `RunInput`；Store 在 Run 创建事务里校验所有附件属于该 Session 且不重复。Run 引用后，附件不能静默删除或换字节。
3. **网页读取与显式模型加载**：浏览器按所属 Session 列出附件，预览内容时请求 Session-scoped content route；Gateway 以 Session ID 委托服务解析，返回已验证的 image bytes、媒体类型及 `no-store` 响应头。Agent 的图像清单只列出被当前 Run 或较早终态 Run 引用的附件 ID 和文件名。模型调用 `load_image` 后，Agent 才在下一次 Provider 请求中按 `session_id + attachment_id` 解析为内存 `ImageBlock`，并在 attempt claim 前校验大小和请求总限制。
4. **删除与对账**：Gateway 只允许通过所属 Session 删除；服务只删除未被 Run 引用的附件。私有目录启动时对账，处理孤儿文件或中断清理。服务端路径不作为公开引用。

## 3. 完整模型字段

### AttachmentMetadata

Session 所拥有的图片元数据；图片字节另存私有文件。 **写入者：**FiguraAttachmentService / Store。**权威位置：**attachments 表。**读取与公开：**附件列表、Run 创建和解析；不公开本机路径。[定义](../../src/figura/runtime/domain/models.py)。

| 完整字段路径 | 类型 | 构造默认 | 含义与约束 | 写入 → 权威 → 读取/公开 |
|---|---|---|---|---|
| AttachmentMetadata.attachment_id | str | 必传 | 附件的不透明身份 | FiguraAttachmentService / Store → attachments 表 → 附件列表、Run 创建和解析；不公开本机路径 |
| AttachmentMetadata.session_id | str | 必传 | 所属 Session 的不透明身份；跨 Session 读取须拒绝 | FiguraAttachmentService / Store → attachments 表 → 附件列表、Run 创建和解析；不公开本机路径 |
| AttachmentMetadata.filename | str | 必传 | 净化后的上传文件名 | FiguraAttachmentService / Store → attachments 表 → 附件列表、Run 创建和解析；不公开本机路径 |
| AttachmentMetadata.media_type | str | 必传 | 由图片内容验证得到的媒体类型 | FiguraAttachmentService / Store → attachments 表 → 附件列表、Run 创建和解析；不公开本机路径 |
| AttachmentMetadata.byte_count | int | 必传 | 原始图片字节数 | FiguraAttachmentService / Store → attachments 表 → 附件列表、Run 创建和解析；不公开本机路径 |
| AttachmentMetadata.created_at | str | 必传 | 创建时的 UTC 时间 | FiguraAttachmentService / Store → attachments 表 → 附件列表、Run 创建和解析；不公开本机路径 |

## 4. 与 Source/Panel/Evidence 的边界

当前附件是输入资源，不等同于由分割工具创建的 `PanelRecord`。两种图像身份、存储和读取生命周期不同；Panel 会引用源 Attachment ID，但归属独立 [Panels](panels.md) 专题。来源与证据目标链见[总览中的规划能力](../figura-implementation-overview.md#4-规划能力与边界)；未来 Evidence 是否归本领域，应按独立 owner 和生命周期重新判断。代码：[附件服务](../../src/figura/attachments/service.py)、[Gateway application](../../src/figura/gateway/application.py)、[元数据模型](../../src/figura/runtime/domain/models.py)、[兼容存储门面](../../src/figura/runtime/store.py)；主规格：[图片附件](../../openspec/figura/openspec/specs/image-attachment-storage/spec.md)、[Web Gateway](../../openspec/figura/openspec/specs/figura-web-gateway/spec.md)。
