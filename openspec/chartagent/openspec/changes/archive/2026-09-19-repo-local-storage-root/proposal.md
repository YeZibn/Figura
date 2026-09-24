## Why

Figura 的持久化目录已经在工作区内手工整理过，但代码仍然在多个入口上保留不同的默认路径：会话数据库、附件、运行产物和真实图表诊断结果可能落到项目外的 `~/.chartagent`、临时目录或调用进程当前目录。这样会造成同一项目出现多份状态，前端 Gateway 与 CLI 也可能使用不同的数据源；重启、排查和清理时很难判断哪一份才是有效记录。现在需要把“项目本地 `.chartagent` 是默认持久化根目录”固化为代码、启动入口、测试和文档共同遵守的契约。

## What Changes

- 引入统一的数据根目录解析规则：显式参数优先，其次使用 `CHARTAGENT_DATA_DIR`，最后回退到项目根目录的 `.chartagent/`。
- 让会话数据库、附件、Gateway run artifacts 和真实评测诊断输出从同一个数据根目录派生，并保持固定的子目录布局。
- 统一 Gateway、Python CLI、前端开发启动器和 Tauri 启动器对数据根目录及 `.env` 的加载时机，避免启动方式不同导致路径分叉。
- 为相对路径定义稳定的解析基准，并保留显式附件目录等高级覆盖能力，以兼容测试和受控部署。
- 增加旧版用户目录数据的安全提示/迁移边界：不得在项目目录和 `~/.chartagent` 同时静默写入，也不得自动合并来源不明的两套数据库。
- 更新相关 OpenSpec、README、环境变量示例和回归测试；短生命周期的 OS 临时裁剪文件仍保持临时性质，不迁移为持久化数据。

## Capabilities

### New Capabilities

- `repository-local-storage-root`: 定义 Figura 持久化数据根目录、子目录布局、优先级、路径解析和旧目录安全边界。

### Modified Capabilities

- `agent-session-memory`: 命名 session 的默认数据库位置改为统一数据根目录下的 `sessions.db`。
- `attachment-access`: 持久附件默认保存到统一数据根目录下的 `attachments/`，并继续保持 session 隔离和安全引用约束。
- `cli-gateway`: Gateway/CLI 启动时必须使用同一数据根目录解析规则，并支持显式传递该根目录。
- `real-chart-evaluation`: 诊断报告默认保存到统一数据根目录下的 `diagnostics/`，不再依赖散落的工作目录或临时目录。

## Impact

- 受影响代码：`src/chartagent/memory`、`src/chartagent/gateway`、`src/chartagent/evaluation`、运行时配置加载，以及 `frontend/scripts` 的 Gateway/Tauri 启动脚本。
- 受影响接口：新增或统一 `data-dir` 配置入口；保留 `CHARTAGENT_DATA_DIR` 和显式附件目录覆盖语义，并明确优先级。
- 受影响运维行为：默认会话和运行数据将写入项目 `.chartagent/`；该目录继续由 Git 忽略，用户可通过显式配置将其迁移到其他受控目录。
- 不改变图表分析、测量、装配、评测判定逻辑，也不要求把短生命周期的系统临时文件持久化。
