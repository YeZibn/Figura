## Why

Agent 核心经过多轮测量、审核、恢复和 panel 路由能力迭代后，关键职责重新集中到 `agent/loop.py`、`measurement.py` 和 `review/manager.py` 等大型模块中，同时遗留了已经被当前 VLM 审核流程取代的旧实现与只做重导出的“伪分层”文件。继续在这些文件上叠加功能会放大回归风险，也让模块边界、公共 API 和测试责任越来越难以判断。

## What Changes

- 清理 Agent、Measurement 和 Review 核心中已确认无调用、已被当前流程取代的私有实现与过期适配器；对仍属于公开或兼容边界的符号保留稳定导出，不把“仓库内未调用”直接等同于可删除。
- 将 Review 的模型、策略、审核器和候选生命周期迁移到真正拥有实现的模块，消除从单一 `manager.py` 重导出的伪分层结构。
- 将单文件 Measurement 领域拆分为范围、证据、质量审核和会话生命周期等聚焦模块，同时通过包级导出保持现有调用方式兼容。
- 将 `Agent.run()` 中的单轮执行、测量决策、panel 路由、恢复/中断和 observation/artifact 投影职责下沉到聚焦的内部协作者，使 `Agent` 保持为稳定的公共编排入口。
- 收紧结构测试：验证真实实现所有权、依赖方向和公共兼容入口，而不再仅验证一组空壳模块能够导入。
- 保持 Agent 行为、工具契约、提示词语义、审核门禁、恢复状态、持久化格式、Gateway API 和前端行为不变。

## Capabilities

### New Capabilities

无。本 change 只重构内部实现，不引入新的系统能力。

### Modified Capabilities

无。本 change 不修改现有 OpenSpec requirement，因此使用 `skip_specs: true`。

## Impact

- 主要影响 `src/chartagent/agent/`、`src/chartagent/measurement/`（替换原单文件领域模块）、`src/chartagent/review/` 及对应 Python 测试。
- 可能调整内部导入和结构兼容测试，但现有受支持的包级导入、Agent 构造与运行入口保持可用。
- 不修改 Gateway/Evaluation 的内部拆分、SQLite schema、HTTP 协议或前端组件；这些属于后续独立 change。
- 不以文件长度为唯一依据拆分图表传感器算法；`bars.py`、`line.py`、`pie.py` 和 rendering 等高回归风险算法模块不在本 change 的主要范围内。
