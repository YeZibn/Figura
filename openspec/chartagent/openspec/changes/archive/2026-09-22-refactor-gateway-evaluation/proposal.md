## Why

核心 Agent 已经完成领域拆分，但 Gateway 和 Evaluation 仍把持久化、运行生命周期、HTTP 投影、恢复以及评测读取、阶段归因、报告生成集中在少数超大型文件中。继续增加重连、只读评测和运行诊断能力会让协议边界与业务实现继续耦合，当前适合在行为稳定后完成第二阶段的内部重构。

## What Changes

- 将 Gateway 的历史存储、运行生命周期、服务编排、HTTP 适配和协议投影拆成职责清晰的内部模块，保留现有公共导入和服务入口。
- 将 Evaluation 的 bundle 读取、样本/批次索引、阶段时间线归约、失败归因和 Markdown/JSON 报告投影拆开，保留现有评测命令与输出结构。
- 建立 Gateway 与 Evaluation 之间单向的数据读取边界：Evaluation 只消费已定义的 run/history/bundle 投影，不直接依赖 Gateway 内部可变对象。
- 删除已确认无调用的私有重复解析、兼容空壳和过时辅助逻辑，保留公开兼容符号与动态注册入口。
- 增加结构所有权、协议序列化、断点恢复、SSE/同步运行和评测报告的回归测试。
- 保持 HTTP API、SQLite schema、Run/Event JSON、评测 bundle 目录结构、前端行为、图表工具和 Agent 决策语义不变。

## Capabilities

### New Capabilities

无。本 change 只重构已存在的 Gateway 和 Evaluation 内部实现，不引入新的运行时能力。

### Modified Capabilities

无。本 change 不改变行为规格，因此使用 `skip_specs: true`。

## Impact

- 主要影响 `src/chartagent/gateway/`、`src/chartagent/evaluation/` 及其 Python 测试、结构兼容测试和集成文档。
- 可能调整 Gateway/Evaluation 内部导入、私有类型和模块路径，但保留 `GatewayService`、协议模型、评测 CLI 和包级公开导出。
- 不修改 `frontend/`、`src/chartagent/agent/`、图表传感器算法、ChartSpec 数据模型、SQLite 表结构或现有 OpenSpec 主规格。
- 所有 Python 验证继续使用 `conda run -n agent`，并覆盖完整 pytest、Gateway lifecycle/recovery、Evaluation bundle/timeline/report 以及现有 smoke 入口。
