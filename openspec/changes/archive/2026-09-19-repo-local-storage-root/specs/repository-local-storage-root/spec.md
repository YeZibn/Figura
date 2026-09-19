## Purpose

为 Figura 的会话、附件、运行产物和诊断报告提供单一、可预测且可覆盖的数据根目录，使不同启动入口不会因为默认路径不同而产生分叉状态。

## ADDED Requirements

### Requirement: Durable data uses one canonical root

系统 SHALL 为所有默认持久化数据解析同一个 canonical data root。解析优先级 SHALL 为：调用方显式提供的 data directory、`CHARTAGENT_DATA_DIR`、项目根目录下的 `.chartagent/`；相对配置路径 SHALL 以项目根目录为基准解析，而不是以任意启动进程的当前目录为基准。

#### Scenario: No override is configured

- **WHEN** 用户从项目的 Gateway、CLI 或前端启动器启动应用，且未提供显式目录或 `CHARTAGENT_DATA_DIR`
- **THEN** 会话数据库、附件、运行产物和诊断报告都使用项目根目录下的 `.chartagent/`

#### Scenario: Environment override is configured

- **WHEN** `CHARTAGENT_DATA_DIR` 指向一个受控目录且调用方没有更高优先级的显式目录
- **THEN** 所有默认持久化类别都从该目录派生，且不得同时回退写入项目 `.chartagent/` 或用户 home 目录

#### Scenario: Explicit directory wins

- **WHEN** Gateway、CLI 或服务构造调用显式指定 data directory
- **THEN** 显式目录覆盖环境变量和项目默认值，并被该运行中的所有持久化组件一致使用

#### Scenario: Frontend and Gateway agree on the root

- **WHEN** 前端开发启动器或 Tauri 启动器拉起 Gateway
- **THEN** 启动器与 Gateway 对 data root 得出相同结果，且不会因启动器的当前工作目录不同而产生第二套持久化状态

### Requirement: Durable categories have a stable local layout

系统 SHALL 在 canonical data root 下使用稳定的子目录和文件布局：会话数据库为 `sessions.db`，持久附件位于 `attachments/`，运行产物位于 `run-artifacts/`，诊断报告位于 `diagnostics/`。这些类别 SHALL 共享根目录但保持内容隔离。

#### Scenario: A named session creates durable state

- **WHEN** 用户创建或恢复命名 session 并产生运行记录
- **THEN** session 数据写入 canonical root 下的 `sessions.db`，而不是另一个默认数据库

#### Scenario: A run produces artifacts and diagnostics

- **WHEN** Gateway 运行产生持久 artifact 或真实图表诊断报告
- **THEN** artifact 和诊断文件分别进入 `run-artifacts/` 与 `diagnostics/`，并可通过受控引用关联到 run

#### Scenario: Attachment storage is derived from the same root

- **WHEN** 附件没有提供独立的显式覆盖目录
- **THEN** 附件源文件进入 canonical root 下的 `attachments/`，且不因数据库、Gateway 或评测入口不同而改变默认位置

### Requirement: Legacy and ephemeral storage boundaries are explicit

系统 MUST 防止项目 `.chartagent/`、`~/.chartagent/` 和其他默认目录被静默双写或自动合并。检测到旧 home 数据时，系统 SHALL 提供可定位的迁移/显式配置提示；当多个候选持久化根同时存在且无法确定用户意图时，系统 SHALL 拒绝静默选择。短生命周期的裁剪图、临时上传中间文件等不需要持久化的内容 SHALL 继续使用受控的 OS 临时路径，并在生命周期结束后清理。

#### Scenario: Legacy home data exists without an explicit choice

- **WHEN** 默认项目根被选中但旧的 `~/.chartagent` 仍包含可识别的数据，且用户未指定迁移或 data root
- **THEN** 系统返回明确的提示或可恢复状态，不自动复制、合并或同时写入两套数据

#### Scenario: Both roots already contain state

- **WHEN** 项目 `.chartagent/` 和 `~/.chartagent/` 都包含可用 session 或 artifact，且调用方没有显式选择
- **THEN** 系统不得静默选择其中一套，必须要求显式 data root 或迁移动作，并保留可定位的冲突信息

#### Scenario: Ephemeral crop is created

- **WHEN** 图表分析只需要一个短生命周期的局部裁剪文件
- **THEN** 文件可以位于 OS 临时目录，并在调用结束或失败清理后消失，不被要求写入 `run-artifacts/` 或其他持久化目录
