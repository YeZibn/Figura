## Context

See `proposal.md` for the motivation and breaking-change boundary. 当前链路的
事实来源仍然是 Gateway 持久化的有序 execution events，但事件语义在多个位置
被补全：Python 事件规范化层、审核流程、前端 `projectDecisionTimeline`、
`normalizeTimeline` 和评测读取层各自保留了一部分规则。实际运行中，审核生产
同时产生 shared `review_*` 和内部 `chart_review_*` 事件；前端又把工具状态和
decision unit 状态分别归约，导致同一个候选出现多个审核节点和相互矛盾的状态。

本 change 是一次协议破坏性重构。实现完成前清理旧的本地运行记录和评测夹具，
不尝试读取或转换旧格式事件。

## Goals / Non-Goals

**Goals:**

- 让新的时间线事件在生产端一次性具备完整、唯一、可验证的语义关联。
- 让每个 candidate attempt 只有一个 review identity 和一条审核生命周期。
- 让工具调用、工具结果、生成候选、审核和发布由一个前端状态归约模型展示。
- 统一用户可见的中文标题、阶段和状态；原始英文 `kind` 只保留在技术详情。
- 删除 legacy、unknown、兼容别名和基于工具名/序号的关联猜测。
- 让普通运行和评测工作台继续使用同一份时间线投影。

**Non-Goals:**

- 不改变测量算法、ChartSpec 语义、生成图审核的判断标准或 repair policy。
- 不改变 Gateway 的 SSE 重连、游标、幂等和运行恢复机制。
- 不改变生成图 artifact 的存储、预览、下载和发布权限边界。
- 不为旧运行记录提供迁移读取、字段补全或兼容渲染路径。

## Decisions

### 1. 用严格事件工厂统一语义，而不是增加前端兜底

所有进入时间线的业务事件由一个明确的事件契约生成。事件生产者负责提供
`unit_id`、`call_id/review_id`、candidate/attempt 引用和状态事实；固定的事件
类型表只负责为已知 `kind` 绑定 `unit_type`、`phase` 和 `role`。规范化层只做
边界校验与有界序列化，不再将缺失字段推断为 legacy、unknown 或兼容 unit。

事件类型和状态采用以下职责划分：

| 事件事实 | 权威字段 | 用户状态 |
| --- | --- | --- |
| 工具调用 | `tool_call` | 运行中 |
| 工具执行结果 | `tool_result.status` | 已完成 / 失败 |
| 审核开始 | `review_started.state` | 审核中 |
| 审核终态 | `review_completed.state` 或 `review_failed.state` | 审核已通过 / 审核未通过 |
| 生成发布 | `generated_chart_published.publication_status` | 已发布 |
| 运行中断 | `run_interrupted` | 已中断 |

`state` 表示业务 unit 的状态，`status` 表示工具执行结果；二者不再被前端
互相猜测或覆盖。缺少权威字段的事件在生产边界失败，并留下明确的协议错误。

备选方案是让前端根据 `kind`、`phase` 和 `role` 兜底推断，已排除：它只能修复
部分历史数据，不能保证普通运行、评测读取和实时事件拥有同一语义。

### 2. 让 ReviewCoordinator 成为唯一审核生命周期拥有者

生成图进入审核时，由审核协调器创建唯一的 review identity，并负责发出：

```text
review_started
  → review_repair_required / review_failed / review_completed
  → generated_chart_published（仅通过且允许发布时）
```

确定性检查和 VLM 检查结果作为同一 review record 的诊断详情保存，
`review_subcheck` 只进入技术 trace 和评测详情，不再创建用户时间线节点。
工具返回的 candidate metadata 中如果包含另一个内部 review id，只能作为嵌套
诊断字段，不能成为第二个时间线 review identity。

`chart_review_started` 和 `chart_review_completed` 是历史兼容别名，直接删除其
生产、传输、读取、展示和测试路径。备选方案是继续发出别名并由前端隐藏，已排除：
它保留了重复状态源，未来仍会产生顺序和状态分歧。

### 3. 前端只保留一个 TimelineNode 归约模型

前端用一个节点模型表示用户时间线。节点以 canonical `unit_id` 为主键，保存
该 unit 的所有事件，并将 `tool_call`、`tool_result`、visual observation、
审核 transition 和 artifact reference 作为同一节点的不同事实。`call_id` 只
用于校验调用/结果配对，不再通过工具名、序号或最近一次未完成调用进行猜测。

节点归约按事件序列执行，状态只能由权威事件向前推进：

```text
tool_call → running
tool_result.success → completed
tool_result.error → failed
review_started → reviewing
review_completed.passed → passed
review_failed → failed
generated_chart_published → published
run_interrupted → interrupted
```

这样可以删除独立的 `ToolStep` 用户状态和 `DecisionUnit` 用户状态两条路径，
保留一个节点供普通运行和评测工作台复用。技术详情直接读取节点保存的原始
事件集合，不需要再从第二套时间线重新拼装。

备选方案是只修补现有 `unitStatus()`，继续同时维护两个投影，已排除：它能修复
当前渲染状态未知，但无法消除“完成/已完成”分裂和重复审核的结构性问题。

### 4. 用户文案和技术字段彻底分层

建立唯一的生命周期标签目录，节点标题、阶段和状态都从该目录产生。用户视图
不接受 `kind` 作为 fallback，也不展示“业务步骤”这种无法表达语义的通用副标题。
原始 `kind`、transition、review id、call id 和完整 payload 只在“技术详情”中
展示并保持机器可读。

最终用户视图只保留类似以下内容：

```text
生成图表    已完成
审核        审核已通过
生成结果    已发布
```

审核中的节点显示“审核中”，中断显示“已中断”，历史缺口显示“历史记录不完整”；
`unknown` 不再是用户状态。

### 5. 以新契约重写测试，不保留兼容测试

Python 测试覆盖事件工厂、审核唯一 identity、别名不再产生、缺失字段被拒绝、
工具结果状态归约和 publication gate。前端 timeline smoke 使用真实运行中出现
的显式 `unit_id` 事件夹具，断言生成图不会停留在未知、审核只出现一个节点、
主界面没有英文 kind 和重复审核卡片。

移除验证 `legacy_envelope`、`legacyUnitId`、`compatibilityBucket`、
`chart_review_*` 和工具名回溯匹配的测试；旧评测 bundle 不作为新的回归样本。

## Risks / Trade-offs

- **旧运行记录无法显示** → 在实现前清理本地 `.chartagent` 运行记录和旧评测夹具；Gateway 对旧协议只返回明确的版本/协议错误，不进行隐式转换。
- **事件生产者遗漏字段导致运行失败** → 先实现事件契约校验，再逐一覆盖工具、审核、发布和 Gateway 事件生产路径；缺失字段用专门的协议测试锁定。
- **审核内部结果丢失可见性** → 保留 subcheck、VLM 结果和问题在技术 trace/评测详情中，只删除其作为用户业务步骤的重复投影。
- **实时事件与历史重放出现顺序差异** → 继续使用单调 sequence 和 transition 去重，并让实时与历史都经过同一个 TimelineNode reducer。
- **集合候选或修复重试错误合并** → candidate attempt、parent attempt、collection parent 和 review identity 纳入节点主键/父子关系测试，禁止用标题或工具名关联。
