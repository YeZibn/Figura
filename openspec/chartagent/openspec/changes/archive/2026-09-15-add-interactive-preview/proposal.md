# Change: Add interactive image preview

## Why

当前前端已经能够加载并展示附件、视觉观察和生成图结果的图片资源，但图片只作为卡片内的静态内容呈现。用户无法点击或通过键盘打开大图，也缺少统一的放大、适应窗口和关闭操作，因此生成结果目前只能查看缩略内容或下载 PNG，难以完成细节核验。

## What Changes

- 增加统一的交互式图片预览能力，支持点击或键盘操作打开预览层，并提供放大、缩小、适应窗口、关闭和 `Escape` 退出等操作。
- 将交互式预览接入附件预览、视觉观察预览、生成候选图和已发布生成结果，确保 Mock、Gateway 和 Tauri 三种前端运行模式行为一致。
- 为生成结果保留现有的下载 PNG 能力，并明确 pending、warning、failed、expired 或无权访问等状态下的预览与下载行为。
- 复用现有 `PreviewResource` 资源边界、图片校验和 object URL 生命周期管理，不改变 Gateway 或 Tauri 的二进制资源 API。
- 为预览层补充可访问名称、键盘焦点和状态提示，使其可被键盘和辅助技术使用。

## Capabilities

### New Capabilities

- `interactive-preview`: 定义图片资源统一进入交互式预览、预览控制、状态处理、可访问性和资源清理行为。

### Modified Capabilities

- `desktop-client`: 将交互式预览接入附件、视觉观察和生成结果界面，同时保持原有选择、删除、下载和状态展示行为。

## Impact

- 受影响的前端区域：`frontend/src/App.tsx`、预览资源相关模块和全局样式，以及对应的前端构建/冒烟测试。
- 不新增或修改 Gateway、Tauri 的资源接口；现有安全的 attachment/preview 资源边界继续作为图片来源。
- 需要新增交互状态、预览层控件和可访问性测试，并验证 `npm run build` 与 `npm run smoke`。
