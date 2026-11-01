## 1. 合同与所有权

- [x] 1.1 核对三个固定 Provider/model 的 Chat Completions 工具图片原生合同，记录支持／不支持／未验证矩阵；确定能力拒绝的本地准备入口，不采用普通 user 图片或自动协议切换。
- [x] 1.2 将 ImageResourceRef、ToolResourceRef 及 ResourceRef 移至公共纯值类型模块，统一全部当前调用方导入，不保留新旧模块 re-export 适配。
- [x] 1.3 实现中立 ImageKind、ResourceImage、ToolImageOutput、ToolImageAttachment 与 ToolOutput，明确所有字段、四种图片类型、provenance 和调用期字节边界。
- [x] 1.4 扩展 ToolExecutionResult 为 result/error/attachments 单合同，失败附件必须为空；九个工具不得再返回裸 dict 或新旧联合格式。
- [x] 1.5 增加业务结果、媒体类型／尺寸／字节／摘要、资源 kind 与所属调用的一致性验证；复用已有完整 payload 和图片保护，不引入额外通用计数限制。

## 2. 私有媒体保存与资源服务

- [x] 2.1 Sources 的 Attachment/Panel 图片读取返回中立 ResourceImage，更新全部消费者，移除 Sources 对 Provider.ImageBlock 的依赖。
- [x] 2.2 实现 Session 私有、按内容摘要不可变安装的标注媒体存储，以及通用媒体规范化提交器；复用原图／Panel／ChartRender 文件和原身份，结果只保留附件描述。
- [x] 2.3 实现精确 descriptor 校验和已保存媒体读取，区分新图片准备失败、已提交图片丢失／损坏与业务效果未知，不在读取时重绘或静默修复。
- [x] 2.4 将新媒体纳入 Session 删除暂存、回滚恢复和启动对账；无引用媒体仅在没有活动写入的独占维护边界清理。
- [x] 2.5 增加安装后未提交、摘要去重、重算输出变化、写入中清理竞争、删除回滚及跨 Session 相同内容隔离的故障注入回归。

## 3. 九个工具统一输出

- [x] 3.1 迁移 load_image 和 read_resource_image，返回原资源图片；验证当前读取 call_id 与原资源引用分离、重读不创建资源或媒体文件。
- [x] 3.2 迁移 extract_text 和 measure_chart，将标注绘制移到工具执行阶段并返回临时媒体；保持当前 OCR、十类测量业务 Schema、available／partial／unsupported／null 语义和 replay_safe 分类。
- [x] 3.3 迁移 render_chart_figure，使用原幂等存储中的规范 PNG 构造 rendered 附件，确保 result 和附件尺寸／摘要一致，并保留既有 unknown-effect 恢复。
- [x] 3.4 迁移 decompose_chart_image、assemble_chart_figure、search_history 和 read_history 到同一个 ToolOutput，images 为空，不增加隐式 Panel 加载、绘图或历史像素读取。
- [x] 3.5 更新九个工具的描述与必要结果外层说明，明确多模态结果、稳定引用、失败语义和自主后续决策，删除“普通 user 追加图片”说明；更新 Registry 版本。

## 4. Runtime 持久化与一次性迁移

- [x] 4.1 扩展 ToolResultFact 及严格编解码、完整 envelope guard 和数据库约束，附件描述与业务结果、checkpoint、进度事件在原结果事务中提交。
- [x] 4.2 更新 DurableToolExecutor 和恢复读取，保证已提交结果不重跑、未提交文件不发布、重算业务数据不混用旧候选图，写入效果未知仍走原恢复合同。
- [x] 4.3 实现独占维护迁移入口、active Run／owner／compaction operation 准入检查、SQLite＋Sources 配对备份及私有迁移审计；正常启动不自动终结旧任务或重绑冻结请求。
- [x] 4.4 实现一次性外层结果转换：保留原业务 payload、全部 ID、事件顺序和 Provider 审计；恢复可验证附件，旧标注只在维护时重建并标记 provenance，不支持或缺失媒体保留 attachments=[] 及原文本结果。
- [x] 4.5 验证新库初始化、迁移失败原子回滚、重入、备份恢复和全量历史可读；确认迁移不调用历史 OCR／测量／组装／渲染／Provider。
- [x] 4.6 将新 Registry、结果编解码和 schema 激活绑定为一次切换；移除新旧输出转换器和旧线上附图通道，维护迁移不得被线上读取入口调用。

## 5. Memory、资源目录与精确读取

- [x] 5.1 将 Memory.ToolMessage 改为结构化 outcome/result/error/attachments 投影，保留 Run／tool sequence／call_id；统一观察序列化器，不维护第二份权威 content 字符串。
- [x] 5.2 从 ToolResultFact 重建 OCR／measurement／ChartRender 附件描述，RunExecutionState 顶层保持 run_id/resources；Prompt 仅投影引用、摘要和图片可用信息，完整目录不被裁剪。
- [x] 5.3 改造统一图片读取为“授权引用→提交描述→已保存字节”，禁止 Gateway／Agent／历史读取时重绘；旧无附件历史数据仍可文本读取。
- [x] 5.4 更新 read_history、search_history 和历史图像读取，保持完整引用、trust、selector／range、授权前缀和 ChartFigure 必须显式渲染的合同。
- [x] 5.5 回归跨 Run 同 call_id、历史资源与新 read call 身份、未来／跨 Session／未提交引用、无可用媒体与异常历史尾部，确认不伪造结果或新建旧资源。

## 6. Agent、hint 与上下文投影

- [x] 6.1 将 JSON、附件定位、相邻 hint 和 ImageBlock 水合到同一调用的一条 TOOL 消息；全部图像选择使用附件数据，不再匹配工具名称。
- [x] 6.2 删除 build_observation_messages 的普通 user 消息追加路径与重复观察序列化；保留 call order、attachment order，并移除跨调用图片去重。
- [x] 6.3 统一四种 image_kind 与 image_feedback.md 的 Common／Rules／Cue 映射；系统保留稳定规则、图旁提供短 hint 和原资源身份，无图不生成 hint，不增加 verify 门控。
- [x] 6.4 实现最新视觉批次发送、旧结果仅保留描述及 images_loaded=false、显式历史重载的当前结果投影；同一逻辑请求重试保留相同媒体和 hint，不持久化“已看过”队列。
- [x] 6.5 修正压缩选择与 operation 校验，保护尚待普通模型观察的完整带图批次，即使其他 protected history 已耗尽软预算；当前 Run 较早完整交互仍可压缩。
- [x] 6.6 摘要输入只使用业务数据与附件引用／provenance，排除图像字节、Cue 和 images_loaded；保证全部用户原始输入和来源读取不变。
- [x] 6.7 验证工具内容中的图片 occurrence 和 hint 纳入原 token 估算，引用未加载图片不收视觉成本，Base64 不按普通文本计数。

## 7. Provider 原生多模态工具结果

- [x] 7.1 将 user-only 图片校验替换为 ProviderPolicy 的明确 supports_tool_result_images 能力；保持通用 TOOL 关联、内容保护及本地 unsupported_capability 拒绝，不加消息降级分支。
- [x] 7.2 实现 DeepSeek 工具消息原生文本／图片数组，按精确合同实现其他支持模型；未满足原生合同的模型明确不可用，不丢图、换 Provider 或自动改端点。
- [x] 7.3 验证角色／tool_call_id／顺序／hint／图片全部进入原 request_fingerprint；现有资产 manifest 从同一描述导出，历史 Provider 审计不改写，continuation／流式／重试额度不变。
- [x] 7.4 增加同批两图、重复资源不同调用、混合成功失败、能力拒绝、资产变化和替代 attempt 同 body 的离线 Provider 回归。

## 8. Gateway 与展示边界

- [x] 8.1 观察图片路由改读同一已提交 PNG，保留现有 Session/Run/call URL、PNG/no-store、鉴权与安全错误，不再重绘。
- [x] 8.2 回归时间线摘要／详情、生成图预览下载、缺失媒体和会话删除恢复；确保 DTO/SSE 不直接暴露完整结果、附件清单、hint、Prompt、路径或字节。

## 9. 验收、文档与清理

- [x] 9.1 在 agent Conda 环境依次运行相关工具／持久化／Sources／Memory／Agent／Provider／压缩／Gateway 窄测试，以及 tests/test_figura_prompting.py、tests/test_prompting.py 和相关 CLI 测试；再运行全量 pytest，记录既有失败与新回归的区别。
- [x] 9.2 如实现涉及前端或启动器调整，分别完成 npm run build、npm run smoke 及需要的 npm run smoke:launcher；未涉及则在验证记录说明范围，不宣称已做 UI 验收。
- [x] 9.3 对每个准备启用工具图片能力的固定模型执行最小两图识别：文本／文件名不泄漏答案，检查图片特征与 call ID 对应，记录实际 usage、识别结果和安全失败类别；无凭据或未通过的模型保持未启用并如实记录。
- [x] 9.4 更新 docs/figura-implementation-overview.md 及 tools、runtime、sources、memory、agent、provider、web、validation／evaluation 的相关字段和行为，区分本地验证与真实 Provider 识别结论。
- [x] 9.5 审计全链路只剩一套合同：无纯字典 handler 适配、按工具名补图、普通 user 图片通道、正常读取时重绘或历史资源新编号；运行 git diff --check 与 OpenSpec 严格校验。

