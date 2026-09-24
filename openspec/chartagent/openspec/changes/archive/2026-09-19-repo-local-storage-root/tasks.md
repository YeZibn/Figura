## 1. 建立统一存储路径解析层

- [x] 1.1 新增可注入的 canonical storage resolver/path 集合，统一实现显式 `data_dir` > `CHARTAGENT_DATA_DIR` > 项目根 `.chartagent` 的优先级。
- [x] 1.2 统一规范化相对路径、项目根定位和固定子路径：`sessions.db`、`attachments/`、`run-artifacts/`、`diagnostics/`。
- [x] 1.3 为 resolver 增加覆盖优先级、启动 cwd 变化、绝对/相对路径和显式旧参数兼容测试。

## 2. 统一 Python 持久化组件

- [x] 2.1 让 SQLite session memory 通过 resolver 获取默认数据库，并保持测试注入数据库路径的行为不变。
- [x] 2.2 修改 Gateway service/history/attachment 初始化，使一次 service 使用同一份解析结果；保留显式 attachment/artifact root 覆盖。
- [x] 2.3 让 run artifact 的 retention、大小限制、目录权限和 session 隔离继续作用于新的 `run-artifacts/` 与 `attachments/`。
- [x] 2.4 让真实评测 CLI 的默认输出通过 resolver 指向 `diagnostics/`，同时保留 `--output-dir` 显式覆盖。

## 3. 统一启动入口和配置加载

- [x] 3.1 在 Gateway 长生命周期入口创建 service 前加载 `.env`，增加显式 `--data-dir` 传递，并确保 `serve`/service 的程序化调用可注入解析结果。
- [x] 3.2 在 Agent CLI 的命名 session 操作中支持同一 data-root 配置，保证 list/create/resume/delete 使用和 Agent runtime 相同的数据库。
- [x] 3.3 更新 `frontend/scripts/dev-gateway.mjs` 与 Tauri Gateway 启动器，稳定使用项目根作为启动上下文并透传 `CHARTAGENT_DATA_DIR`/`--data-dir`，不在 Node 侧重复实现路径规则。
- [x] 3.4 为 Gateway、Agent CLI、评测 CLI 和前端启动器补充配置帮助、`.env.example` 与 README，说明默认目录、优先级和固定布局。

## 4. 处理旧目录与生命周期边界

- [x] 4.1 增加对旧 `~/.chartagent` 的非破坏性检测和明确提示；项目根与 home 同时有数据时不得静默选择或双写，并保留显式 `CHARTAGENT_DATA_DIR` 回滚入口。
- [x] 4.2 验证短生命周期裁剪/上传中间文件仍走 OS 临时目录并按现有 finally/清理路径删除，不把它们混入持久化 artifact。
- [x] 4.3 增加数据根目录权限、路径泄露、旧目录冲突和失败启动行为的回归测试。

## 5. 集成验证与交付检查

- [x] 5.1 使用 `conda run -n agent python -m pytest` 先运行存储、Gateway、session、recovery 和评测相关窄测试，再运行完整 Python 测试套件。
- [x] 5.2 运行前端 `npm run build`、`npm run smoke` 及 Gateway 启动/停止回归，确认前端启动的 Gateway 与直接 CLI 看到同一数据根。
- [x] 5.3 执行 `git diff --check`，并完成一次无覆盖、环境覆盖、显式 data-dir 三种模式的本地 smoke，确认目录布局和 `.gitignore` 行为符合规格。
