## Why

Figura 的会话列表没有删除入口，旧会话及其对话、运行记录和图片会持续保留，用户无法整理工作区。需要为 Figura 网页模式提供明确的永久删除操作，并让界面、Gateway、Runtime 与 Sources 对删除范围和失败行为保持一致。

## What Changes

- 在 Figura 会话列表中为每个会话提供删除操作；确认前明确展示会话名称以及将一并删除的对话、运行记录和相关图片。
- 增加 Session 删除 API。运行中的 Session 拒绝删除；成功后从列表移除，若删除的是当前会话则切换到剩余会话或空状态。
- 永久删除该 Session 的 Runtime 执行数据、Sources 附件与 Panel 数据及私有图像文件、ChartFigure 渲染 PNG；保留其他 Session 的数据。
- 将逐条执行事实不可变规则限定为记录生命周期内不可修改；显式 Session 聚合删除是受控的数据清除操作。

## Capabilities

### New Capabilities

<!-- None. Session deletion extends existing Figura lifecycle and client capabilities. -->

### Modified Capabilities

- `figura-web-client`: 增加 Figura 会话删除入口、确认、成功后的列表状态更新与错误反馈。
- `figura-web-gateway`: 增加 Session-scoped `DELETE` 操作及运行中拒绝、未知 Session 和安全错误行为。
- `run-execution-core`: 定义只能删除非运行中 Session，并作为一个聚合清除其所有 Runtime 执行事实。
- `image-attachment-storage`: Session 删除时清除该 Session 的附件/Panel 元数据与私有图片文件。
- `panel-image-observation`: Session 删除时清除该 Session 拥有的 Panel 元数据与独立 PNG。
- `chart-rendering`: Session 删除时清除由该 Session Run 生成的私有 ChartFigure PNG 文件。

## Impact

- Frontend: `FiguraApp`, shared `SessionSidebar`, `FiguraClient`, Figura workspace adapter, and delete confirmation dialog.
- Gateway/Runtime: Session-scoped HTTP route, active-Run guard, coordinated permanent deletion, and database constraints/triggers for authorized aggregate purge.
- Sources/Charts: ownership-scoped cleanup for attachment, Panel, and ChartFigure render files with recoverable handling of filesystem failures.
- Tests/specs: Gateway, Runtime, Sources, render-storage, and Figura frontend regression coverage; six existing Figura capabilities receive delta specs.
