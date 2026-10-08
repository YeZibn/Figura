## Context

动机见 proposal.md。当前 `build_observation_messages` 从最新 MODEL_RESPONSE 对应的完整工具批次选择成功结果，在普通规范历史后附加一个 USER 多模态消息。原图、OCR/测量标注图、ChartRender PNG 与历史重载图片均已有授权读取路径。图像身份信息目前较简短；原始 TOOL JSON 已在历史中，无需复制。

`AgentRequestBuilder` 组合这些消息与三层基础 SYSTEM 指令，可另有摘要层；`prompt_digest` 已覆盖指令内容，Provider request binding 已执行恢复身份校验。现有规则要求回看，但不存在独立图表验证能力。遗留空 change `add-figura-main-agent-verification` 不是本方案的实现基础，本次不修改它。

## Goals / Non-Goals

**Goals:** 在每张实际回传图片附近突出适用观察方向，保持图片与来源一一对应；当前自动回传与历史显式读取共用映射；回看融入下一次正常推理。

**Non-Goals:** 不新增审核工具/状态/模型请求/数据库迁移；不建设通用 Hook Registry；不改变图片授权、数量、去重、工具批次边界或最终答复合同；不扩展测量算法，也不自动取回源图或完整历史。

## Decisions

### 1. 在 Agent 图像反馈构造处使用一个确定性的提示构造函数

所谓钩子是构造期纯函数，不是执行事件或异步回调。只在授权读取和结果一致性校验通过、即将追加 ImageBlock 时追加 TextBlock。原 TOOL JSON 不变；没有图片就没有局部提醒。完整批次提交后构造一次请求，不在批次中间调用模型。

建议内部分类 `original | ocr | measurement | rendered`，仅作 prompting 内部值；不修改 Provider `observation_kind` 的 `original | annotated | rendered` 合同。OCR 与 measurement 通过权威资源 content 类型区分，不能仅根据 `annotated` 猜测。

### 2. 一个 Markdown 资产管理规则与简短提醒

新增 `prompting/assets/image_feedback.md`，使用固定标题 Common、Original、OCR、Measurement、Rendered。每个类型含 Rules 与 Cue 子段；loader 明确解析这些封闭标题，缺失/重复/空段沿现有 PromptAssetError 失败方式处理，不引入模板引擎或插件配置。

Common 和各类 Rules 作为稳定规则加入第一 SYSTEM 指令，与现有四份资产保持原有相对顺序。这样所有行为规则来自受控资产，并自然参与既有 prompt_digest，不增加 SYSTEM 层。Cue 是简短邻近提醒，在每张图之前按类型选取；第一 SYSTEM 同时包含各类 Cue 的原文或其规则化条目，使 Cue 资产变化也参与 digest，不能只散落在 USER 消息中而漏掉请求身份。

每个 Cue 用一句至两句提醒即可；详细规则在 SYSTEM 中，避免每张图片重复完整检查清单。无图请求依然拥有稳定原则，但不追加局部提醒，也不据此加载图片。摘要专用请求仍只读取 compaction.md。

### 3. 图像邻近文本合同

每张图前使用一个 TextBlock，由两部分组成：JSON 编码的身份数据，以及资产提供的短 Cue。固定分隔说明前者是数据、后者是系统提供的观察提醒。文件名、标题、OCR 内容绝不用于选择或编写指令；可以省略文件名，避免当前括号拼接产生边界混淆。

| 调用期身份字段 | 来源与用途 |
|---|---|
| feedback_kind | 上述四类内部分类 |
| resource_ref | 与相邻 ImageBlock.source_ref 完全一致；Attachment/Panel 用 kind/id，工具资源用 kind/run_id/call_id |
| trigger_call | 当前加载或产生该图片的 run_id/call_id/tool_name；历史 origin 和当前加载身份分开 |

这些只是消息内序列化数据，不新增公开 DTO、Run 字段或持久记录。现有图片仍保留原始 ref/observation_kind/媒体类型。

`load_image` 的 source 去重在生成 Cue 前完成。`read_resource_image` 沿现有数量语义，不新增全局去重；每张实际输出的图片匹配一个 Cue。按现有调用顺序排列，混合批次不会把图像说明与另一个结果串联。

### 4. 四类内容的具体边界

| 分类 | Rules 要点 | 邻近 Cue 建议 |
|---|---|---|
| original | 按目标观察布局、家族、轴/刻度/标签/图例；不强制后续工具调用 | 请观察这张原图中与当前任务有关的结构和线索，按需决定下一步。 |
| ocr | 结合对应 JSON 看覆盖、框位置和关联；框内文本仍是候选识别；缺少完整 JSON 时按需 read_history | 请结合对应 OCR 结果，留意文字遗漏、框位置和标签关联；标注不保证识别正确。 |
| measurement | 关注遗漏、重复、图例误检和系列/类别对应；核对 scope、status、缺口与校准；几何不是业务数值 | 请结合对应测量结果，检查标记是否遗漏或误检；数值可靠性仍需校准依据。 |
| rendered | 用户目标及已知数据与生成内容对应；图例/文字/遮挡/裁切/布局；源图未加载不能声称已对照 | 请回看这张生成图的内容对应与可见布局；发现有依据的问题时自主决定修正或继续。 |

所有类型共享：标注是候选观察，绘制是过程成功；不能自动设立 pass/fail。模型按任务自主补证据、修正、继续或交付，不要求暴露推理或生成报告。标注图被遮盖、刻度不可辨或来源缺失时说明不确定性，不能以视觉印象替代精确数值验证。

### 5. 恢复与状态

图片与提醒都从同一授权前缀重建。图片读取失败仍按现有安全失败路径处理，不能留下孤立提醒、杜撰图片或放宽授权；这不是可随意吞掉的审核失败。恢复不新增检查调用，Provider retry 仍执行既有逻辑请求身份规则。正常升级的资产变化可能导致旧绑定不匹配，沿现有错误合同处理，不静默换提示重发、不新建兼容层。

### 6. 验证分层

离线请求测试确认四类路由、邻近身份、历史 origin、混合顺序、source 去重、无图不触发、资产缺失和 digest 变化。Executor 回归确认一批工具后的下一次请求仍为普通 MODEL，失败/恢复路径不产生额外模型调用。恢复测试包含已有绑定及 Provider-private continuation，保证提示改造不改变原响应关联。

少量真实模型实验观察遗漏类别、图例误检、标签遮挡及多图继续任务场景，记录模型条件与真实行动；若无可用 Provider，明确注明未验证模型行为。测试通过仅证明提示正确送达，不代表模型一定发现问题。

## Risks / Trade-offs

- [模型可能忽略或误解提醒] → 明确来源和关注点，真实样例观察；不宣传准确率提升。
- [增加 token 或诱发无效修正] → 每图只放短 Cue，详细规则集中在 SYSTEM；明确有依据才修正，无问题可继续。
- [图中或名称含指令] → 固定受控规则、JSON 身份编码和不可信来源说明，不把源数据提升为政策。
- [历史图片缺少完整结果或源图] → 指明可见范围，按需读取，不自动补齐资源。
- [提示更新影响运行中请求身份] → 保持严格绑定检测，部署尽量在无运行中请求时完成，不增加迁移适配。

## Migration Plan

实现资产与局部反馈、完成离线验证、更新领域文档后正常部署；无 DB、工具 Registry 或 HTTP/SSE 迁移。主规格同步与归档在用户后续明确请求时执行。回滚为恢复先前提示资产与消息构造；绑定恢复仍遵循原有身份校验。暂不调整前端、环境变量或用户配置。
