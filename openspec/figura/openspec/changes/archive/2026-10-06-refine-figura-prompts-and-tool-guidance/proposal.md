## Why

当前四份固定提示词已覆盖基本职责，但存在重复约束、正向决策指导不足，以及历史取回、修改已有图表和观察边界说明不完整的问题。12 个工具均有工具级描述，但关键参数缺少语义说明；另外已确认图像读取 Schema 接受不可读引用，以及 Panel 透明区在检测解码时重新暴露原像素，需要使文案、参数合同和实际行为一致。

## What Changes

- 整体改写 `agent.md`、`evidence.md`、`workflow.md`、`response.md`，保留分层与模型自主决策，补齐历史取回、已有 Figure 修改、结果判断和任务结束指导。
- 审校全部 12 个工具的 `description`，在原生参数 Schema 中补齐坐标、范围、引用、搜索、选择器及 ChartSpec 数据语义；不把完整工具手册复制进固定提示词。
- 新增独立 `agent/prompting/assets/compaction.md`，通过独立加载入口构造纯文本、无工具摘要请求；摘要升级为机器可读的 v2 分层合同，分别保存当前目标、约束、决定、事实、完成／进行中／待办／阻塞、未决问题、资源与未接受提议，每项保留来源引用。v1 checkpoint 继续可读，仅在下一次压缩时重整为 v2；移除模型无法判断的窗口占比指令。
- **BREAKING**：收窄 `read_resource_image.resource_ref`，仅接受 Attachment、Panel、OCR、Measurement、ChartRender 引用；消息、工具结果和 ChartFigure 继续通过各自适用工具读取或显式渲染。新 Registry 升为 `figura-web-v8`。
- 统一图像观察解码：透明像素先合成到白色背景，完全透明区不作为 OCR／测量证据；透明区掩码与可选观察范围相交，保留原尺寸与坐标。
- 增加加载、请求隔离、参数投影、历史读取、透明图像及恢复合同回归验证，并同步实现文档。

## Capabilities

### New Capabilities

- `image-observation-decoding`: 五种图像观察工具共用的透明度、像素中和、观察范围与坐标保留合同。

### Modified Capabilities

- `agent-react-execution`: 扩展任务驱动的固定提示规则，覆盖渐进历史读取、有依据的展示命名、结果判断、修改已有 Figure 和停止无效重复动作。
- `tool-runtime`: 规定模型可见工具说明与关键参数语义的职责，覆盖当前 12 个工具及实际结果边界。
- `session-context-compaction`: 将摘要生成规则独立成 Markdown 资产，明确增量归纳与引用合同、加载隔离和请求身份。
- `session-context-retrieval`: 收窄可读图像引用 Schema，明确文本搜索、局部选择器和完整结构化资源读取的模型可见说明。

## Impact

- Agent：`src/figura/agent/prompting/`、`agent/request.py`；保持普通请求层顺序、动态数据投影、现有压缩触发与 fallback 行为。
- Tools / Charts：`src/figura/tools/implementations/`、`tools/measurements/observation_scope.py`、Charts 参数 Schema 注释和 `bootstrap.py` Registry 版本；工具名称和已有合法调用字段保持稳定。
- Runtime / Provider：复用现有摘要来源授权、请求 digest 与绑定恢复；仅升级摘要 JSON 合同版本，不增加持久字段、数据库迁移或新的重试策略。
- 测试与文档：相关 Figura pytest、`docs/figura/agent.md`、`tools.md`、必要的 Memory / Sources 边界说明与系统总览；无需前端改动、新依赖或新增配置。
- 升级前应让旧 Registry 的活动 Run 结束或停止并完成协调；旧版闭合交互仍作为只读历史保留，不增加 v7 未完成工具兼容执行器。已绑定请求遇到 prompt / registry digest 变化继续采用现有身份不匹配处理，不绕过校验。
- 本 change 不调整上下文阈值、历史选取算法、输出预算或网络重试，不引入工具自动失败重试、语义搜索或生成图审核。
