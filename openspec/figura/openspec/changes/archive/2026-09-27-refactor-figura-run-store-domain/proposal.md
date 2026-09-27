## Why

`src/figura/runtime/store.py` 同时承担 SQLite 初始化与迁移、SQL 读写、记录映射、Run 状态校验以及跨记录原子转换，职责集中使后续维护和扩展困难。现在将存储实现按领域与持久化职责拆开，可以为后续跨 Run 消息记忆等能力提供清晰边界，同时不改变现有运行行为。

## What Changes

- 将 Run 状态约束和领域转换规则从 SQLite 读写细节中分离，明确领域模型的所有权与持久化映射边界。
- 将数据库连接、schema/迁移、记录映射及存储操作按职责拆入 `runtime` 内部模块。
- 保留 `FiguraRunStore` 作为兼容门面，维持现有构造方式、公开方法、`data_root` / `database_path` 属性及调用方导入路径。
- 保持现有 SQLite schema、schema version、记录格式、错误语义和事务边界不变；原子转换仍在同一事务中提交。
- 不在本 change 中增加跨 Run 消息记忆、裁剪或预算策略，也不新增数据库字段或表。

## Capabilities

### New Capabilities

无。本 change 只重组内部结构，不引入新的外部能力。

### Modified Capabilities

无。可观察行为和持久化契约保持不变；本 change 在 `.openspec.yaml` 中声明 `skip_specs: true`。

## Impact

- 主要涉及 `src/figura/runtime/store.py`、`src/figura/runtime/models.py` 和 `src/figura/runtime/` 下新增的领域及持久化模块。
- 兼容边界包括 `src/figura/runtime/__init__.py`、RunCoordinator、附件服务、工具执行器及直接使用 `FiguraRunStore` 的调用方。
- 回归重点是现有 SQLite schema 与迁移、Run/Session/附件操作、事件序列、provider 与 tool attempt 生命周期、checkpoint 恢复，以及涉及多个记录写入的原子性。
- `src/chartagent/` 及其 OpenSpec store 不属于本 change；实现完成后再由独立 change 处理完整跨 Run 消息记忆。
