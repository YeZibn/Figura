## Why

项目经过多轮功能迭代后，仓库中出现了失效的旧路径、过时的结构文档和被提交的前端构建产物。它们会误导后续开发、让 smoke 检查在启动阶段直接失败，并把生成文件与源码混在一起。本 change 先完成低风险、可验证的仓库卫生清理，为后续兼容层收缩和大模块拆分建立干净基线。

## What Changes

- 修复 `scripts/smoke_chart_understanding.py` 对已迁移 `spec_tools` 模块的导入，使现有图表理解 smoke 入口能够启动。
- 更新集成指南中的 Agent、runtime 和当前目录结构路径，并修正根包中过时的模块说明。
- 从版本控制中移除前端 TypeScript/Vite 构建生成物，调整构建配置避免它们再次落到源码目录，并补充构建缓存忽略规则。
- 增加针对上述仓库卫生约束的轻量验证，确保旧路径和生成物不会重新混入。
- 保持 Python、Gateway、前端运行时、ChartSpec、图表工具、评测数据格式和公开兼容模块的行为不变。

## Capabilities

### New Capabilities

无。本 change 只涉及文档、构建卫生和失效开发脚本修复，不引入新的运行时能力。

### Modified Capabilities

无。本 change 不改变任何主 OpenSpec requirement，因此使用 `skip_specs: true`。

## Impact

- 影响 `scripts/`、`docs/`、`src/chartagent/__init__.py`、`frontend/tsconfig*.json`、`.gitignore` 以及已提交的前端生成物。
- 不改变生产 API、持久化 schema、Agent 工具契约或前端用户功能。
- 验证需要使用 `conda run -n agent` 执行 Python 检查，并运行前端构建确认构建产物不再写入源码目录。
