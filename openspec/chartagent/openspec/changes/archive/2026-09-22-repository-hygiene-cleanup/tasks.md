## 1. 修复旧入口与文档

- [x] 1.1 将 `scripts/smoke_chart_understanding.py` 的 `spec_tools` 导入更新为当前 `tools.chart.specification` 入口，并确认脚本参数解析可以启动。
- [x] 1.2 更新 `docs/Figura-integration-guide.md` 中的 Agent、runtime 和目录结构路径。
- [x] 1.3 修正 `src/chartagent/__init__.py` 中已经与当前实现不符的模块说明。
- [x] 1.4 使用 `rg` 检查仓库内是否仍有生产文档或脚本引用 `chartagent.tools.chart.spec_tools`、`src/chartagent/agent.py` 或 `src/chartagent/runtime.py`，并只保留必要的历史 OpenSpec 记录。

## 2. 隔离前端构建产物

- [x] 2.1 调整 `frontend/tsconfig.node.json`，让 project reference 的编译输出和增量信息写入 `frontend/node_modules/.tmp` 下的临时目录，不再写入 `frontend/` 源码目录。
- [x] 2.2 在 `.gitignore` 中补充 TypeScript 增量构建缓存规则，并确认规则不会忽略源码配置或用户需要提交的文件。
- [x] 2.3 从版本控制中移除 `frontend/vite.config.js`、`frontend/vite.config.d.ts` 和 `frontend/tsconfig.node.tsbuildinfo`，保留对应的 TypeScript 源配置。

## 3. 验证仓库卫生

- [x] 3.1 使用 `conda run -n agent python scripts/smoke_chart_understanding.py --help`，并运行结构兼容、CLI 和图表理解相关测试。
- [x] 3.2 在 `frontend/` 执行 `npm run build`，确认构建成功且生成文件只位于被忽略的临时目录。
- [x] 3.3 在 `frontend/` 执行现有 `npm run smoke`，确认前端启动和 launcher 检查没有回归。
- [x] 3.4 执行 `git diff --check`、旧路径搜索和工作区状态检查，确认没有新的源码目录生成物或未处理的旧引用。
