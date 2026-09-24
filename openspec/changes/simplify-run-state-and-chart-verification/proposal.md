## Why

Figura 已有稳定的四态 Run 合约，但恢复、生成图审核和前端展示同时维护 checkpoint 快照、通用 operation、candidate/review/publication 状态及 execution gate。项目进入收束阶段，需要把恢复落实为持久步骤和安全边界，并删除这些重复状态及其长期兼容代码。

## What Changes

- 为 Gateway Run 建立唯一的私有执行记录：模型响应、工具结果、验证结果和发布结果按提交顺序保存；小型 checkpoint 只记录已提交游标、下一动作及必要的安全引用。步骤结果和下一动作在同一 SQLite 事务中提交。
- 明确定义 `MODEL`、`TOOL`、`VERIFY`、`PROMOTE`、`FINAL` 五种恢复动作及各类调用的重放契约。已提交结果复用；显式 resume 可以重新请求未提交的模型/VLM 结果，可能产生额外费用；仅结果不明的外部副作用阻止自动重放。
- 将生成图改为持久暂存图像和精确 ChartSpec/来源绑定、自动确定性及适用的 VLM 验证、保存一份不可变验证结论、幂等发布。Agent 决定失败后的下一步，代码强制阻止未验证发布及虚假的成功终结。
- **BREAKING** 删除 Candidate/Review/Publication 三套状态、ExecutionGate/repair phase、完整 review/measurement checkpoint 快照、通用 Operation Journal、旧回调链及相应的 API、SSE、前端和提示词字段。保留失败图预览、问题诊断、集合子图归属、Run 子代关系和 `runId:sequence` 事件身份。
- **BREAKING** 新版切换时清空旧会话数据库、应用托管附件和运行产物，包括已发布图表；不迁移旧会话、历史和 checkpoint，不保留旧格式读取分支。删除前以实际配置解析并核对目标路径，仅处理 Figura 托管数据，不删除外部源图片或无关诊断/评测材料。

## Capabilities

### New Capabilities

- `durable-execution-record`: 提交步骤事实、私有模型上下文、原子游标及安全重放的统一执行记录。
- `generated-chart-verification`: 暂存图表、自动验证、结构化诊断、幂等发布与最终结果保护的唯一契约。

### Modified Capabilities

- `run-checkpoint-recovery`: 由完整状态快照和通用 operation 状态改为游标、下一动作、引用及明确的重放规则。
- `run-lifecycle-reliability`: 保留四态和子 Run，更新未提交模型/VLM 请求的显式恢复语义。
- `agent-session-memory`: 将普通会话记忆与受限的私有恢复记录分开，旧数据切换后从新空库开始。
- `agent-loop`: 由旧 review gate 和 publicationStatus 驱动改为验证事实、工具结果和最终回答保护。
- `chart-generation`: 由 candidate/review/publication 状态字段改为暂存、验证和发布事实。
- `scope-aware-generation-review`: 保留不可变任务范围，但让修复提示成为诊断而非代码控制的 repair phase。
- `review-gates`: 移除旧的共享审核状态机要求；仍有效的发布约束迁入 `generated-chart-verification`。
- `vlm-chart-review`: 移除候选审核生命周期要求；仍有效的 VLM 内容、安全和有界调用要求迁入 `generated-chart-verification`。
- `python-gateway`: 更新恢复、生成图暂存/发布资源和运行摘要契约，删除 gate/candidate 回调及旧字段。
- `execution-trace`: 将旧 review/publication/repair 生命周期事件收敛为可投影的验证与发布事实。
- `unified-decision-review-timeline`: 保留关联、去重和集合子图展示，删除旧 gate/候选状态投影。
- `desktop-client`: 使用新恢复与验证/发布投影呈现运行、错误、预览和集合结果。
- `interactive-preview`: 以暂存图及正式 artifact 引用表达预览和下载可用性。
- `measurement-quality-gate`: 测量 attempt/evidence 仍有范围归属，但当前结果由提交记录恢复，不复制完整 session 到 checkpoint。

## Impact

- 影响 Agent/Runtime、Memory、Gateway SQLite 与产物存储、生成图验证、前端 Gateway/mock 协议、时间线/预览、提示词、评测投影，以及上述主规格和相关测试。
- 保留 Gateway 的 loopback、授权、脱敏、限额、Run 幂等与 SSE 重连边界；不增加外部依赖或新的对外 Run 状态。
- 实施可分多个小提交，但本 change 只有在新链路验收、旧状态代码及旧数据均退出后才算完成。
