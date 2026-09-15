## 1. Preview contract and shared state

- [x] 1.1 定义安全的交互式预览描述类型，覆盖资源引用或 fallback URL、图片 alt、来源类型、标题、状态文本和触发器焦点引用，不携带原始字节或本地路径
- [x] 1.2 在工作区根部增加单一预览打开/关闭状态，并让预览描述能够从附件、视觉观察和生成结果入口传递到共享 overlay
- [x] 1.3 让共享 overlay 使用现有 `PreviewResourceLoader` 和 `usePreviewResource` 独立加载打开后的资源，支持取消未完成请求并在关闭、替换、卸载时调用 `releasePreview`

## 2. Interactive preview overlay

- [x] 2.1 实现有界的 `role="dialog"` 预览层，展示来源身份、标题/说明和状态文本，并提供简体中文的关闭、放大、缩小和适应窗口控件
- [x] 2.2 实现初始适应窗口、有限步进缩放、缩放百分比反馈和 viewport 内的图片布局，确保大图和窄窗口不会溢出工作区
- [x] 2.3 实现关闭按钮、Escape 和明确 backdrop 区域关闭行为；打开时保存来源触发器，关闭后在触发器仍存在时恢复焦点
- [x] 2.4 实现 overlay 的键盘焦点管理：打开后焦点进入 dialog，控件可通过键盘操作，焦点不会落到背景交互内容，且所有控件具有可访问名称和可见焦点样式

## 3. Integrate preview triggers

- [x] 3.1 更新通用 `PreviewImage`，仅在图片资源已成功加载且未发生图片错误时渲染可点击、可聚焦的预览 trigger，并保留加载、无效、不可用和重试状态
- [x] 3.2 将视觉观察和消息中的图片入口接入共享 overlay，确保 pointer、Enter、Space 三种激活方式打开对应资源且不改变会话或运行上下文
- [x] 3.3 更新 `AttachmentPreview` 接入共享 overlay，保留附件勾选、删除、重试和模型加载状态；不可用附件不得渲染可操作的预览 trigger
- [x] 3.4 更新 `GeneratedChartView` 接入共享 overlay，保留生成图表身份、review/publication 状态、pending-with-bytes 行为和独立的“下载 PNG”按钮
- [x] 3.5 统一 available、warning、pending、failed、expired、unauthorized 和图片校验失败的 inline/overlay 状态映射，避免预览成功被误报为审核或发布成功

## 4. Styling and regression coverage

- [x] 4.1 为预览 trigger、overlay、viewport、缩放控件、状态提示和窄窗口布局补充全局样式，并验证状态不只依赖颜色
- [x] 4.2 扩展前端 smoke contract，覆盖共享 overlay、pointer/keyboard trigger、dialog accessibility、zoom/fit/close、生成结果下载独立性和 object URL 清理标识
- [x] 4.3 在 Mock 模式手动验证附件、视觉观察和生成图结果均可打开/关闭/缩放，且选择、删除、重试和下载行为未回归
- [x] 4.4 在 Gateway 浏览器开发模式验证预览仍通过活动 Gateway 资源、错误响应不打开 broken preview、会话切换不会保留 stale image，并验证 Tauri 配置地址仍被使用
- [x] 4.5 运行 `npm run build`、`npm run smoke` 和 `git diff --check`，记录验证结果并修复由 TypeScript、布局或 smoke contract 暴露的问题
