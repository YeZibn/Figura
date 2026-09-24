## Why

审核与测量的领域状态已经收敛，但事件生产、Gateway、前端和 Evaluation 仍重复表达时间线语义。与此同时，Agent 主循环还承担工具调度、审核协作、恢复和事件记录等多项职责。本 change 将统一事件链路，并在保持运行行为不变的前提下整理主循环和相关冗余，避免领域状态与兼容逻辑继续散落。

## What Changes

- 将 timeline correlation 协议升级，为各事件定义唯一的 canonical 字段和状态语义；移除同义字段及 Gate 镜像事件。
- 统一普通运行与 Evaluation 的用户时间线投影；不支持的历史协议明确显示不可用，不推断状态、不删除历史数据。
- 将 `Agent.run` 收敛为运行协调入口，拆分其余仍混杂的执行职责；优先复用现有 turn、recovery、measurement、panel routing 和 artifact 模块。
- 将生成图表审核流程与主循环解耦，但继续由 `ChartReviewManager` 独占审核状态；不得引入第二套审核或 Gate 状态。
- 在上述范围内清理重复字段、过时事件分支、无调用方包装层和其他经引用扫描确认的冗余代码；迁移其测试和调用方后再删除。
- 保持模型轮次与工具调用顺序、中断、checkpoint/resume、幂等、审核阻塞和发布行为不变。
- 保留 Gateway/client façade、路由、Run 与事件序号身份、checkpoint、产物持久化，以及 Evaluation 的脱敏、截断和资源授权边界。
- 不进行无关的全仓清理，不重新设计审核或测量领域状态，不迁移或删除旧运行数据。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `execution-trace`：统一事件 envelope、字段语义和不支持历史协议的处理方式。
- `unified-decision-review-timeline`：统一普通运行与 Evaluation 的只读时间线投影。
- `desktop-client`：移除旧事件/字段 fallback，明确展示不可用状态。
- `evaluation-workbench`：使用共享时间线投影，并保留只读诊断与安全边界。

主循环改造按行为保持不变的内部重构处理；若实施中发现用户可观察的 Agent 行为契约也要变化，再补充 `agent-loop` delta。

## Impact

- Agent 编排与已有协作模块：`src/chartagent/agent/loop.py`、`turn.py`、`recovery.py`、审核及测量流程。
- 时间线生产与校验：`src/chartagent/decision_timeline.py`、`src/chartagent/trace.py`、Gateway lifecycle。
- 前端运行和评测时间线、Evaluation 诊断及相关测试。
- 回归验证涵盖工具顺序、恢复、中断、审核/发布、事件重放、UI 一致性和冗余引用清理。
