## 1. 建立重构基线与边界

- [x] 1.1 运行并记录当前 `npm run build`、`npm run smoke` 和 `git diff --check` 结果，建立普通会话、评测、预览、重连和恢复的能力清单。
- [x] 1.2 使用 `rg` 梳理 `App.tsx`、`gatewayClient.ts`、`protocol.ts`、mock client 和样式文件的公开导出与调用方，标记必须保留的兼容入口。
- [x] 1.3 创建前端目标目录与依赖方向约定，确保类型模块不依赖 React，纯逻辑不依赖组件，组件不直接访问 Gateway transport。

## 2. 提取协议类型与纯逻辑

- [x] 2.1 将会话、运行/恢复、评测、预览和 Provider/健康状态类型拆到按领域组织的模块，并保留 `types/protocol.ts` 的 barrel export。
- [x] 2.2 提取状态标签、时间格式化、资源展示、错误到中文提示的纯函数，保持现有文案和错误码映射。
- [x] 2.3 提取运行时间线模型、事件合并去重、工具调用/结果关联和生成产物归一化逻辑，保持 `runId:sequence` 语义。
- [x] 2.4 提取测量修复、审核 gate、完整性状态和评测详情的安全展示 view model，确保缺失字段可以安全降级。
- [x] 2.5 删除 `App.tsx` 中已迁移且确认无其它引用的纯逻辑，运行 TypeScript 构建确认类型边界稳定。

## 3. 拆分 Gateway adapter 与 Mock 实现

- [x] 3.1 抽取 Gateway 请求 transport、URL 配置和 `GatewayClientError` 处理，保留现有请求超时/错误语义。
- [x] 3.2 抽取会话、运行/SSE、评测 API 的 payload mapper，保持字段映射、资源引用和完整性字段不变。
- [x] 3.3 将 Gateway client 的会话、运行、评测读取和订阅实现拆分到职责清晰的内部模块，并保留当前 `gatewayClient` façade。
- [x] 3.4 将 mock fixtures 与 mock client 行为分离，保留运行重连、测量修复、评测和预览所需的代表性样例。
- [x] 3.5 用 `rg` 和 `npm run build` 清理确认无调用的重复 mapper、旧路径和空壳实现，不删除仍被外部入口使用的兼容导出。

## 4. 统一运行生命周期控制器

- [x] 4.1 提取运行控制器或 hook，统一 start/resume、SSE 订阅、sequence 游标和事件归并状态。
- [x] 4.2 让新运行和页面恢复中的运行共用历史补偿、history gap 标记、有界退避重连和清理逻辑。
- [x] 4.3 保持中断、重试、继续执行、幂等 key、父子 run lineage 和 recovery 状态的现有行为。
- [x] 4.4 增加或复用 mock 回放检查，覆盖重复事件、历史先到、实时先到、重连耗尽、终态事件和组件卸载清理。
- [x] 4.5 从 `App.tsx` 删除重复的订阅/重连闭包，确认每次运行只存在一个活动订阅和一个终态收敛路径。

## 5. 拆分工作区与展示组件

- [x] 5.1 提取工作区 shell、SessionSidebar、创建/删除对话框和工作区切换逻辑，保留会话与评测入口行为。
- [x] 5.2 提取 ConversationPanel、Message、AttachmentPanel 和附件预览，保持附件选择、上传、删除、重试和活动源展示。
- [x] 5.3 提取 RunBlock、RunTimeline、工具步骤、视觉观察、审核时间线和生成图展示组件，接入统一时间线 view model。
- [x] 5.4 提取 EvaluationPanel、评测 case 导航、历史记录、详情资源和完整性提示组件，保持评测只读边界。
- [x] 5.5 提取 InteractivePreview、PreviewImage 和预览资源状态展示，保持放大、缩小、适应窗口、键盘关闭和 object URL 清理。
- [x] 5.6 将 `App.tsx` 收敛为工作区组合、跨域选择和少量全局状态，不再直接实现 API 请求、事件归一化或长 JSX 细节。

## 6. 整理样式、Mock 与前端契约检查

- [x] 6.1 将 `global.css` 按 tokens/layout、conversation/run、evaluation、attachment/preview 和 dialogs 拆分，并通过稳定入口保持导入顺序。
- [x] 6.2 保持现有 class 语义、选择器优先级和响应式断点，检查宽窗口、窄窗口、评测工作区和预览层布局没有视觉回归。
- [x] 6.3 更新前端 smoke，使其按模块能力、稳定 façade、事件契约和启动脚本检查，不再假设所有实现字符串位于 `App.tsx`。
- [x] 6.4 保持 mock 与 Gateway 两种模式均能启动，更新必要的 mock 展示数据和 smoke 断言以覆盖拆分后的入口。

## 7. 清理与交付验证

- [x] 7.1 使用 `rg`、TypeScript 构建和依赖图复核无引用的旧实现、重复导出和过渡文件，逐项删除并保留必要兼容 façade。
- [x] 7.2 运行 `npm run build`、`npm run smoke` 和前端相关启动器检查，覆盖会话、运行、评测、附件、预览和 provider 选择。
- [x] 7.3 运行受影响的 Gateway/Python 回归与事件回放检查，确认前端重构未改变 HTTP、SSE、运行记录和评测资源契约。
- [x] 7.4 运行 `git diff --check`，复核用户可见中文、敏感信息脱敏、错误降级和未知事件 fallback。
