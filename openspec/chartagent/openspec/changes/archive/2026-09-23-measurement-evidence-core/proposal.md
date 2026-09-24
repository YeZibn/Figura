## Why

测量结果目前同时承载候选证据和 selected/discarded decision 生命周期，装配器、恢复状态、事件时间线与前端也保留了对应状态及兼容入口，导致一次测量被拆成多套互相重复的状态。将测量统一为带来源、范围、质量和系列信息的候选证据，让主 Agent 通过实际工具调用和 `assemble_spec` 引用表达判断，可以去掉多余门禁并让局部重测成为模型按需调用的普通测量。

## What Changes

- **BREAKING** 移除 measurement 核心模型、持久化状态和装配输入中的 `measurement_decision`、`selected_refs`、`discarded_refs`、`decision_status` 及其旧兼容别名；旧运行无需继续通过这些字段恢复。
- 将测量 session 收敛为来源范围内当前 attempt 的结果与 lineage，保留 `measurement_ref`、`evidence_refs`、scope、quality metadata、series metadata；实际下游引用从 `assemble_spec` 请求派生，不再维护另一套选中/舍弃状态。
- 让模型在主链路中自主决定是否引用候选证据，以及是否通过已有测量工具发起带 scope/target 的局部重测；工具和恢复流程不自动重测，也不因缺少 decision 阻塞合法组装。
- 移除独立的 pending measurement repair 队列和重复的修复状态；恢复从 measurement session 与当前 attempt 重建必要上下文。
- 精简测量 trace 与前端呈现：只呈现测量开始、完成、失败及必要工具结果，不再产生或展示测量决策待处理、证据选取/舍弃、局部修复耗尽等独立业务步骤。
- 清理 Agent prompt、工具描述、ChartSpec 组装 schema、持久化投影及测试中的旧决策协议，确保一条新生命周期贯穿端到端。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `measurement-quality-gate`: 测量结果只表达候选证据及质量/来源；会话与 attempt 不再保存选取/舍弃决策，局部重测由主 Agent 显式调用。
- `agent-loop`: 模型直接消费测量结果并以实际 assembly refs 表达使用；移除 pending repair 和独立 decision 生命周期，不因其缺失阻塞主流程。
- `chartspec`: assembly 只接收并校验实际使用的 measurement/evidence refs、来源范围和图表意图，不接受或推导 decision 状态。
- `run-checkpoint-recovery`: checkpoint 只持久化并恢复 measurement session/current attempt 所需事实，不保存独立测量审核门禁或重复 repair 队列。
- `tool-system`: 测量工具输出候选证据和元数据；装配工具 schema 与描述删除 selected/discarded/decision 输入及兼容路径。
- `execution-trace`: 新运行不再发出 measurement decision、选择/舍弃、待决或自动 repair 生命周期事件；保留必要的测量工具执行与结果关联。
- `desktop-client`: 时间线仅将测量显示为工具观察及其结果，不显示测量决策卡、选择/舍弃状态或待处理门禁。
- `unified-decision-review-timeline`: measurement 的 timeline projection 以实际工具观察和下游引用为依据，不再为候选使用与否创建独立可见或持久决策单元。
- `layered-prompt-assembly`: 过程产物和动态上下文只提供候选测量事实；prompt 指导模型通过引用或再次调用测量工具表达选择，不保留 selected/discarded 生命周期或两阶段 focus。
- `evaluation-workbench`: 评测详情复用新的工具调用/结果与 assembly 引用，不再要求 discarded evidence decision 或 pending measurement unit。
- `review-gates`: 测量 warning 下主 Agent 继续自主选择下一工具动作或装配，不需要提交独立 evidence decision；生成图发布门禁保持不变。

## Impact

- Python：`measurement/lifecycle.py`、`tools/chart/specification.py`、`agent/measurement_flow.py`、`agent/loop.py`、`agent/recovery.py`，以及 measurement session、artifact、checkpoint、trace/evaluation projection 和 prompting 相关模块。
- Frontend 与 evaluation：事件归一化、measurement timeline/domain/types 和评测详情；删除旧 decision event 的业务投影与文案。
- OpenSpec：更新以上现有能力的 delta specs；相应更新测试，使新运行从工具调用、assembly、checkpoint 到历史展示均不依赖旧字段。
- 不增加模型调用或新工具；沿用现有 scope-aware 测量工具。质量、scope、引用有效性和 ChartSpec 结构校验仍保留，但不再充当 selected/discarded 决策状态机。
