## Why

评测工作台已经能够展示批次状态、阶段时间线、失败原因和视觉证据，但当前“只读运行记录”停留在事件摘要层，用户无法展开查看模型可见对话、工具调用参数和工具返回结果。这使得评测过程虽然可见，却不能完成细节复盘和问题定位；现在需要在现有工作台基础上补齐可展开的运行详情，同时保持评测数据只读、隔离和安全脱敏边界。

## What Changes

- 保留现有独立评测工作区、批次列表、case 详情、阶段时间线和证据画廊，不新增一套独立的 transcript 工作区。
- 扩展评测 case 的只读运行记录，使用户可以查看用户输入、模型可见回复、工具名称、调用参数、工具结果、测量修复信息及其 `call_id`/事件序号关联。
- 在现有运行时间线上增加工具调用和工具结果的展开详情，详情按需读取，避免列表初始响应被原始过程数据撑大。
- 从评测 bundle 中已有的 `records` 与 `gateway_run_events` 组合生成安全的详细记录投影；缺少某一类记录时保留另一类可用的过程信息。
- 对详细对话和工具结果继续执行字段脱敏、文本/事件/响应大小限制、资源引用映射和明确的持久化截断标记。
- 详细记录仍不得暴露隐藏 reasoning、凭据、绝对本地路径、原始 SQLite、未受控 provider payload 或图片二进制；视觉内容继续通过 evaluation-scoped resource reference 预览。
- 保持普通 session API、评测 bundle 布局、评测数据库隔离和现有评测工作区状态管理兼容。

## Capabilities

### New Capabilities

- `evaluation-workbench`: 为 Figura 桌面端提供独立的评测批次浏览、case 诊断、可展开运行记录、报告和安全视觉证据查看能力。

### Modified Capabilities

无。此次调整仍属于 `evaluation-workbench` change 的范围扩展，不修改普通会话或其他能力的行为契约。

## Impact

- Python Gateway：扩展评测读取层和只读 history/detail 投影，读取已有 `records` 与 `gateway_run_events`，并继续执行归属校验、脱敏、大小限制和资源引用映射。
- React 前端：扩展评测 history 类型、按需读取接口和现有“只读运行记录”视图，增加对话、工具参数和工具结果的折叠详情。
- 评测存储：不迁移或复制现有 bundle；优先复用当前已保存的数据，无法恢复的历史截断内容必须显式标记。
- 测试与文档：增加详细记录投影、工具结果安全展示、截断和当前 `bar_line_dashboard` bundle 的回归覆盖。
