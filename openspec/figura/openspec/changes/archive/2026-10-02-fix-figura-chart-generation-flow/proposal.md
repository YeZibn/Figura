## Why

最新 `test` 对话已成功装配并生成两张饼图，但后续 DeepSeek 请求在本地预检失败，Run 没有形成最终答复；生成图像还出现标题重叠、裁切和百分比缺失。需要修复这条已存在的装配、渲染、回看链路，同时让预检失败留下可理解的安全原因。

## What Changes

- 区分 DeepSeek 实际返回的 reasoning 字段缺失、显式 null、空字符串和非空字符串；有字段时按原值私有保存并回放，不制造 reasoning。
- 调整 continuation 的内部类型、校验和 SQLite 约束，以正常迁移保留已有数据；真正缺失必要字段时继续拒绝请求。
- 本地 Provider 预检失败复用 Run 的 `terminal_message` 保存经过允许列表映射的安全原因，不增加 Provider attempt。
- 改善固定画布上的总标题、子图标题、绘图区和来源备注布局；饼图默认显示一位小数百分比。
- 在现有装配工具描述和 schema 中明确 pie 的 category/value、无 series、无笛卡尔 axes 约束，不改变 ChartSpec 字段集合。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `provider-continuation-persistence`: 保留 DeepSeek reasoning 字段的显式空值语义及迁移、回放边界。
- `run-execution-core`: 本地 Provider 预检失败保存安全且具体的终止原因。
- `chart-rendering`: 固定画布的文字布局和饼图百分比显示要求。
- `chart-figure-assembly`: 模型可见的 pie 装配约束说明。

## Impact

涉及 `src/figura/providers`、`runtime`、`storage`、`charts/chartfigure` 及实际装配工具定义和对应回归测试。SQLite schema 从当前版本 8 迁移到 9；保持 continuation 身份、关联关系和原值，保留现有业务字段与 HTTP/SSE 字段。无需新增依赖、前端控件或 execution resource 类型。旧 Run 已遗失的 reasoning 无法推断补回；本次不重开失败 Run，不自动同步主规格、归档或提交。
