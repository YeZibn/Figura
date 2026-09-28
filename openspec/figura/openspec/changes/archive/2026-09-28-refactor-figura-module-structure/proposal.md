## Why

Figura 当前代码有些文件承载过多职责，也有些目录方案把模型和简单模块拆得过细，增加了查找与维护成本。需要采用一套中等粒度的功能模块划分，理顺 Agent、Memory、Sources、Runtime、Tools 和 Gateway 的归属，同时保留完整的跨 Run Memory 行为。

## What Changes

- 以功能模块作为主要目录边界，保留 Provider、ChartSpec、Memory 等职责明确的现有模块。
- 将附件和 Panel 归入 Sources，将图片工具归入 Tools 的 implementations，将运行过程派生状态归入 Agent。
- 整理 Runtime 持久化中职责拥挤的代码，并保留现有 SQLite、原子事务与恢复语义。
- 增加清晰的组件组装入口，并明确模块间允许的依赖方向。
- 仅在文件混合了独立职责或难以维护时拆分；不要求每个类独占文件，也不强制采用 domain/application/infrastructure 三层。
- 保留完整的跨 Run 消息 Memory，不加入裁剪、预算或新的持久化机制。

## Capabilities

本 change 只调整内部代码结构，不改变用户可见行为、持久化格式、Provider/Tool 契约或 HTTP/SSE 协议。按 OpenSpec 规则设置 `skip_specs: true`，不新增行为规格。

## Impact

- 影响 `src/figura/` 的包组织、模块导入和组件构造位置。
- 迁移时更新受影响的 Figura 测试导入；保持测试行为断言和测试文件布局不变。
- 不涉及 `src/chartagent/`、前端协议、数据库结构或用户数据迁移。
