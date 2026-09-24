## 1. 评测读取模型与安全边界

- [x] 1.1 新增只读评测 bundle reader，扫描 canonical data root 下的 `evaluations/`，校验 `evaluation_id`、索引 schema 和 bundle 状态，并忽略或安全标记损坏目录。
- [x] 1.2 定义评测列表、评测详情、case 详情、阶段时间线和资源引用的有界 DTO，确保不包含绝对路径、凭据、原始 provider payload 或 SQLite 内容。
- [x] 1.3 实现 evaluation/case/run 归属校验、路径穿越防护、allowlist 文件映射、媒体类型校验和资源大小限制。
- [x] 1.4 适配评测 bundle 中的 `summary.*`、`diagnostics/`、可选 `report.md` 与 `report-assets/`，缺少可选报告时提供标准摘要回退。

## 2. Gateway 只读评测 API

- [x] 2.1 增加 `GET /api/v1/evaluations`，按最近更新时间返回 running、completed、partial、blocked 等批次摘要。
- [x] 2.2 增加评测和 case 详情路由，返回 case 状态、session/run 引用、阶段时间线、首个失败和报告元数据。
- [x] 2.3 增加评测 case 的只读 run history 适配，将事件中的视觉证据映射为 evaluation-scoped resource reference。
- [x] 2.4 增加评测资源读取路由，支持输入图、panel 图、visual observation、generated artifact 和报告图片，并拒绝未登记文件、敏感文件和越界路径。
- [x] 2.5 为评测目录不存在、bundle 尚未就绪、历史不可读、资源缺失和 schema 不兼容定义稳定的有界错误响应。

## 3. 前端评测数据边界

- [x] 3.1 扩展前端协议类型、Gateway client 和 preview resource loader，支持评测列表、详情、case history 及评测图片资源。
- [x] 3.2 增加独立的评测工作区状态，不复用普通 session 的 active session、composer、删除和 run 提交状态。
- [x] 3.3 实现评测列表、状态筛选/展示、评测详情头部和 case 导航，保留 evaluation_id、case_id、run_id 等必要技术引用。
- [x] 3.4 实现阶段时间线、失败原因、修复请求、标准诊断摘要和可选 Markdown 报告展示。
- [x] 3.5 实现输入图、拆分图、局部 panel、测量证据和生成 artifact 的证据画廊，并复用交互式图片预览。
- [x] 3.6 实现空状态、损坏 bundle、资源不可用、Gateway 断开和报告缺失等中文错误/恢复界面。

## 4. 刷新与生命周期

- [x] 4.1 为评测工作区增加显式刷新动作，刷新失败时保留最近一次成功快照并显示 stale/unavailable 状态。
- [x] 4.2 对 running 评测实现有界轮询，进入 completed、partial 或 blocked 后停止轮询，离开工作区或 Gateway 不可用时清理计时器。
- [x] 4.3 验证评测工作区切换不会改变普通 session 的选择、附件、运行订阅和会话列表状态。

## 5. 后端验证

- [x] 5.1 添加有效、空、running、partial、blocked 和损坏 bundle 的 reader/API 测试。
- [x] 5.2 添加评测资源的路径穿越、跨 evaluation/case 访问、敏感文件、超限文件、错误媒体类型和缺失文件测试。
- [x] 5.3 添加评测 history/event/resource 引用映射测试，确认不暴露原始数据库和本地路径。
- [x] 5.4 使用现有 `bar_line_dashboard` 评测结构建立可重复的本地 API 集成验证，确认前端能够读取失败 case 和证据图。

## 6. 前端验证与交付

- [x] 6.1 添加评测列表、详情、case 切换、轮询终态、错误状态和图片预览的前端测试或 smoke 覆盖。
- [x] 6.2 验证普通会话、附件预览、运行时间线和现有 generated chart 展示没有回归。
- [x] 6.3 更新评测运行文档，说明默认 Gateway 如何发现评测 bundle、评测数据只读边界和资源生命周期。
- [x] 6.4 运行 `conda run -n agent python -m pytest -q`、`npm run build`、`npm run smoke` 和 `openspec validate evaluation-workbench --type change --strict`。

## 7. 只读运行记录详情

- [x] 7.1 定义详细运行记录 DTO，分别保留 event sequence、record sequence、时间戳、`call_id`、可见对话、工具调用和工具结果状态。
- [x] 7.2 扩展评测读取层和 Gateway 只读接口，组合已有 `records` 与 `gateway_run_events`，支持按需加载、case/run 归属校验和缺失数据降级。
- [x] 7.3 对工具参数、工具结果、模型可见内容和修复信息执行脱敏、大小限制、结构化投影和持久化截断标记，继续映射视觉资源引用。
- [x] 7.4 改造现有评测“只读运行记录”前端，在时间线中增加对话、工具参数、工具结果和视觉证据的折叠详情，不新增独立 transcript 工作区。
- [x] 7.5 增加详细记录的加载中、空、截断、不可用和敏感字段隐藏状态，并验证普通会话工作区不受影响。
- [x] 7.6 使用当前 `bar_line_dashboard` bundle 和临时 fixture 覆盖对话、工具调用、工具结果、视觉观察、缺失 records、跨 case 访问和敏感内容测试。
- [x] 7.7 更新评测运行文档，运行完整 pytest、前端 build、smoke 和 OpenSpec 严格校验。
