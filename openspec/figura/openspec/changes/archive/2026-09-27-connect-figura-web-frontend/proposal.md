## Why

Figura 的 Run、Session memory、Provider 和图片附件能力目前只有 Python 内部调用入口，现有 React 网页仍连接 ChartAgent 或 mock，用户无法通过网页实际运行 Figura。需要增加本地 Web 接入层，并复用现有工作区界面，让已实现的 Figura 能力形成可操作的端到端流程。

## What Changes

- 增加仅监听 loopback 的 Figura HTTP/SSE Gateway，组合现有 RunStore、RunCoordinator、AgentExecutor、Provider 和 AttachmentService。
- 暴露会话创建与列表、会话读取投影、图片上传与内容读取、Run 创建与状态事件，以及 Provider 配置状态接口。
- Run 请求通过现有固定 Provider/模型允许列表执行：Qwen `qwen3.8-flash`、DeepSeek `deepseek-flash`、MiMo `mimo-v2.6-flash`；HTTP 请求使用幂等键，运行状态和事件沿用现有持久化记录。
- 增加 React Figura 客户端和网页运行模式，复用会话侧栏、对话区、附件面板及运行生命周期控制；隐藏 Figura 尚无接口支持的评估、图表预览和重试/恢复操作。
- 增加 `npm run dev:figura`，启动本地 Figura Gateway 与 Vite 网页；Gateway 从项目 `.env` 读取 Figura 配置，数据默认写入 Git 忽略的 `.figura/`。
- 公共会话消息由现有 Run 持久化事实只读投影，不增加消息表，不公开工具原始参数、Continuation、密钥或本地路径。

## Capabilities

### New Capabilities
- `figura-web-gateway`: 本地浏览器使用的 Figura HTTP/SSE API、异步 Run 派发、会话与附件访问、Provider 状态及安全投影。
- `figura-web-client`: 现有 React 工作区中的 Figura 网页模式、Provider 选择、会话/附件/Run 交互与开发启动流程。

### Modified Capabilities

无。现有 Agent、Memory、Provider、附件及持久化行为不改变；新能力通过边界明确的 Web 接口调用它们。

## Impact

- Python：新增 `src/figura/gateway/` 及必要的 Store/Coordinator 只读查询入口；不修改 ChartAgent Gateway。
- Frontend：扩展 `frontend/src/App.tsx` 的模式选择与 API 适配，新增 Figura 客户端和 Gateway/SSE 映射，复用现有工作区组件。
- Dev/runtime：扩展 `frontend/package.json` 与 `frontend/scripts/`；读取项目 `.env` 时保留 Shell 环境变量优先级，Provider 密钥只进入 Python 进程；Gateway 绑定 `127.0.0.1`，只允许配置的本地网页 Origin。
- Persistence：继续使用 Figura 当前 SQLite Run、Session、Attachment 和 Run event 记录；补充读取能力，不引入消息表或改变现有记录格式。
- Compatibility：保留 `ChartAgentClient`、`gatewayClient.ts`、`types/protocol.ts` 及既有 `dev` / `dev:gateway` 行为。
