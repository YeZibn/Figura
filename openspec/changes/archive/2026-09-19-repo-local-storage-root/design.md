## Context

See `proposal.md` for the motivation and scope. 当前持久化路径由多个模块分别推导：SQLite 使用 `default_database_path()`，Gateway history 和附件各自读取环境变量，评测 CLI 直接使用相对的 `.chartagent/diagnostics`，而 Gateway 服务入口在构造服务前没有保证 `.env` 已加载。前端启动脚本还会注入 `CHARTAGENT_ENV_FILE`，但不负责把其中的配置复制成另一套路径规则。

本变更需要同时覆盖 Python 运行时、Gateway、评测 CLI、前端启动器和文档；测试又大量通过显式 `tmp_path` 注入数据库或 artifact 根目录，因此不能用全局状态替换显式依赖。

## Goals / Non-Goals

**Goals:**

- 建立一个可注入的 storage-paths 解析层，产出 canonical root 及其固定子路径。
- 让各持久化组件在一次运行内共享同一份解析结果，而不是分别读取环境变量。
- 保持现有显式数据库、附件目录、artifact 根目录和评测输出目录的覆盖能力。
- 让 Gateway 进程在创建 service 前完成环境配置加载，并让前端/Tauri 启动方式与 Python 入口使用同一解析结果。
- 对旧 `~/.chartagent` 数据和权限/清理边界给出可操作、可测试的行为。

**Non-Goals:**

- 不改变 Agent、图表测量、分区、装配或真实评测的业务逻辑。
- 不把局部裁剪等短生命周期观察文件改成持久化 artifact。
- 不在本变更中实现云端存储、跨机器同步或完整的数据格式迁移器。
- 不自动合并项目 `.chartagent` 与 `~/.chartagent` 中不确定归属的数据库和附件。

## Decisions

### 1. 用单一解析器和不可变路径集合作为 source of truth

新增一个轻量的 storage 配置对象/解析函数，负责确定：

```text
root/
├── sessions.db
├── attachments/
├── run-artifacts/
└── diagnostics/
```

解析优先级固定为：调用方显式 `data_dir` > `CHARTAGENT_DATA_DIR` > 项目根目录 `.chartagent`。相对路径统一相对于项目根目录解析，并在进入存储组件前规范化为绝对路径。组件只接收解析后的路径集合；SQLite、Gateway history、attachment store 和评测报告生成器不再各自重新解释环境变量。

选择集中解析而非继续在每个模块中拼接路径，是为了让数据库父目录、附件、run artifact 和诊断输出不会因不同入口产生分叉。显式的独立目录参数仍然保留给测试和受控部署，但必须在构造时明确传入，不参与默认路径推导。

### 2. 把 `data_dir` 作为一等入口，保留旧参数兼容

Gateway `serve`/CLI 和 Agent CLI 增加显式 data-root 传递；现有 `--database`、附件目录、artifact root、评测 `--output-dir` 继续可用。仅提供旧 `--database` 时，将其父目录作为派生持久化目录的兼容基准，避免历史调用出现数据库在一个目录、附件/artifact 在另一个默认目录的情况；同时在新调用中优先推荐 `--data-dir`。

服务层在一次初始化中解析路径集合，再把对应路径显式传给 history 和 attachment 组件。这样既能满足默认统一，又不破坏现有测试中直接注入 `tmp_path / "sessions.db"` 或独立 artifact root 的方式。

### 3. 在 Python 入口加载环境，在库层保持显式可测试

长生命周期入口（Gateway CLI、Agent CLI、评测 CLI）先调用现有 `load_environment()`，再解析 storage 配置。`CHARTAGENT_ENV_FILE` 仍是环境文件入口；环境文件加载只负责填充进程配置，不由 Node 脚本复制 `.env` 内容。

Gateway 的 `serve(...)` 和 `GatewayService(...)` 仍支持程序化调用，调用方可以直接传入 `data_dir` 或已解析的路径；测试通过显式参数绕过进程环境。这样可以修复当前 Gateway 直接启动时 `.env` 可能尚未生效的问题，同时避免 storage resolver 隐式读取文件造成单元测试污染。

### 4. 前端启动器只传递配置，不维护第二套存储逻辑

前端 `dev-gateway.mjs` 和 Tauri 启动器继续负责选择 Conda 环境、Gateway 环境文件和工作目录，但不自行创建数据库或解析附件路径。它们将项目根作为稳定启动上下文，透传 `CHARTAGENT_DATA_DIR` 或显式 `--data-dir`（若用户在启动配置中提供），并由 Python storage resolver 完成最终规范化。

这种方式优于让 Node 和 Python 各自解析 `.env`：两边只共享配置入口，路径语义只有一份；同时保留前端脚本现有的环境注入和子进程生命周期管理。

### 5. 旧目录采用显式迁移边界，不做静默双写

当选择项目默认根时，启动检查可以识别仍存在的 `~/.chartagent`。若旧目录包含数据而项目根没有明确选择，返回带路径类别和处理建议的可恢复提示；若两个根都已有数据且未显式指定，则拒绝继续使用含糊的默认状态。应用不自动合并 SQLite、附件和 artifact。

用户可以通过 `CHARTAGENT_DATA_DIR` 或 `--data-dir` 明确继续使用旧目录，或在停机后手工移动到 `.chartagent`。这比自动迁移更容易回滚，也不会在 API key、附件哈希或 run 记录归属不明时造成不可逆合并。

### 6. 保持安全权限和生命周期语义

目录创建沿用现有 application-owned storage 的权限约束：根目录、附件和 run artifact 不向其他用户开放；数据库和临时上传文件的权限不放宽。`run-artifacts` 的现有 retention/size 清理继续有效。诊断报告属于持久输出并进入 `diagnostics/`，而观测阶段的临时裁剪文件继续使用 OS 临时目录并在 finally 路径清理。

## Risks / Trade-offs

- [Risk] 默认路径从用户 home 改为项目目录，旧版本留下的 session 不会自动出现 → [Mitigation] 提供旧目录检测、明确提示和 `CHARTAGENT_DATA_DIR`/`--data-dir` 兼容入口，文档给出一次性移动步骤。
- [Risk] 多个入口加载 `.env` 的顺序不一致会继续造成路径分叉 → [Mitigation] Python 长生命周期入口在创建任何 store 前统一加载环境；Gateway service 接收显式解析结果；增加从前端启动到 Gateway 的集成回归测试。
- [Risk] 保留多个显式覆盖参数会让调用方故意构造“数据库和附件分离” → [Mitigation] 默认路径全部由同一 `StoragePaths` 派生，独立覆盖只保留给显式参数，并在日志/诊断中记录受控的路径类别而不泄露绝对路径。
- [Risk] 相对路径解析基准变化可能影响脚本调用 → [Mitigation] 在 CLI 帮助、README 和测试中明确“相对 data/output 路径相对于项目根”，对显式绝对路径保持原样。
- [Risk] 诊断报告目录切换后已有临时报告不可见 → [Mitigation] 本变更不删除旧报告；启动和文档明确新旧目录边界，评测仍允许 `--output-dir` 显式指定旧目录。

## Migration Plan

1. 先落地 resolver、路径注入和测试，保持显式 `CHARTAGENT_DATA_DIR`、`--database` 及各类 root override 可用。
2. 更新 Gateway/CLI/frontend 启动顺序和默认值；新运行默认只写项目 `.chartagent/`，并继续由 Git ignore 排除。
3. 对仍存在的 `~/.chartagent` 做非破坏性检测；不自动合并。用户选择继续使用旧目录时显式设置 `CHARTAGENT_DATA_DIR`，选择迁移时停机移动并重新启动验证 session、附件和 artifact。
4. 若新版本出现问题，可通过显式 `CHARTAGENT_DATA_DIR` 指回原目录或使用显式数据库/输出目录回滚，不需要回滚数据库 schema。

