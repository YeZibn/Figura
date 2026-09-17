## 1. VLM 审核契约与调用边界

- [x] 1.1 定义内部 VLM 审核请求与规范化结果模型，固定 `decision`、`confidence`、逐项 `checks`、有界 `issues`、candidate/review/ChartSpec 归因字段及 `reviewMode=vlm` 元数据。
- [x] 1.2 实现审核专用提示词和多模态消息构造，将授权原图、生成候选图与不可变 ChartSpec 组合为一次成对输入，并确保不携带本地路径、无关附件、历史 reasoning 或原始 provider 响应。
- [x] 1.3 通过现有 LLM client 发起一次无 tools 的内部 VLM 调用，隔离该调用的主 Agent 历史，并接入既有 provider、超时、token 限制和 trace 观察能力。
- [x] 1.4 实现严格的审核结果解析与边界校验；对非法 JSON、未知枚举、越界置信度、超长字段、缺少决策或决策与问题矛盾的结果统一返回非发布失败。
- [x] 1.5 重写审核提示词的结构化指导，明确原图、候选图与 ChartSpec 的证据职责，区分画布旋转、图表横纵方向、坐标轴方向和零基线，并加入 bar、line、pie、scatter 的专项检查流程。
- [x] 1.6 收紧审核 JSON 解析契约：拒绝额外顶层字段，强制 `pass`、`pass_with_warning`、`fail` 与检查状态及问题严重性的关系一致，并保留有界的 issue code/location/message。

## 2. 候选生命周期与发布门禁

- [x] 2.1 将候选审核中的 OCR、CV、几何和图表测量调用移出活动审核路径，保留 ChartSpec 结构校验、PNG 解码、尺寸、大小、空白图和其他发布安全检查。
- [x] 2.2 将规范化 VLM 结果绑定到 candidate ID、review ID、run ID 和 ChartSpec digest，并原子更新 `review_pending`、`verified`、`warning`、`review_failed`、`timed_out` 与 `retry_exhausted` 状态。
- [x] 2.3 实现 `pass`、允许的 `pass_with_warning`、`fail`、无效输出、源图不可用和异常响应的发布转换规则，确保只有通过安全检查和 VLM 审核的候选才能生成最终 artifact reference。
- [x] 2.4 实现 VLM 阻塞问题到主 Agent 的有界修正上下文，支持修正 ChartSpec 后创建新的候选，并保证旧候选不可变、可归因且不被重复发布。
- [x] 2.5 实现内部审核调用与候选重试的 deadline、attempt、幂等和 stale-reference 检查，验证超时或重复事件不会留下无限 pending 或改变其他候选。

## 3. Agent 与运行时接入

- [x] 3.1 在渲染候选创建后接入自动 VLM 审核钩子，保证每个 semantic-review-required candidate 恰好触发一次本次尝试的无工具审核，并将结果返回到正常候选观察中。
- [x] 3.2 从 runtime factory、Agent 注册表、适配器和 schema 中移除 `review_generated_chart` 的主模型可见工具面，同时保留 `assemble_spec`、`render_chart` 及生成前的辅助证据工具。
- [x] 3.3 更新 Agent 静态系统提示词，删除主动调用审核工具和 `evidence_refs` 决策要求，说明审核自动完成、失败时如何依据结构化诊断修正并重新生成。
- [x] 3.4 修改 Agent 的最终回答、step-budget 和异常终止路径，同时检查 pending、failed、timed-out、retry-exhausted 状态，禁止自由文本绕过发布门禁。
- [x] 3.5 确认内部 VLM 审核请求不被追加到主 Agent 历史或普通工具消息序列，并确认主 Agent 仍能看到候选图及结构化审核上下文以执行修正。
- [x] 3.6 优化主流程系统提示词，明确 render 结果只是候选预览，使用 `publicationStatus` 作为发布权威，区分 `reviewStatus=completed` 与审核通过，并规定失败候选必须经过 `assemble_spec → render_chart` 重试链路。

## 4. Trace、Gateway 与前端状态

- [x] 4.1 增加内部审核开始、完成、警告、拒绝和超时的有界 trace 字段，标明 `internal_review`、`tool_count=0`、candidate/review ID 和最终决策，但不记录提示词、图片字节或 provider 原文。
- [x] 4.2 更新 Gateway 候选与最终 artifact 投影，持久化规范化 VLM 审核状态和诊断，并继续阻止 pending、failed 和 rejected candidate 进入最终下载路由。
- [x] 4.3 更新前端生成结果状态映射，展示“VLM 审核中/已通过/带警告/未通过”和有界问题说明，保持已发布与可下载状态的现有安全边界。

## 5. 回归测试与验证

- [x] 5.1 为审核结果解析增加 pass、warning、fail、非法响应、越界字段和工具调用痕迹的单元测试。
- [x] 5.2 为候选管理增加安全检查与 VLM 结果组合、候选身份绑定、发布转换、幂等、超时和重试耗尽测试。
- [x] 5.3 为 Agent 增加测试，验证渲染后自动触发一次无 tools VLM、主模型工具列表不含 `review_generated_chart`、内部消息不进入主历史且失败诊断可驱动重新生成。
- [x] 5.4 增加终止路径回归测试，验证模型在 review failed、pending、timeout 或 retry-exhausted 状态下不能直接返回已验证或已发布结果。
- [x] 5.5 更新 Gateway、trace 和前端状态测试，覆盖发布、带警告、拒绝、审核超时以及候选预览/最终 artifact 的边界。
- [x] 5.6 使用 `conda run -n agent python -m pytest -q` 运行完整 Python 测试，执行 `git diff --check`，并在前端运行 `npm run build` 与 `npm run smoke`。
- [x] 5.7 增加严格 JSON 契约回归测试，覆盖 clean pass、warning、fail、柱状图基准线错误、额外字段、缺失字段、决策冲突和超长 issue。
- [x] 5.8 增加主流程提示词回归测试，验证候选预览与最终发布的区分、`publicationStatus` 权威规则、失败诊断驱动重生成以及源图证据缺失时的声明边界。
