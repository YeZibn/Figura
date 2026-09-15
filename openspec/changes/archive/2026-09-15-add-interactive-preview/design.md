## Context

当前前端的 `PreviewImage` 和 `AttachmentPreview` 已经通过 `usePreviewResource` 加载图片，并由 `PreviewResourceLoader` 负责 Gateway 资源路径、媒体类型校验、图片解码和 object URL 释放。`GeneratedChartView` 另行维护生成状态与下载逻辑，但所有图片仍然是被动的 `<img>`，没有共享的打开、缩放或关闭状态。详情见 proposal.md - Why；行为边界见本 change 下的 `interactive-preview` 和 `desktop-client` delta spec。

实现必须继续支持 Mock、Gateway 浏览器开发模式和 Tauri 管理的 Gateway 地址，不暴露本地源文件路径或原始二进制，不改变现有预览资源 API。项目当前没有可复用的 UI 弹窗依赖，因此设计应适配现有 React 组件和 CSS 体系。

## Goals / Non-Goals

**Goals:**

- 在工作区级别提供一个共享的图片预览层，并让附件、视觉观察、候选图和生成结果使用同一套触发与控制行为。
- 让预览层拥有清晰的资源生命周期：打开时按资源描述加载，关闭、替换或卸载时中止请求并释放临时 object URL。
- 保留生成结果卡片上的独立下载逻辑、状态标签和元数据，同时让预览层显示必要的图像身份与状态。
- 覆盖鼠标、键盘、焦点恢复、Escape、缩放/适应窗口、错误状态和窄窗口布局。

**Non-Goals:**

- 不改变 Gateway 或 Tauri 的预览、下载、会话和运行接口，不新增服务端存储或数据库字段。
- 不实现图像编辑、裁剪、标注、旋转、批量浏览或跨资源画廊。
- 不把 pending、failed、expired 或 unauthorized 资源伪装成可用图片；也不为不可下载的结果新增绕过权限的下载路径。

## Decisions

### 1. 在工作区维护单一预览控制器和单一 overlay

由 `App` 持有当前预览描述和关闭/打开状态，并在工作区根部渲染一个共享的 `InteractivePreview`。预览描述只包含资源引用或安全 fallback URL、图片 alt、来源类型、标题、状态文本和来源触发器引用；不保存原始字节或本地源文件路径。各类卡片通过 `PreviewImage`/`AttachmentPreview` 的回调提交描述，不能自行创建另一套弹层。

选择工作区级状态，是为了保证附件、视觉观察和生成结果在同一运行上下文中使用相同的焦点、Escape 和 CSS 行为，并避免多个卡片各自挂载弹层导致层级和清理不一致。备选方案是在每张图片旁边复制一个 modal，代码重复且容易出现状态语义和 object URL 清理分叉；不采用。

### 2. 预览层独立拥有打开后的资源租约

打开预览时，`InteractivePreview` 使用已有的 `PreviewResourceLoader` 和资源描述重新取得或使用安全 fallback URL，而不是把内联图片组件拥有的临时 blob URL 直接转交给 overlay。预览层加载完成后独立持有结果，关闭或资源变化时沿用 `releasePreview` 释放 temporary object URL，并用 `AbortController` 取消未完成请求。这样即使触发器因会话切换、运行更新或列表折叠而卸载，打开的预览也不会引用已被触发器清理的 stale URL。

这种设计可能在 Gateway 模式下为打开动作产生一次额外请求，但换来了清晰的所有权和不会悬挂 blob URL 的生命周期。备选方案是新增全局缓存或引用计数资源池；它需要处理缓存失效、会话隔离和下载复用，当前需求不值得引入该复杂度。

### 3. 以安全描述驱动的可用性和状态映射

触发器只在 inline 预览已获得可用图片 URL 时启用；pending 资源沿用生成结果的现有判断，只有已拥有可解码图片时可打开，并在 overlay 中保留“待审核”等状态。available 和 warning 的生成结果保留卡片下载按钮；failed、过期、无权访问、无图片或图片校验失败只显示现有的有界原因，不创建不可用的触发器。

预览层显示来源类型、标题/说明和状态文本，但不重新推断 review/publication 语义。状态的权威来源仍是 `GeneratedChartView` 和已有协议字段，避免把“已渲染”误报为“已审核”或“已发布”。备选方案是让 overlay 自己重新计算生成状态，会造成卡片与 overlay 不一致，因此不采用。

### 4. 使用无新依赖的可访问 modal 交互

overlay 使用现有 React/CSS 实现的 `role="dialog"`、`aria-modal="true"` 和明确的 `aria-labelledby`，打开后把焦点放到关闭按钮或 dialog 容器，关闭后恢复到仍存在的触发器。Escape、关闭按钮和 backdrop 的明确点击区域都关闭；键盘焦点在 overlay 控件间可循环，背景内容在打开时不可操作。缩放状态在 overlay 内部维护，初始为适应窗口，使用有限步进和有界上限，并显示当前百分比；fit 操作恢复初始视图。

选择手写的轻量交互，是因为当前项目没有 modal 依赖且 Tauri/WebView 需要一致行为。备选方案是引入第三方 lightbox，会增加依赖、样式隔离和 Tauri 兼容验证成本；备选方案是跳转到新路由，会丢失当前会话上下文；两者都不采用。

### 5. 让所有入口共享能力，但保持附件动作和生成下载独立

附件缩略图和视觉观察图只增加 preview trigger，不改变附件勾选、删除、重试或模型加载含义。生成图结果继续由 `GeneratedChartView` 决定状态和下载权限，预览 trigger 与“下载 PNG”并列但不互相调用；overlay 不取代卡片上的下载按钮。这样用户可以检查细节而不触发下载，也不会因图片可预览而误以为 artifact 一定可下载。

## Risks / Trade-offs

- [额外资源请求] → 打开 Gateway 预览时可能再次获取图片；通过仅在用户明确打开时加载、复用已有 loader 校验和在关闭时中止请求来控制成本。
- [大图占用内存] → overlay 使用有界 viewport、CSS 适应窗口和有限缩放上限；每次关闭都释放其 temporary object URL。
- [焦点管理回归] → 为打开、Escape、按钮关闭、触发器卸载和键盘循环增加自动化检查，并保持原有 session/delete dialogs 的实现不变。
- [状态与 UI 不一致] → 预览描述携带来源状态但不复制状态推断；生成卡片继续作为状态单一来源，并对 available/warning/pending/failed 分别验证。
- [fallback URL 生命周期不明确] → overlay 只对 loader 返回且标记为 temporary 的 blob URL 执行释放；非 temporary fallback 不由预览层 revoke，避免破坏调用方所有权。

## Migration Plan

1. 先在前端新增共享预览描述、overlay 控制器和样式，再把视觉观察、生成结果和附件入口逐一接入。
2. 增加交互、资源清理、状态和可访问性测试，在 Mock 模式验证后执行 Gateway 浏览器冒烟测试，并运行 `npm run build` 和 `npm run smoke`。
3. 发布后若发现交互回归，可回滚前端预览入口和 overlay；资源 API、附件数据和生成结果协议无需迁移或回滚。
