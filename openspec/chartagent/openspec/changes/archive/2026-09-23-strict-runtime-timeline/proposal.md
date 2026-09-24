## Why

当前运行时间线同时维护原始事件、decision unit、ToolStep 和兼容投影。审核事件还存在 `review_*` 与 `chart_review_*` 两套来源，部分事件显式带有 `unit_id` 却被标记为 `unknown`，最终造成英文事件名、错误的“已完成”状态、重复审核记录和渲染结果状态未知。现在需要一次性收敛运行时协议和前端投影，避免继续叠加兼容分支。

## What Changes

- **BREAKING** 建立严格的运行时间线事件契约：所有可投影事件由生产端写入完整的 `unit_id`、`unit_type`、`phase`、`role`、`state/status` 和 `transition_id`；前端不再根据缺失字段猜测关联。
- **BREAKING** 删除 `legacy`、`unknown`、按工具名/序号回溯匹配以及旧事件兼容封装；无法满足新契约的事件在协议校验阶段失败，不进入用户业务时间线。
- **BREAKING** 统一审核事件来源，只保留一套 canonical `review_*` 生命周期；删除 `chart_review_*` 兼容别名，并让同一 candidate attempt 始终使用一个 review identity。
- 统一工具调用、工具结果、生成、审核和发布的状态归约，消除“完成”“已完成”“状态未知”来自不同投影模型的问题。
- 删除前端重复的 ToolStep/DecisionUnit 用户状态投影，保留一个时间线节点模型；技术事件和原始英文 `kind` 只在技术详情中展示。
- 统一简体中文用户文案，主界面只展示运行中、审核中、已完成、审核已通过、已发布、失败和已中断等确定状态。
- 重写时间线、审核事件、Gateway 历史和评测夹具测试；不保留旧事件格式的兼容测试或运行时兜底。

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `execution-trace`: 将运行事件从可兼容的松散投影改为严格、完整、单一的事件契约，并统一工具/审核/发布状态。
- `unified-decision-review-timeline`: 删除 legacy/unknown 容器和多重投影，改为一个严格的用户时间线节点与状态归约模型。
- `review-gates`: 让审核生产端只发布一个 canonical review cycle，移除 `chart_review_*` 兼容事件和重复 review identity。

## Impact

- Python 运行时事件生产、事件规范化、审核协调和 Gateway 历史事件协议。
- React 时间线投影、工具结果展示、审核展示、评测只读历史和中文标签。
- 相关 OpenSpec 主规格、测试夹具、timeline smoke、审核测试和评测诊断测试。
- 这是一次有意的协议破坏性重构；已有旧格式运行记录和旧测试夹具需要清理或重新生成，不提供运行时兼容读取路径。
