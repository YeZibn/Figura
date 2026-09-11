## Why

Figura 当前桌面客户端仍以 ChartAgent 作为主要产品名称，视觉层次也停留在基础工作台阶段。随着 React + Tauri 客户端成为主要交互入口，需要统一产品身份并提升会话、对话、附件和运行状态的可读性，让真实 Gateway 和离线模式都呈现一致、成熟的 Figura 工作台体验。

## What Changes

- 将用户可见的产品名称统一为 `Figura`，并将助手、桌面窗口和 Gateway 的展示名称统一到 Figura 品牌。
- 保留 `chartagent` Python 模块、现有环境变量、协议字段和数据目录作为内部兼容标识，避免本次变更造成技术层面的破坏性重命名。
- 重构 React 桌面工作区的视觉层级、色彩、间距、排版、状态反馈和响应式布局。
- 优化会话导航、当前会话标题、对话消息、工具执行详情、视觉观察、附件面板和输入区域的呈现。
- 为会话项提供清晰的操作区布局，为后续删除会话能力预留入口位置；本次不实现删除接口或删除行为。
- 确保 mock 模式、Gateway 模式和 Tauri 窗口中的用户可见文案保持简体中文，并使用 Figura 品牌名称。
- 更新相关 README、OpenSpec 文档、Tauri 配置和测试断言中的产品展示名称。

## Current Scope Boundary

本变更后续只继续推进 React/Vite 浏览器前端及其 Gateway 连接验证。已经完成的 Tauri 品牌配置保留，但暂不继续实现或验证 Tauri、Rust、Cargo 和 Xcode 相关内容；Tauri 实机工作后续单独安排。

## Capabilities

### New Capabilities

- `figura-branding`: 规定 Figura 的用户可见产品身份、各运行界面的展示名称，以及与现有 `chartagent` 内部兼容标识之间的边界。

### Modified Capabilities

- `desktop-client`: 增加 Figura 桌面工作区的视觉一致性、信息层级、状态反馈和响应式交互要求。

## Impact

- React 客户端：`frontend/src/App.tsx`、`frontend/src/styles/global.css`、前端类型和 mock 展示数据。
- Tauri 客户端：`src-tauri/tauri.conf.json` 及必要的窗口展示配置。
- Python Gateway：仅调整对外展示名称和文档语义，不改变 `chartagent` 模块路径或协议兼容字段。
- 文档与测试：README、OpenSpec 主规格和现有前端/Python/Tauri 断言中的展示名称。
- 不涉及会话删除后端接口、SQLite 数据迁移、Python 包重命名、环境变量迁移或数据目录迁移。
