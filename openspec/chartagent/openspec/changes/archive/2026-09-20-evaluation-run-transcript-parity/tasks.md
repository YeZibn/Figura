## 1. 统一运行记录契约

- [x] 1.1 以普通会话 `RunHistory` 和 `RunTimeline` 的现有行为建立评测 transcript 对照基线，列出事件字段、工具关联、视觉观察和生命周期状态。
- [x] 1.2 定义评测与普通会话兼容的安全事件 DTO，保留 `sequence`、`timestamp`、`call_id`、状态、资源引用和完整性状态字段。
- [x] 1.3 定义 `persisted_truncated`、`projection_truncated`、`detail_unavailable` 等完整性状态及其中文展示语义。

## 2. 评测 Gateway 事件读取

- [x] 2.1 改造评测 history 读取，使工具调用、工具结果、视觉观察、修复、审核、失败和恢复事件返回与普通会话一致的安全 payload。
- [x] 2.2 将 `gateway_run_events` 设为执行过程的权威来源，使用 `records` 补充用户/模型可见消息，不重复展示同一 `call_id` 的工具结果。
- [x] 2.3 用语义化安全投影替换全局递归深度截断，保留 bbox、polygon、axes、baseline、bars、series、points 等图表结构。
- [x] 2.4 为集合、文本和总响应设置有界限制，并在具体字段返回可解释的截断来源、原因和保留信息。
- [x] 2.5 保持缺失 records、历史缺口、旧事件格式和已持久化截断 bundle 的兼容回退，不伪造缺失数据。

## 3. 大工具结果详情资源

- [x] 3.1 设计评测 bundle 内安全工具结果详情的目录、opaque resource ID、媒体类型、字节数、归属和摘要指纹登记格式。
- [x] 3.2 在新评测运行中对超过普通事件 envelope 的安全结果写入详情资源，并在事件中保留工具身份、call_id、状态和详情引用。
- [x] 3.3 增加按 evaluation/case/run 校验的详情读取路径，拒绝跨 case、路径穿越、未登记、超限和不支持类型的请求。
- [x] 3.4 让旧 bundle 在没有详情资源时继续展示已有事件结果，并明确返回不可恢复的持久化截断状态。

## 4. Gateway 与前端数据接入

- [x] 4.1 让评测 history API 返回可直接映射为普通 `RunHistory` 的数据，并为评测视觉资源补充 evaluation-scoped 引用。
- [x] 4.2 扩展前端协议类型和 Gateway client，支持安全事件、完整性状态及大结果详情的按需读取。
- [x] 4.3 保留评测批次、case、报告和证据接口的只读边界，确认新 transcript 接口不暴露 SQLite、本地路径或原始 provider payload。

## 5. 前端运行时间线一致化

- [x] 5.1 抽取普通会话的工具步骤归并、事件标签、工具调用/结果展开和视觉观察挂载逻辑为可复用只读组件。
- [x] 5.2 将评测 case 的运行过程切换为共享时间线，按 call_id 合并工具调用、工具结果和观察，并保持原始 event sequence 顺序。
- [x] 5.3 在评测时间线中展示用户/模型消息、测量修复、审核、失败、恢复和终态事件，保持与普通会话一致的中文标签和状态语义。
- [x] 5.4 移除评测主链路对“只显示摘要”的工具结果占位逻辑；旧 detail 接口仅作为兼容或补充上下文来源。
- [x] 5.5 增加完整性状态、历史缺口、详情资源不可用和只读限制的明确提示，并提供可滚动、展开和复制结构化 JSON 的查看方式。
- [x] 5.6 确认评测页面不会出现同一工具结果的完整事件、截断 records 和摘要详情三份重复表示。

## 6. 后端回归验证

- [x] 6.1 添加深层图表结构投影测试，验证 bbox、polygon、坐标轴、柱体、系列和点坐标的数值不会因递归深度被替换。
- [x] 6.2 添加敏感字段、data URL、未知嵌套对象、集合超限、文本超限和总响应超限测试，确认安全边界仍然有效。
- [x] 6.3 使用当前 `bar_line_dashboard` bundle 验证拆分、柱状图测量和折线提取结果在 API 中保留完整结构。
- [x] 6.4 添加缺失 records、历史已截断、detail resource 缺失和资源读取失败的兼容测试。
- [x] 6.5 添加大结果详情资源的创建、读取、归属校验、路径穿越、跨 case、媒体类型和大小限制测试。

## 7. 前端与交付验证

- [x] 7.1 增加评测 transcript 的工具调用/结果分组、视觉观察、错误事件、完整性提示和只读模式 smoke 覆盖。
- [x] 7.2 验证普通会话的 RunTimeline、工具结果展示、重试、继续执行和中断行为没有回归。
- [x] 7.3 更新评测运行文档，说明安全完整展示、历史不可恢复截断和大结果详情资源行为。
- [x] 7.4 运行 `conda run -n agent python -m pytest -q`、`npm run build`、`npm run smoke`、`git diff --check` 和 `openspec validate evaluation-run-transcript-parity --type change --strict`。
