## Why

当前 ChartAgent 主要通过 CLI 交互，session、附件和工具执行过程不便于选择、查看和操作。需要先建立一个本地桌面工作台，让用户可以在可视化界面中理解并验证这些核心交互，再逐步接入真实 Python 后端能力。

## What Changes

- 新增基于 Tauri 2 + React + TypeScript/Vite 的桌面客户端基础工程。
- 提供 session 列表、当前 session 状态和新建 session 的前端交互。
- 提供对话消息区域，支持用户消息、Agent 回答、工具调用、工具结果、视觉观察和错误状态的展示。
- 提供附件面板、图片预览和附件状态展示。
- 提供可展开/收起的执行详情区域，为后续 trace 事件接入保留稳定消息模型。
- 所有面向用户的界面文案、mock 数据和交互提示使用简体中文；技术名称、代码标识符和工具协议名称可保留英文。
- 使用 mock adapter 驱动页面，确保无 API credential 时也能启动和操作界面。
- 提供可替换的客户端 API 边界，使后续 session gateway、附件上传和 Agent events 可以逐步接入。
- 桌面窗口默认面向本地单用户使用，不在本变更中处理跨平台发布、Python sidecar 打包或真实后端通信。

## Capabilities

### New Capabilities

- `desktop-client`: 提供基于 Tauri 2 和 React 的本地 ChartAgent 桌面工作台及其 mock 交互能力。

### Modified Capabilities

无。当前变更只新增桌面客户端能力，不修改现有 Agent、CLI、附件或 memory 的行为契约。

## Impact

- 新增前端工程目录、Tauri 配置和桌面客户端启动入口。
- 新增 React 组件、前端状态模型、mock 数据和可替换 API client。
- 可能新增 Node/Tauri 开发依赖，但 Python 核心依赖和 Conda `agent` 环境保持不变。
- 后续 `web-session-gateway`、`web-attachment-upload` 和 `web-agent-events` 将以本客户端的协议和状态模型为接入目标。
