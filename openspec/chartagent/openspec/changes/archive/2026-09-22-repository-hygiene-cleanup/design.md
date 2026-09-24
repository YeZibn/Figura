## Context

See `proposal.md` for the motivation and scope. 当前仓库的运行时入口已经完成过多次目录迁移，但开发脚本、集成文档和前端 TypeScript 构建配置没有完全同步。前端根 `tsconfig` 通过 project reference 检查 `vite.config.ts`，现有配置会把编译结果写回 `frontend/` 源码目录；同时，图表理解 smoke 脚本仍引用迁移前的模块名。

本 change 是仓库卫生修复，不改变 Agent、Gateway、工具注册、持久化数据或前端业务行为。所有 Python 命令和测试均使用 `conda run -n agent`。

## Goals / Non-Goals

**Goals:**

- 让图表理解 smoke 脚本能够在当前模块布局下启动。
- 让集成文档和根包说明反映当前代码结构。
- 让前端类型检查的生成输出进入被忽略的临时目录，不再污染源码目录。
- 移除已经提交的前端生成物，并增加可重复的仓库卫生验证。

**Non-Goals:**

- 不删除 `review`、`cartesian`、`attachments` 等兼容模块。
- 不拆分 `agent/loop.py`、`measurement.py`、Gateway 或 `App.tsx`。
- 不调整 OpenSpec 主规格、运行时 API、持久化 schema、评测数据格式或工具契约。
- 不处理 `.qoder`、`.trae` 或 OpenSpec archive；这些属于独立的工具配置/历史保留策略。

## Decisions

### 1. 修复现有 smoke 入口，而不是直接删除

将 `smoke_chart_understanding.py` 的旧 `spec_tools` 导入切换到当前 `tools.chart.specification` 模块，并保留脚本的原有用途。它仍然是一个真实 provider smoke 入口，删除会减少现有诊断能力；如果后续确认没有调用价值，再另行移除。

备选方案是删除脚本，但这会把“当前不用”误判成“永远不需要”，不适合本次低风险清理。

### 2. 使用构建输出目录隔离生成物，而不是只依赖 `.gitignore`

调整 `frontend/tsconfig.node.json`，让 project reference 的 JavaScript、声明文件和增量信息写入 `frontend/node_modules/.tmp` 下的构建临时目录；同时在 `.gitignore` 中补充 `*.tsbuildinfo` 作为兜底规则。这样可以保留 `npm run build` 的类型检查语义，并避免通过忽略规则掩盖源码目录被污染的问题。

备选方案是只忽略 `vite.config.js` 和 `vite.config.d.ts`。该方案无法阻止构建继续写源码目录，也容易留下更多未跟踪生成物，因此不采用。

### 3. 更新文档，不重写项目结构

只修正 `docs/Figura-integration-guide.md` 的入口路径和 `src/chartagent/__init__.py` 的过时说明，保持文档的现有组织方式。这样可以消除误导，又不会把本 change 扩展成新的架构文档项目。

### 4. 验证以“运行 + 无污染”为核心

验证分为三层：

1. Python smoke 脚本可启动，结构兼容测试和相关图表理解测试通过。
2. 前端 `npm run build` 与现有 smoke 命令通过。
3. 构建后工作区只包含预期源码/文档变更，不重新生成已删除的根目录构建产物，并通过 `git diff --check`。

## Risks / Trade-offs

- **[Risk]** TypeScript project reference 对 `outDir`、声明文件和增量构建有约束，配置不当会使 `npm run build` 失败。→ 先在实现中验证完整前端 build，再删除旧生成物；失败时只回滚构建配置，不影响 Python 代码。
- **[Risk]** smoke 脚本可能依赖本地 provider 配置。→ 将“模块可导入/帮助可启动”与“真实 provider 调用”分开验证，不把网络凭据作为仓库卫生测试前置条件。
- **[Risk]** 文档路径修正可能遗漏其他旧引用。→ 使用 `rg` 搜索旧路径和 `spec_tools`，并在验证任务中要求结果为空。
- **[Risk]** 删除已跟踪生成物会影响本地已有构建流程。→ 先确认 TypeScript 输出已隔离到 `node_modules/.tmp`，再从 Git 中移除生成物；Git 可通过恢复对应文件回滚。
