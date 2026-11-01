## Why

Figura 当前将结构化工具结果与图像反馈拆成两条路径：工具和 Runtime 仅记录 JSON，Agent 再按工具名重建图片并追加普通 user 消息。需要把图片、资源身份与观察 hint 归入对应的多模态工具结果，使历史读取、按需加载、中断恢复和 Provider 编码使用同一合同，避免新增图像工具时继续扩展中央附图分支。

## What Changes

- **BREAKING**：九个 Figura 工具统一返回 `ToolOutput`；成功业务数据与有序媒体输出分开校验，规范 `ToolExecutionResult` / `ToolResultFact` 增加 `attachments`。不接受字典和新对象双轨返回，不保留在线格式升级适配器。
- 在 Sources 保存不可变 OCR／测量标注 PNG，并以完整类型化引用、图片类型、尺寸、字节数与 SHA-256 描述附件。原图、Panel、ChartRender 复用原资源身份；文件先安装、结果事实与 checkpoint 随后事务提交。
- 将中立资源引用移至公共值类型模块；`RunExecutionState` 保持 `run_id + resources`，从已提交事实派生资源及其附件描述。Prompt 索引、历史工具与加载工具复用同一引用，读取不创建新的原资源 ID。
- **BREAKING**：Memory 表达结构化工具观察和附件引用；Agent 在同一调用的工具消息内投影业务 JSON、图片身份、相邻 hint 与图片。删除普通 user 图片追加路径及按工具名推断图像的中央分支。
- 稳定观察规则与 hint 模板继续由 `image_feedback.md` 提供，图片类型统一为 original / ocr_annotation / measurement_annotation / rendered；无图片时不注入图片 hint，不引入审核门控或额外模型调用。
- Provider 按固定 Provider/model 的原生多模态工具结果能力编码；DeepSeek 使用原生 tool 内容块，Qwen／MiMo 以精确接口合同和小规模图像识别验收确认能力。不支持则在本地明确拒绝，不静默转普通 user 消息、丢图或更换协议／Provider。
- 保留最新待观察完整工具批次；历史投影省略旧图片字节但保留附件引用和未加载标记。摘要只消费数据与引用，历史图片通过显式读取重新进入当前工具结果；估算继续使用原有图片近似口径。
- **BREAKING**：实施带备份和回滚的一次性数据迁移与 Registry 切换，完整迁移可确认附件、明确标记历史标注重建来源，保留不可读图片的原始文本事实；不重跑历史业务工具、不删除历史、不保留旧在线读写管线。
- Gateway 的既有观察图片路由读取同一已提交媒体；维持 Session 授权、私有文件、受限详情、PNG 响应和会话删除语义，不新增媒体上传／路径读取接口。

## Capabilities

### New Capabilities
- `tool-result-media`: 中立图像输出／附件合同、不可变媒体保存、身份与完整性、会话清理及一次性切换迁移。

### Modified Capabilities
- `tool-runtime`: 统一 handler 输出及成功／失败附件合同，通用媒体验证，取消纯字典成功返回。
- `durable-tool-execution`: 附件描述随工具结果与进度原子提交，恢复不发布未提交图片。
- `model-provider`: 原生多模态工具结果内容与能力拒绝，删除 user-only 图片的统一限制。
- `session-memory`: 规范工具消息保存业务观察和附件引用，消息不携带图片字节。
- `agent-react-execution`: 同调用内 JSON／hint／图片投影、按附件选择而非按工具名推断。
- `run-execution-resources`: 资源目录派生附件元数据，统一读取已保存标注图片。
- `session-context-retrieval`: 精确读取返回附件引用，历史图片由当前读取调用返回并保留原资源身份。
- `session-context-compaction`: 保留待观察完整交互，压缩附件引用而非媒体字节或 hint。
- `panel-image-observation`: load_image 返回原图附件，移除普通 user 图片与跨调用去重语义。
- `ocr-text-observation`: 业务结果仍保留完整 OCR 合同，标注图通过外层附件交付。
- `chart-family-measurement`: 保持历史测量业务 payload 原样，明确仅允许一次性外层媒体描述迁移，不升级旧家族合同。
- `chart-rendering`: ChartRender PNG 使用统一附件合同与原身份发布。
- `figura-web-gateway`: 观察图读取已保存的已提交媒体，不在 Gateway 重绘。
- `local-context-token-estimation`: 统计工具内容中的实际图片和 hint，旧媒体引用不计图片成本。

## Impact

涉及 `src/figura/{tools,runtime,sources,memory,agent,providers,shared,web,storage}` 的合同、编解码、提交、查询和迁移，以及相应 Python 测试和实现文档。新 Figura 的工具输入参数、ChartSpec／ChartFigure 与测量业务 Schema、Run/SSE 身份和前端 API 形状保持本次既定边界；必要的后端实现替换不扩散到旧 chartagent。

本 change 仅规划。Provider 文档支持与真实模型可见图片是不同验收层次；不能以 HTTP 成功、离线 mock 或现有大任务结果替代原生工具图片的识别验收。付费在线验证使用最小可辨图样，不运行完整图表评测。

