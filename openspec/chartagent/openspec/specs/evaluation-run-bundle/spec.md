# evaluation-run-bundle Specification

## Purpose

为一次包含多个真实图表样本的评测建立独立、可追溯且可复盘的数据边界，统一保存评测配置、样本清单、诊断报告和 Gateway 运行材料，避免与其他评测或普通应用运行混淆。

## Requirements

### Requirement: 每次评测必须拥有独立的批次目录

系统 SHALL 在提交第一个真实样本前创建唯一的 `evaluation_id` 和评测根目录。该目录 SHALL 作为本次评测的唯一持久化边界，不能复用其他评测的 session 数据库、附件目录或 run artifact 目录。

默认根目录 MUST 位于 canonical data root 下的 `evaluations/<evaluation_id>/`；用户显式指定评测根目录时，系统 MUST 使用该目录并保留相同的内部布局。

#### Scenario: 创建一批真实评测

- **WHEN** 用户启动一次包含一个或多个样本的真实评测
- **THEN** 系统在任何 Gateway run 创建前生成唯一的 `evaluation_id` 和对应根目录
- **AND** 本次评测的后续持久化数据全部归属于该目录

#### Scenario: 评测之间必须隔离

- **WHEN** 连续启动两次真实评测
- **THEN** 两次评测使用不同的根目录、`sessions.db`、附件目录和运行 artifact 目录
- **AND** 任一次评测都不会把另一批次的历史或文件纳入自己的汇总

### Requirement: 评测目录必须保存完整的批次索引和运行材料

评测根目录 SHALL 保存 `evaluation.json`、清单快照、批次级 JSON/Markdown 汇总以及每个 case 的诊断报告。Gateway 的 `sessions.db`、上传附件和 run artifacts SHALL 位于同一根目录下的固定子目录中，并通过批次索引关联到 `case_id`、`session_id` 和 `run_id`。

评测索引至少 MUST 记录评测状态、开始/结束时间、provider、model、选中的 case、每个 case 的运行状态和第一失败引用。评测状态 SHALL 支持 `running`、`completed`、`partial` 和 `blocked`。

#### Scenario: 所有样本完成

- **WHEN** 一批评测中的所有 case 都已得到终态
- **THEN** 系统写入 `completed` 的批次索引和汇总，并能从索引定位每个 case 的报告与 run

#### Scenario: 部分样本失败或中断

- **WHEN** 某个 case 失败、超时、被阻塞或评测进程中断
- **THEN** 系统保留已经产生的数据库、附件、观测 artifact 和 case 报告
- **AND** 批次索引标记为 `partial` 或 `blocked`，而不是删除或伪造完整成功结果

### Requirement: 评测批次材料必须遵守脱敏和本地数据边界

系统 MUST 不将 API key、Authorization 头、`.env` 文件或其他凭据复制到评测索引、清单快照或可阅读汇总中。JSON/Markdown 汇总 SHALL 保持现有有界、脱敏的诊断规则；原始数据库、上传图片和观测 artifact 属于本地评测材料，不得被默认当作可分享报告。

#### Scenario: 生成评测索引

- **WHEN** 系统写入批次元数据和汇总
- **THEN** 输出只包含 provider/model、样本指纹、状态和受控引用，不包含凭据或绝对环境路径

#### Scenario: 评测运行失败

- **WHEN** Gateway 或 provider 在评测期间失败
- **THEN** 系统仍保留可用的失败事件和 artifact 引用，并以脱敏错误摘要更新批次索引
