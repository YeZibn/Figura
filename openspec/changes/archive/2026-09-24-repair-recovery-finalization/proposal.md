## Why

恢复链路仍有边界缺陷：子 Run 继续恢复时可能因游标比较错误被拒绝；已提交的最终回答在进程中断后可能重新调用模型；历史失败验证可能误伤后续成功尝试。工具批次还可能丢失后续调用产生的 artifact 引用，使下一轮模型上下文不完整。

## What Changes

- 按每个 Run 的本地游标校验其执行记录，并分别验证父级游标与有界 lineage，使 `resume → child → resume` 可从完整已提交前缀恢复。
- 将已提交最终回答作为恢复的最终动作；显式 resume 复用该答案并幂等完成子 Run，不再次请求模型。
- 将最终回答中的验证和发布判断限定到该回答涉及的 artifact/attempt，避免历史失败验证否定后续成功结果。
- 修复工具批次中 artifact 记录列表截断导致的别名丢失，确保同一批后续调用的记录继续进入下一轮模型上下文。
- 增加对应的恢复、崩溃窗口、历史 attempt 隔离和多工具批次回归覆盖。
- 不引入兼容层、旧格式 fallback、重复状态字段或双写迁移路径；直接按当前执行记录、游标和 Run 契约修正生产路径。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `run-checkpoint-recovery`: 校验父子执行记录 lineage，支持从子 Run 的游标继续恢复。
- `durable-execution-record`: 最终回答提交后恢复为最终动作并复用已提交答案。
- `run-lifecycle-reliability`: 崩溃恢复后的最终答案发布与终态收敛保持幂等，不重复启动模型执行。
- `generated-chart-verification`: 最终回答保护按其引用的 artifact/attempt 判断，不受无关历史失败影响。
- `agent-loop`: 有序工具批次中已产生的 artifact 记录保留至后续调用和模型上下文。

## Impact

- 影响 Gateway 执行记录前缀和恢复游标校验、Agent 最终回答提交/恢复、最终回答验证保护，以及 `ToolExecutionFlow` 的 artifact 记录管理。
- 更新上述 5 项主规格和针对 lineage、finalization、attempt 归属及批次 artifact 保留的测试。
- 不改变对外 Run/SSE 字段、状态枚举或现有 resume 子 Run 身份约定。
