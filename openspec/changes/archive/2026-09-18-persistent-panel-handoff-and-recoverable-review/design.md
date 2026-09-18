## Context

本 change 解决的是一次完整链路中的状态边界问题，详见 `proposal.md`。当前 Agent 的 layout context 是单次 run 内存对象，Gateway 虽然持久化 run 和附件，却没有持久化面板交接记录；OCR 和几何传感器对 panel scope 的消费也不统一。审核管理器已经有候选和重试概念，但 source payload 缺失时会直接产生失败结果，Agent loop 没有把可恢复诊断重新交给主模型。

实现必须继续遵守 session-scoped attachment 授权、不得向模型暴露本地路径、默认不启用 SAM、以及使用 `agent` Conda 环境运行 Python 测试的约束。

## Goals / Non-Goals

**Goals:**

- 让同一 session 中的后续 run 能可靠恢复 active source 和第一次拆解得到的 panel。
- 让 OCR、柱状图、折线图、饼图、散点图都通过同一 PanelScope 做局部分析，并保留源图坐标归因。
- 让 source binding failure、语义审核失败和审核运行时失败走不同的恢复路径。
- 让主 Agent 在有预算时修正 ChartSpec、生成新候选并重新审核，同时保证失败候选不发布。
- 让 checkpoint、Gateway 和前端可以解释并恢复上述状态。

**Non-Goals:**

- 不重新引入 SAM，也不在本 change 中改造 SAM 模型或训练数据。
- 不把 OCR 变成 dashboard 拆解器；OCR 只作为已解析范围内的辅助证据。
- 不允许审核阶段调用 OCR、CV、布局或其他工具，保持 VLM-only review 约束。
- 不实现跨 session 的面板共享、云端协作或无限期保存 crop 原图。
- 不通过关闭 source-linked review 来规避附件绑定问题。

## Decisions

### 1. Gateway-owned persistent PanelHandoff registry

面板注册表归 Gateway/session 持有，Agent runtime 只在 run 开始时读取一个经过授权和校验的快照。这样新 Agent 进程不依赖旧的 Python 内存，也不会把完整模型历史当作结构化状态。

PanelHandoff 的逻辑记录包含：

```text
session_id
attachment_id
attachment_sha256
panel_id
panel_revision
name / slug / role / chart_type
source_bbox
analysis_scope
local_origin
source_to_local_transform
confidence / warnings / status
origin_run_id / supersedes_panel_id / updated_at
```

`panel_id` 使用附件哈希、标准化区域和稳定语义形成不依赖运行内序号的身份。新 VLM proposal 通过名称、类型、相对位置和 bbox IoU 与已有记录匹配；匹配不确定时创建新 revision，不静默覆盖旧记录。

### 2. Active source context precedes model history

每个 run 的 source context 按以下优先级解析：

```text
本次明确提交的 attachment IDs
        ↓
session 当前 active attachment
        ↓
无唯一来源时返回 needs_source
```

每一层都要检查 session 所属关系、文件可访问性和内容哈希。ChartSpec 的自由文本 `metadata.source` 只能描述来源，不能取代结构化 source context。这样可以避免 test2 中“源图实际存在，但当前 run 的 attachmentIds 为空”的错误状态。

### 3. Reuse-first decomposition with explicit invalidation

拆解入口先查询有效 panel registry，再决定是否需要调用 VLM 拆解。重复调用不能只由 Prompt 禁止，runtime 还要在已有有效目录时返回复用结果；只有源图变化、没有匹配、旧记录 stale 或用户显式要求时才进入新拆解。

Panel 的 crop 不作为无限期独立事实保存；注册表保存源坐标和派生元数据，局部观察资源按 run 或候选需要生成，并受现有附件和资源生命周期约束。所有派生结果都能回到原 attachment 和 panel revision。

### 4. One scope resolver, two coordinate systems

所有观察工具通过一个共享范围解析层取得局部图像。解析结果包含：

```text
PanelScope: 标题、图例、坐标轴、标签等完整局部范围
MeasurementFrame: PanelScope 内部真正的绘图区
Transform: local ↔ source 坐标变换
```

工具在局部图像上执行 OCR 或几何测量，结果同时返回 local bbox 和 source bbox。若调用方未提供 panel scope，工具可以处理单图，但在多面板输入上必须标记 `unscoped`，不得把整图结果归因给某个 panel。

### 5. Review recovery is a state machine, not a repeated final check

审核流程采用以下状态：

```text
rendered
  → source_preflight
      ├─ needs_source → rebind/resume
      └─ source_ready → vlm_review
                          ├─ pass → published
                          ├─ semantic_fail → agent_correction → new_candidate
                          ├─ runtime_fail → bounded_review_retry
                          └─ limit → retry_exhausted
```

语义失败必须生成新的 ChartSpec digest 和 candidate ID，不能无限审核同一个候选。source binding failure 不应要求模型凭空修改 ChartSpec，而应先尝试从 session 恢复或请求重新绑定。只有通过审核的候选才能进入 published。

### 6. Prompt guidance plus runtime enforcement

运行时 Prompt 增加以下行为约定：先使用 panel inventory，所有局部观察携带 panel ID，审核诊断出现时必须修正并重新 assemble。工具描述也明确 full-image observation 的限制。

但以下规则由 runtime 强制：panel 所属和 hash 校验、scope 解析、source context 继承、review retry budget、候选发布门禁。这样即使模型误调用 decompose 或遗漏 panel ID，也不会静默扩大分析范围。

### 7. Candidate lineage is the single publication history

每个生成候选保存 `candidate_id`、父候选、ChartSpec digest、source/panel refs、review attempt 和状态。审核拒绝只会将当前候选置为 rejected/unpublished；主 Agent 生成新候选后，新的候选继承可追溯关系。Gateway 与前端通过这条 lineage 展示“正在修复”“未发布”和“最终发布”的区别。

## Risks / Trade-offs

- **[VLM bbox 每次略有漂移]** → 使用语义、图表类型、相对位置和 IoU 的有界匹配；不确定时创建 revision，而不是静默复用错误区域。
- **[面板注册表与附件生命周期不一致]** → 所有读取前校验 session、存在性和 hash；附件删除后面板立即 stale，禁止全图 fallback。
- **[局部裁剪切掉标题或数据标签]** → PanelScope 默认包含安全 padding；MeasurementFrame 由工具在 PanelScope 内重新识别。
- **[OCR/测量结果坐标变换出错]** → 统一一个坐标约定，并增加 local→source→local round-trip 测试及源图 overlay 回归。
- **[模型反复调用拆解]** → reuse-first 由 Gateway/runtime 强制，Prompt 只负责引导；重复等价 proposal 必须幂等返回已有 handoff。
- **[审核修复形成循环]** → 区分 review retry 与 new candidate correction，分别设置上限，并要求 semantic retry 的 ChartSpec digest 发生变化。
- **[历史 session 升级兼容]** → 旧 session 没有 panel registry 时视为无目录，首次请求可建立 registry；不迁移未经校验的旧文本 panel ID。
- **[资源占用增加]** → 只持久化 bounded metadata，crop/overlay 作为可清理派生资源；保留已有大小和生命周期限制。

## Migration Plan

1. 先增加 schema 版本、观测字段和空 registry 兼容读取，不改变旧运行的成功路径。
2. 引入 active source 解析和 PanelHandoff 持久化；旧 session 首次使用时按当前有效附件建立目录。
3. 将 OCR 和四类传感器接入共享 scope resolver，并增加局部/源图双坐标输出。
4. 接入 review preflight、结构化 diagnostics、候选 lineage 和 bounded correction。
5. 更新前端状态和执行轨迹，使用 `test2` 及多附件案例做 Gateway 真实链路回归。

回滚时可以关闭新 panel reuse 和 review correction 开关，但仍保留旧候选不发布的安全门禁；已写入的 registry 数据按版本忽略即可，不删除用户附件或历史 run。

## Open Questions

- 多附件 session 是否允许用户在前端显式切换 active source，还是第一阶段只允许单一活动源？建议第一阶段要求显式切换，避免自动猜测。
- panel crop 是否需要作为前端长期可见资源？建议默认只展示按 run 生成的观察结果，PanelHandoff 本身只保存安全元数据和可重建范围。
- 对 source binding 失败是否允许用户选择“按无源数据直接生成”？建议保留为显式用户意图，不作为自动恢复路径。
