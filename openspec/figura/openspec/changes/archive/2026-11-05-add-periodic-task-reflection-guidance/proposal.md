## Why

复杂任务可以需要很多次有效的观察与修改，但 Agent 也可能在已经偏离目标或沿错误结果继续加工时，长时间不回看整体任务。周期性提示让模型重新对照原始需求、现有证据和下一步价值，帮助它及时调整方向或交付有依据的部分。

## What Changes

- 每累计 20 个当前 Run 中已提交的普通模型响应，在下一次普通模型请求的动态 SYSTEM 状态中加入一次任务回看提醒。
- 提醒指导模型检查需求覆盖、结果依据、近期进展和下一步价值；由模型决定继续、调整方法或交付已有结果。
- 轮数从当前 Run 的已提交执行事实重建；Provider 重试、工具执行和上下文压缩不增加轮数。
- 周期提醒不创建额外审核请求、持久计数器、续期机制或 Run 总配额，也不改变工具权限和已提交结果。

## Capabilities

### New Capabilities

无

### Modified Capabilities

- `agent-react-execution`：增加基于当前 Run 已提交普通模型响应计数、每 20 轮在下一普通请求注入任务回看提醒的行为合同，并明确其不构成强制终止或结果正确性证明。

## Impact

- Agent 请求组装与动态执行状态 Prompt。
- Agent workflow 提示资产。
- Agent ReAct 主规格及其测试。
- 不涉及 Runtime schema、数据库迁移、Provider API 或公开 API。
