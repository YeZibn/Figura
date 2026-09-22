## Why

当前链路已经具备 generation context、局部测量、证据选择、ChartSpec 装配、生成候选审核和发布门禁，但这些动作在执行追踪中缺少统一的决策单元与父子关系。test4 中因此出现局部范围已应用却看不出后续测量、证据舍弃在后面突然出现、同一生成候选被展示为多次审核等问题。

现在需要在保留原始事件和模型自主决策的前提下，建立一个可重建的统一决策时间线，让普通运行和评测运行使用同一套关联、状态转换和展示语义。

## What Changes

- 新增统一的 decision unit/timeline 投影，将观察、Agent 决策、工具动作、装配、审核门禁和发布状态关联到同一条候选链路。
- 为测量 focus、measurement observation、evidence selected/discarded 和 assemble 建立明确的 attempt、父动作和下一步关系，禁止把“范围已应用”误显示为“测量已完成”。
- 将 deterministic quality audit 与 tool-free VLM semantic review 归入同一个 candidate review cycle；同一 candidate attempt 只产生一个可见审核周期，collection 子图按父级聚合展示。
- 保留原始 execution events 作为唯一事实来源，由普通会话和评测工作台共享同一个 timeline projector，避免另存一份容易漂移的 timeline 数据。
- 向主 Agent 注入有界的当前决策上下文，明确当前阶段、允许动作、阻塞动作和是否需要显式放弃，不替模型选择证据或语义角色。
- 将事件去重、幂等和 review phase 约束纳入后端状态转换，避免 shared review、VLM review 和 tool result 快照重复制造审核事件。

## Capabilities

### New Capabilities

- `unified-decision-review-timeline`: 定义跨测量、装配、生成、审核和发布的决策单元、关联字段、状态转换和共享时间线投影。

### Modified Capabilities

- `execution-trace`: 增加决策单元、阶段、父子关系、下一步和去重语义。
- `measurement-quality-gate`: 约束局部范围应用、实际观察、证据决策和装配之间的闭合关系。
- `review-gates`: 将审核过程统一为 candidate review cycle，并限制合法的修复和重试转换。
- `vlm-chart-review`: 区分 deterministic audit 与 semantic VLM review，保证每个候选 attempt 的审核语义唯一。
- `layered-prompt-assembly`: 注入紧凑的当前决策上下文和允许动作。
- `desktop-client`: 将普通运行中的决策单元聚合为可展开的统一时间线。
- `evaluation-workbench`: 复用普通运行的时间线投影，完整展示评测 case 的测量、审核和发布过程。

## Impact

- 主要影响 `src/chartagent/agent/loop.py`、执行事件协议与持久化、测量生命周期、review coordinator/manager，以及 `frontend/src/domain/run`、测量和审核时间线组件。
- 需要增加后端事件关联、review cycle 幂等、collection 子图聚合和前端投影的回归测试。
- 保持已有 `generation_context`、ChartSpec、工具参数和原始事件兼容；不新增测量工具，不替换 OCR/SAM/CV，不改变评测目录布局。
- 旧事件缺少新关联字段时继续可读，但只能显示为 legacy/unknown 单元，不得凭空推断其完整决策关系。
